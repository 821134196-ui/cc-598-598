"""端到端业务规则验证（不依赖第三方库，直接打 HTTP 接口）。"""
import base64
import io
import json
import sys
import time
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
PASS, FAIL = 0, 0
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def call(method, path, body=None, expect=None, raw=False):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            payload = json.loads(r.read())
            code = r.status
    except urllib.error.HTTPError as e:
        payload = json.loads(e.read())
        code = e.code
    if expect is not None:
        check(code == expect, f"{method} {path} -> {code}（期望 {expect}）{payload.get('detail','')}")
        if code == expect:
            return payload
    if code >= 400:
        raise AssertionError(f"{method} {path} -> {code}: {payload}")
    return payload


def upload_photo(path):
    boundary = "----e2e"
    part = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.png\"\r\n"
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + PNG_1X1 + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path, data=part,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {msg}")
    else:
        FAIL += 1
        print(f"  ✗ {msg}")


def new_order(phone, claim):
    return call("POST", "/api/orders", {
        "customer_name": "测试车主", "customer_phone": phone, "plate_no": f"测{phone[-4:]}",
        "car_model": "测试车型", "glass_position": "前挡风玻璃",
        "insurance_company": "测试保险", "claim_no": claim,
    })["id"]


def first_quote(oid, **over):
    body = {"glass_model": "GLASS-STD-001", "glass_spec": "夹层前挡",
            "price_glass": 1800, "price_labor": 300, "price_sealant": 100,
            "price_other": 0, "insurance_cover": 0}
    body.update(over)
    return call("POST", f"/api/orders/{oid}/quotes", body)


def receipt(claim, decision, cover=0.0, ago=0, reason=""):
    return call("POST", "/api/sim/insurance/receipt", {
        "claim_no": claim, "decision": decision, "cover_amount": cover,
        "reason": reason, "issued_minutes_ago": ago,
    })


print("== 1. 安排施工守卫：库存/报价确认/保险通过 缺一不可 ==")
oid = new_order("13900000001", "CLM-T1")
first_quote(oid)
call("POST", f"/api/orders/{oid}/schedule", {"worker": ""}, expect=409)   # 库存未确认+保险待回执
call("POST", f"/api/orders/{oid}/stock")
call("POST", f"/api/orders/{oid}/schedule", {"worker": ""}, expect=409)   # 保险仍待回执
receipt("CLM-T1", "approved", cover=2000)
call("POST", f"/api/orders/{oid}/schedule", {"worker": ""}, expect=409)   # 车主还未确认报价
o = call("POST", f"/api/orders/{oid}/quotes/1/confirm",
         {"customer_authorization": "本人同意报价与自付金额"})
check(o["status"] == "ready", "回执赔付金额回填 + 车主确认后工单进入待施工")
q1 = o["quotes"][0]
check(q1["insurance_cover"] == 2000 and q1["self_pay"] == 200, "保险承担 2000，车主自付 200")
o = call("POST", f"/api/orders/{oid}/schedule", {"worker": ""})
check(o["status"] == "scheduled", "三条件齐备后允许安排施工")

print("== 2. 施工暂停：型号不符/新破损须新报价+重新授权才能复工 ==")
o = call("POST", f"/api/orders/{oid}/install/start")
check(o["status"] == "installing", "开始施工")
o = call("POST", f"/api/orders/{oid}/install/pause", {"reason": "实车为带雨感版本，型号不符"})
check(o["status"] == "paused", "发现型号不符，工单暂停")
call("POST", f"/api/orders/{oid}/install/resume", expect=409)               # 未出新方案
o = call("POST", f"/api/orders/{oid}/quotes", {
    "glass_model": "GLASS-RAIN-002", "price_glass": 2300, "price_labor": 300,
    "price_sealant": 100, "price_other": 0, "insurance_cover": 0,
    "change_reason": "更换为雨感兼容型号并补边框处理"})
check(len(o["quotes"]) == 2 and o["quotes"][0]["status"] == "superseded",
      "变更报价生成 v2，原 v1 报价保留并标记 superseded")
call("POST", f"/api/orders/{oid}/install/resume", expect=409)               # 新报价未授权
o = call("POST", f"/api/orders/{oid}/quotes/2/confirm",
         {"customer_authorization": "本人已知悉型号变更与新费用，确认授权"})
check(o["quotes"][-1]["customer_authorization"].startswith("本人已知悉"),
      "车主对变更方案重新授权留痕")
o = call("POST", f"/api/orders/{oid}/install/resume")
check(o["status"] == "installing", "新方案授权后复工")

print("== 3. 照片 / 固化 / 验收 / 交车门禁 ==")
call("POST", f"/api/orders/{oid}/install/finish", expect=409)               # 无照片不能完成安装
o = upload_photo(f"/api/orders/{oid}/photos")
check(len(o["photos"]) == 1, "安装照片已上传本地并关联工单")
call("POST", f"/api/orders/{oid}/cure", {"cure_minutes": 60})
o = call("POST", f"/api/orders/{oid}/install/finish")
check(o["status"] == "installed" and o["cure_deadline"], "完成安装，已登记固化截止时间")
# 验收未过
o = call("POST", f"/api/orders/{oid}/inspect", {"passed": False, "note": "上部密封条间隙偏大"})
g = o["delivery_gate"]
check(not g["allow"] and not g["inspection_passed"] and not g["cured"],
      "验收不合格且未固化 → 门禁不放行")
