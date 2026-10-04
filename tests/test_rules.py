"""核心业务规则测试：

1. 完整流程可正常交车
2. 固化时间未到禁止交车
3. 验收未通过禁止交车
4. 保险拒赔后必须生成新报价并由车主重新授权才能交车，原报价保留
5. 迟到的理赔回执不覆盖车主已确认的方案
6. 施工暂停后必须确认新方案（型号变更还需重新确认库存）才能恢复施工
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.database import Base, engine
from backend.main import app
from backend.seed import seed_all

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_db():
    """每个用例使用全新的数据库（含库存与模拟保险回执）。"""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    seed_all(include_demo=False)
    yield

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082"
)


def iso_in(seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def create_wo(**over):
    payload = {
        "plate_number": "沪A·T0001", "owner_name": "测试车主", "owner_phone": "13800000000",
        "vehicle_model": "丰田凯美瑞", "glass_model": "FW-CAMRY-2020",
        "damage_desc": "前挡破裂", "estimated_pickup_at": iso_in(86400),
        "glass_price": 1800, "labor_fee": 500, "other_fee": 100,
        "payment_method": "INSURANCE", "insurance_amount": 2000,
    }
    payload.update(over)
    r = client.post("/api/workorders", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def owner_confirm(wo, quote_id):
    token = wo["owner_path"].rsplit("/", 1)[-1]
    r = client.post(f"/api/owner/{token}/quotes/{quote_id}/confirm")
    assert r.status_code == 200, r.text
    return r.json()


def poll():
    r = client.post("/api/insurance/poll")
    assert r.status_code == 200, r.text
    return r.json()


def detail(wid):
    r = client.get(f"/api/workorders/{wid}")
    assert r.status_code == 200, r.text
    return r.json()


def finish_installation(wid, curing_in_seconds=-60, acceptance="PASSED"):
    r = client.post(f"/api/workorders/{wid}/installation/finish", json={
        "glue_type": "聚氨酯结构胶", "curing_deadline": iso_in(curing_in_seconds)})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/workorders/{wid}/installation/acceptance",
                    json={"result": acceptance, "note": "测试验收"})
    assert r.status_code == 200, r.text


def prepare_installable(wo, claim_delay=0, force=None):
    """确认报价 -> 提交并批复理赔 -> 确认库存 -> 开始施工 -> 上传照片。"""
    wid = wo["id"]
    owner_confirm(wo, wo["quotes"][0]["id"])
    body = {"delay_seconds": claim_delay}
    if force:
        body["force_decision"] = force
    r = client.post(f"/api/workorders/{wid}/claims", json=body)
    assert r.status_code == 200, r.text
    return wid


def test_full_flow_deliver():
    wo = create_wo()
    wid = wo["id"]
    prepare_installable(wo)
    poll()
    d = detail(wid)
    assert d["claims"][0]["status"] == "APPROVED"

    assert client.post(f"/api/workorders/{wid}/inventory/confirm").status_code == 200
    assert client.post(f"/api/workorders/{wid}/start-work").status_code == 200
    r = client.post(f"/api/workorders/{wid}/photos",
                    files={"file": ("p.png", PNG, "image/png")}, data={"stage": "AFTER"})
    assert r.status_code == 200, r.text
    finish_installation(wid)

    check = client.get(f"/api/workorders/{wid}/delivery-check").json()
    assert check["deliverable"], check
    r = client.post(f"/api/workorders/{wid}/deliver")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DELIVERED"


def test_curing_not_ready_blocks_delivery():
    wo = create_wo()
    wid = wo["id"]
    prepare_installable(wo)
    poll()
    client.post(f"/api/workorders/{wid}/inventory/confirm")
    client.post(f"/api/workorders/{wid}/start-work")
    client.post(f"/api/workorders/{wid}/photos",
                files={"file": ("p.png", PNG, "image/png")}, data={"stage": "AFTER"})
    finish_installation(wid, curing_in_seconds=3600)  # 固化截止在 1 小时后

    check = client.get(f"/api/workorders/{wid}/delivery-check").json()
    assert not check["deliverable"]
    curing = next(c for c in check["checks"] if c["key"] == "curing")
    assert not curing["passed"]
    r = client.post(f"/api/workorders/{wid}/deliver")
    assert r.status_code == 400
    assert "固化" in r.json()["detail"]


def test_failed_acceptance_blocks_delivery():
    wo = create_wo()
    wid = wo["id"]
    prepare_installable(wo)
    poll()
    client.post(f"/api/workorders/{wid}/inventory/confirm")
    client.post(f"/api/workorders/{wid}/start-work")
    client.post(f"/api/workorders/{wid}/photos",
                files={"file": ("p.png", PNG, "image/png")}, data={"stage": "AFTER"})
    finish_installation(wid, acceptance="FAILED")

    r = client.post(f"/api/workorders/{wid}/deliver")
    assert r.status_code == 400
    assert "验收" in r.json()["detail"]


def test_denial_requires_new_confirmed_quote_and_keeps_original():
    wo = create_wo()
    wid = wo["id"]
    prepare_installable(wo, force="DENIED")
    poll()
    d = detail(wid)
    assert d["claims"][0]["status"] == "DENIED"

    # 拒赔后：不能开工（保险未批复）
    client.post(f"/api/workorders/{wid}/inventory/confirm")
    r = client.post(f"/api/workorders/{wid}/start-work")
    assert r.status_code == 400 and "保险" in r.json()["detail"]

    # 生成自费新报价（必须填写方案说明）
    r = client.post(f"/api/workorders/{wid}/quotes", json={
        "reason": "DENIAL_CONVERT", "glass_model": "FW-CAMRY-2020",
        "glass_price": 1800, "labor_fee": 500, "other_fee": 100,
        "payment_method": "SELF_PAY", "note": "保险拒赔，转自费：总价 2400 元全部由车主承担"})
    assert r.status_code == 200, r.text
    d = detail(wid)
    assert len(d["quotes"]) == 2
    assert d["quotes"][0]["status"] == "CONFIRMED"   # 原报价仍保留
    assert d["quotes"][1]["status"] == "PENDING_OWNER"

    # 新报价未获车主确认（未重新授权）-> 禁止交车
    check = client.get(f"/api/workorders/{wid}/delivery-check").json()
    assert not check["deliverable"]
    qcheck = next(c for c in check["checks"] if c["key"] == "quote_confirmed")
    assert not qcheck["passed"]

    # 车主确认授权 -> 原报价转为历史保留，新报价生效
    owner_confirm(d, d["quotes"][1]["id"])
    d = detail(wid)
    assert d["quotes"][0]["status"] == "SUPERSEDED"  # 原报价保留为历史
    assert d["quotes"][1]["status"] == "CONFIRMED"
    assert d["quotes"][1]["payment_method"] == "SELF_PAY"
    assert d["quotes"][1]["insurance_amount"] == 0
    assert d["quotes"][1]["self_pay_amount"] == 2400

    # 继续施工并交车
    assert client.post(f"/api/workorders/{wid}/start-work").status_code == 200
    client.post(f"/api/workorders/{wid}/photos",
                files={"file": ("p.png", PNG, "image/png")}, data={"stage": "AFTER"})
    finish_installation(wid)
    r = client.post(f"/api/workorders/{wid}/deliver")
    assert r.status_code == 200, r.text


def test_late_receipt_does_not_overwrite_confirmed_plan():
    wo = create_wo()
    wid = wo["id"]
    prepare_installable(wo, claim_delay=0)  # 回执立即可取，但先不拉取

    # 回执到达前，车主变更方案：转为自费（第 2 版）并确认
    r = client.post(f"/api/workorders/{wid}/quotes", json={
        "reason": "OWNER_REQUEST", "glass_model": "FW-CAMRY-2020",
        "glass_price": 1800, "labor_fee": 500, "other_fee": 100,
        "payment_method": "SELF_PAY", "note": "车主决定不等保险，直接自费"})
    assert r.status_code == 200, r.text
    d = detail(wid)
    owner_confirm(d, d["quotes"][1]["id"])

    # 迟到的保险回执（批复 2000 元）现在才到达
    result = poll()
    assert any(x["outcome"] == "stale" for x in result["results"]), result

    d = detail(wid)
    claim = d["claims"][0]
    assert claim["status"] == "STALE"          # 回执被标记为迟到，未应用
    active = [q for q in d["quotes"] if q["status"] == "CONFIRMED"][0]
    assert active["revision"] == 2
    assert active["payment_method"] == "SELF_PAY"
    assert active["insurance_amount"] == 0     # 金额未被回执改动
    assert active["self_pay_amount"] == 2400
    assert any(e["type"] == "RECEIPT_STALE" for e in d["events"])

    # 自费方案下可正常施工交车
    client.post(f"/api/workorders/{wid}/inventory/confirm")
    assert client.post(f"/api/workorders/{wid}/start-work").status_code == 200
    client.post(f"/api/workorders/{wid}/photos",
                files={"file": ("p.png", PNG, "image/png")}, data={"stage": "AFTER"})
    finish_installation(wid)
    assert client.post(f"/api/workorders/{wid}/deliver").status_code == 200


def test_pause_requires_new_confirmed_plan_and_inventory():
    wo = create_wo()
    wid = wo["id"]
    prepare_installable(wo)
    poll()
    client.post(f"/api/workorders/{wid}/inventory/confirm")
    client.post(f"/api/workorders/{wid}/start-work")

    # 施工中发现型号不符 -> 暂停
    r = client.post(f"/api/workorders/{wid}/pause",
                    json={"reason": "MODEL_MISMATCH", "note": "实物与 FW-CAMRY-2020 不符"})
    assert r.status_code == 200, r.text

    # 未确认新方案前不能恢复
    r = client.post(f"/api/workorders/{wid}/resume")
    assert r.status_code == 400

    # 生成新方案（更换玻璃型号），车主确认
    r = client.post(f"/api/workorders/{wid}/quotes", json={
        "reason": "MODEL_MISMATCH", "glass_model": "FW-ACCORD-2019",
        "glass_price": 1900, "labor_fee": 500, "other_fee": 100,
        "payment_method": "SELF_PAY",
        "note": "型号不符，更换为 FW-ACCORD-2019，差价 100 元"})
    assert r.status_code == 200, r.text
    d = detail(wid)
    owner_confirm(d, d["quotes"][1]["id"])

    # 型号变更后原库存预留被释放，需重新确认库存才能恢复
    d = detail(wid)
    assert d["inventory"]["confirmed"] is False
    r = client.post(f"/api/workorders/{wid}/resume")
    assert r.status_code == 400 and "库存" in r.json()["detail"]
    client.post(f"/api/workorders/{wid}/inventory/confirm")
    r = client.post(f"/api/workorders/{wid}/resume")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "IN_PROGRESS"


def test_cannot_start_work_before_insurance_and_inventory_ready():
    wo = create_wo()
    wid = wo["id"]
    # 报价未确认 -> 不能开工
    r = client.post(f"/api/workorders/{wid}/start-work")
    assert r.status_code == 400
    owner_confirm(wo, wo["quotes"][0]["id"])
    # 库存未确认 -> 不能开工
    r = client.post(f"/api/workorders/{wid}/start-work")
    assert r.status_code == 400 and "库存" in r.json()["detail"]
    client.post(f"/api/workorders/{wid}/inventory/confirm")
    # 保险未批复 -> 不能开工
    r = client.post(f"/api/workorders/{wid}/start-work")
    assert r.status_code == 400 and "保险" in r.json()["detail"]