call("POST", f"/api/orders/{oid}/deliver", {"operator": "店员A"}, expect=409)  # 强拦截
# 复检通过，但固化仍未到
o = call("POST", f"/api/orders/{oid}/inspect", {"passed": True, "note": "复检合格"})
check(o["delivery_gate"]["inspection_passed"] and not o["delivery_gate"]["cured"]
      and not o["delivery_gate"]["allow"], "复检通过但胶未固化，仍禁止交车")
call("POST", f"/api/orders/{oid}/deliver", {"operator": "店员A"}, expect=409)

print("== 4. 拒赔 → 转自费（重新授权，原报价保留）==")
oid2 = new_order("13900000002", "CLM-T2")
first_quote(oid2)
receipt("CLM-T2", "rejected", reason="玻璃险不在承保范围")
call("POST", f"/api/orders/{oid2}/stock")
call("POST", f"/api/orders/{oid2}/schedule", {"worker": ""}, expect=409)   # 拒赔不能按保险方案施工
o = call("POST", f"/api/orders/{oid2}/convert-self-pay", {
    "glass_model": "GLASS-STD-001", "price_glass": 1800, "price_labor": 300,
    "price_sealant": 100, "price_other": 0})
check([q["version"] for q in o["quotes"]] == [1, 2], "新自费报价为 v2，原 v1 继续保留")
check(o["quotes"][0]["status"] == "superseded" and o["quotes"][1]["kind"] == "self_pay"
      and o["quotes"][1]["status"] == "pending_customer", "v2 为待车主重新授权的自费报价")
call("POST", f"/api/orders/{oid2}/quotes/1/confirm",
     {"customer_authorization": "试图确认旧报价"}, expect=409)             # 旧版本不可再确认
# 授权语过短被拒
call("POST", f"/api/orders/{oid2}/quotes/2/confirm", {"customer_authorization": "ok"}, expect=422)
o = call("POST", f"/api/orders/{oid2}/quotes/2/confirm",
         {"customer_authorization": "本人知悉拒赔，确认全额自费 ¥2200 并授权安装"})
check(o["quotes"][1]["self_pay"] == 2200 and o["quotes"][1]["insurance_cover"] == 0,
      "自费方案保险承担 0，自付 2200")
o = call("POST", f"/api/orders/{oid2}/schedule", {"worker": ""})
check(o["status"] == "scheduled", "重新授权后可以安排施工")

print("== 5. 迟到理赔回执不得覆盖已确认方案 ==")
# 车主已确认自费在前；回执签发时间被模拟为更早、现在才到店（迟到）
o = receipt("CLM-T2", "approved", cover=2200, ago=60, reason="迟到的同意赔付")
last_r = o["receipts"][-1]
check(last_r["decision"] == "approved" and not last_r["applied"],
      "迟到回执仅留痕，applied=false")
check("不得覆盖" in last_r["ignore_reason"], "已记录不覆盖原因：" + last_r["ignore_reason"])
cur = [q for q in o["quotes"] if q["status"] == "confirmed"][-1]
check(cur["kind"] == "self_pay" and cur["insurance_cover"] == 0
      and o["insurance_decision"] == "rejected",
      "工单仍执行车主已确认的自费方案，理赔金额、工单状态均未被改写")

print("== 6. 固化到期后放行交车 ==")
oid3 = new_order("13900000003", "CLM-T3")
first_quote(oid3, insurance_cover=2200)
receipt("CLM-T3", "approved", cover=2200)
call("POST", f"/api/orders/{oid3}/stock")
call("POST", f"/api/orders/{oid3}/quotes/1/confirm", {"customer_authorization": "本人同意报价"})
call("POST", f"/api/orders/{oid3}/schedule", {"worker": ""})
call("POST", f"/api/orders/{oid3}/install/start")
upload_photo(f"/api/orders/{oid3}/photos")
call("POST", f"/api/orders/{oid3}/cure", {"cure_minutes": 1})
call("POST", f"/api/orders/{oid3}/install/finish")
call("POST", f"/api/orders/{oid3}/inspect", {"passed": True, "note": "合格"})
g = call("GET", f"/api/orders/{oid3}/delivery-gate")
check(not g["allow"] and g["minutes_until_cured"], "固化剩余 1 分钟，交车仍被拦截")
print("  … 等待 65 秒固化到期 …")
time.sleep(65)
o = call("POST", f"/api/orders/{oid3}/deliver", {"operator": "店员B"})
check(o["status"] == "delivered" and o["delivered_by"] == "店员B", "固化到期+验收通过 → 交车成功")
call("POST", f"/api/orders/{oid3}/deliver", {"operator": "x"}, expect=409)

print(f"\n结果：通过 {PASS} 项，失败 {FAIL} 项")
sys.exit(1 if FAIL else 0)
