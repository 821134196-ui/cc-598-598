"""FastAPI 主应用：业务 API + 挂载的模拟保险接口 + 静态前端 + 本地上传目录。"""
import os
import secrets
import uuid
from pathlib import Path

import httpx
from fastapi import (APIRouter, Depends, FastAPI, File, Form, HTTPException,
                     UploadFile)
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models, services
from .database import Base, SessionLocal, engine, get_db
from .mock_insurance import mock_app
from .schemas import (AcceptanceIn, ClaimSubmit, EstimatedPickupIn, FinishIn,
                      PauseIn, QuoteCreate, WorkOrderCreate)
from .seed import seed_all
from .services import (REASON_LABELS, add_event, confirmed_quote, iso,
                       latest_quote, naive_utc, utcnow)

ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(ROOT / "uploads"))
FRONTEND_DIR = ROOT / "frontend"
ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

Base.metadata.create_all(engine)
os.makedirs(UPLOAD_DIR, exist_ok=True)
seed_all(include_demo=os.environ.get("GLASS_SEED_DEMO", "1") == "1")

app = FastAPI(title="汽车玻璃保险直赔与安装验收系统")
router = APIRouter(prefix="/api")


def get_wo_or_404(db: Session, wid: int) -> models.WorkOrder:
    wo = db.get(models.WorkOrder, wid)
    if not wo:
        raise HTTPException(404, "工单不存在")
    return wo


def ensure_open(wo: models.WorkOrder):
    if wo.delivered_at:
        raise HTTPException(400, "工单已交付关闭，无法执行该操作")


async def mock_client() -> httpx.AsyncClient:
    """通过 ASGI 直连模拟保险公司接口（等价于外部 HTTP 服务，无需额外端口）。"""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=mock_app),
                             base_url="http://mock-insurance")


# ---------------- 工单 ----------------


@router.post("/workorders")
def create_work_order(data: WorkOrderCreate, db: Session = Depends(get_db)):
    if data.payment_method not in ("INSURANCE", "SELF_PAY"):
        raise HTTPException(400, "支付方式必须为 INSURANCE 或 SELF_PAY")
    total = round(data.glass_price + data.labor_fee + data.other_fee, 2)
    if total <= 0:
        raise HTTPException(400, "报价总额必须大于 0")
    if data.payment_method == "INSURANCE":
        if not (0 <= data.insurance_amount <= total):
            raise HTTPException(400, "保险承担金额必须在 0 与总价之间")
        insurance_amount = round(data.insurance_amount, 2)
    else:
        insurance_amount = 0.0
    self_pay = round(total - insurance_amount, 2)

    seq = db.query(models.WorkOrder).count() + 1
    wo = models.WorkOrder(
        order_no=f"WO{utcnow():%Y%m%d}-{seq:03d}",
        plate_number=data.plate_number.strip(),
        owner_name=data.owner_name.strip(),
        owner_phone=data.owner_phone.strip(),
        vehicle_model=data.vehicle_model.strip(),
        damage_desc=data.damage_desc.strip(),
        estimated_pickup_at=naive_utc(data.estimated_pickup_at),
        owner_token=secrets.token_hex(8),
    )
    db.add(wo)
    db.flush()
    quote = models.Quote(
        work_order_id=wo.id, revision=1, glass_model=data.glass_model.strip(),
        glass_price=data.glass_price, labor_fee=data.labor_fee, other_fee=data.other_fee,
        total=total, payment_method=data.payment_method,
        insurance_amount=insurance_amount, self_pay_amount=self_pay,
        reason="INITIAL", note=data.note.strip() or "初始报价",
    )
    db.add(quote)
    add_event(db, wo, "WO_CREATED",
              f"接车建单：{wo.plate_number} {wo.vehicle_model}，损伤：{wo.damage_desc or '未填写'}")
    add_event(db, wo, "QUOTE_CREATED",
              f"已生成第 1 版报价（初始报价）：总价 ¥{total:.2f}，"
              f"保险承担 ¥{insurance_amount:.2f}，车主自付 ¥{self_pay:.2f}，待车主确认")
    db.commit()
    return services.wo_detail(wo)


@router.get("/workorders")
def list_work_orders(db: Session = Depends(get_db)):
    rows = db.query(models.WorkOrder).order_by(models.WorkOrder.id.desc()).all()
    return {"items": [services.wo_brief(wo) for wo in rows]}


@router.get("/workorders/{wid}")
def work_order_detail(wid: int, db: Session = Depends(get_db)):
    return services.wo_detail(get_wo_or_404(db, wid))


@router.put("/workorders/{wid}/estimated-pickup")
def update_estimated_pickup(wid: int, data: EstimatedPickupIn, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    wo.estimated_pickup_at = naive_utc(data.estimated_pickup_at)
    add_event(db, wo, "PICKUP_UPDATED",
              f"预计提车时间更新为 {services.fmt_cn(wo.estimated_pickup_at)}")
    db.commit()
    return services.wo_detail(wo)


# ---------------- 报价 ----------------

@router.post("/workorders/{wid}/quotes")
def create_quote(wid: int, data: QuoteCreate, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    if data.reason not in REASON_LABELS or data.reason == "INITIAL":
        raise HTTPException(400, "无效的报价原因")
    if data.reason in ("DENIAL_CONVERT", "MODEL_MISMATCH", "NEW_DAMAGE") and not data.note.strip():
        raise HTTPException(400, "请填写方案说明（重新说明方案和费用）")
    if data.reason == "DENIAL_CONVERT":
        denied = any(c.status == "DENIED" for c in wo.claims)
        if not denied:
            raise HTTPException(400, "当前没有拒赔记录，不能使用“拒赔转自费”")
    if data.payment_method not in ("INSURANCE", "SELF_PAY"):
        raise HTTPException(400, "支付方式必须为 INSURANCE 或 SELF_PAY")

    total = round(data.glass_price + data.labor_fee + data.other_fee, 2)
    if total <= 0:
        raise HTTPException(400, "报价总额必须大于 0")
    if data.payment_method == "INSURANCE":
        if not (0 <= data.insurance_amount <= total):
            raise HTTPException(400, "保险承担金额必须在 0 与总价之间")
        insurance_amount = round(data.insurance_amount, 2)
    else:
        insurance_amount = 0.0
    self_pay = round(total - insurance_amount, 2)

    # 尚未确认的旧待确认报价作废（历史保留）
    for q in wo.quotes:
        if q.status == "PENDING_OWNER":
            q.status = "SUPERSEDED"
            add_event(db, wo, "QUOTE_SUPERSEDED", f"第 {q.revision} 版报价未确认即被新方案取代（历史保留）")

    revision = (wo.quotes[-1].revision if wo.quotes else 0) + 1
    quote = models.Quote(
        work_order_id=wo.id, revision=revision, glass_model=data.glass_model.strip(),
        glass_price=data.glass_price, labor_fee=data.labor_fee, other_fee=data.other_fee,
        total=total, payment_method=data.payment_method,
        insurance_amount=insurance_amount, self_pay_amount=self_pay,
        reason=data.reason, note=data.note.strip(),
    )
    db.add(quote)
    add_event(db, wo, "QUOTE_CREATED",
              f"已生成第 {revision} 版报价（{REASON_LABELS[data.reason]}）：{quote.note}。"
              f"总价 ¥{total:.2f}，保险承担 ¥{insurance_amount:.2f}，车主自付 ¥{self_pay:.2f}，"
              f"待车主确认授权")
    db.commit()
    return services.wo_detail(wo)


# ---------------- 保险理赔 ----------------

@router.post("/workorders/{wid}/claims")
async def submit_claim(wid: int, data: ClaimSubmit, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    cq = confirmed_quote(wo)
    if not cq:
        raise HTTPException(400, "需先由车主确认报价，才能提交保险理赔")
    if cq.payment_method != "INSURANCE":
        raise HTTPException(400, "当前方案为车主自费，无需提交理赔")
    for c in wo.claims:
        if c.quote_revision == cq.revision and c.status == "SUBMITTED":
            raise HTTPException(400, "理赔已提交，正在等待保险回执")
        if c.quote_revision == cq.revision and c.status == "APPROVED":
            raise HTTPException(400, "该方案已获保险批复，请勿重复提交")

    attempt = sum(1 for c in wo.claims if c.quote_revision == cq.revision) + 1
    claim_number = f"CL-{wo.order_no}-R{cq.revision}-{attempt}"
    claim = models.InsuranceClaim(
        work_order_id=wo.id, claim_number=claim_number,
        quote_revision=cq.revision, amount=cq.insurance_amount,
    )
    db.add(claim)
    add_event(db, wo, "CLAIM_SUBMITTED",
              f"已向保险公司提交理赔 {claim_number}（对应第 {cq.revision} 版方案，"
              f"申请赔付 ¥{cq.insurance_amount:.2f}）")
    db.commit()

    # 调用模拟保险公司接口受理案件
    async with await mock_client() as client:
        resp = await client.post("/claims", json={
            "claim_number": claim_number,
            "plate_number": wo.plate_number,
            "amount": cq.insurance_amount,
            "delay_seconds": data.delay_seconds,
            "force_decision": data.force_decision,
        })
        resp.raise_for_status()
    return services.wo_detail(wo)


@router.post("/insurance/poll")
async def poll_receipts(db: Session = Depends(get_db)):
    """从模拟保险接口拉取新回执并逐条应用（迟到回执不会覆盖已确认方案）。"""
    last = services.get_setting(db, "last_receipt_id", 0)
    async with await mock_client() as client:
        resp = await client.get("/receipts", params={"after_id": last})
        resp.raise_for_status()
        receipts = resp.json()["receipts"]
    results = []
    max_id = last
    for r in receipts:
        applied = services.apply_receipt(db, r)
        results.append({"claim_number": r["claim_number"], "outcome": applied["outcome"]})
        max_id = max(max_id, r["receipt_id"])
    services.set_setting(db, "last_receipt_id", max_id)
    db.commit()
    return {"fetched": len(receipts), "results": results}


# ---------------- 库存 ----------------

@router.get("/inventory")
def list_inventory(db: Session = Depends(get_db)):
    rows = db.query(models.InventoryItem).order_by(models.InventoryItem.glass_model).all()
    return {"items": [{
        "glass_model": i.glass_model, "name": i.name,
        "total": i.total, "reserved": i.reserved,
        "available": i.total - i.reserved,
    } for i in rows]}


@router.post("/workorders/{wid}/inventory/confirm")
def confirm_inventory(wid: int, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    lq = latest_quote(wo)
    if not lq:
        raise HTTPException(400, "尚无报价，无法确认库存")
    model = lq.glass_model
    if wo.inventory_confirmed and wo.reserved_glass_model == model:
        return services.wo_detail(wo)  # 幂等
    if wo.inventory_confirmed:
        old = db.query(models.InventoryItem).filter_by(glass_model=wo.reserved_glass_model).first()
        if old and old.reserved > 0:
            old.reserved -= 1
        wo.inventory_confirmed = False
        wo.reserved_glass_model = None
    item = db.query(models.InventoryItem).filter_by(glass_model=model).first()
    if not item:
        raise HTTPException(400, f"库存中不存在玻璃型号 {model}")
    if item.total - item.reserved < 1:
        raise HTTPException(400, f"型号 {model} 库存不足（可用 {item.total - item.reserved} 件）")
    item.reserved += 1
    wo.inventory_confirmed = True
    wo.reserved_glass_model = model
    add_event(db, wo, "INVENTORY_CONFIRMED",
              f"库存已确认：{model} 预留 1 件（剩余可用 {item.total - item.reserved} 件）")
    db.commit()
    return services.wo_detail(wo)


# ---------------- 施工 ----------------

@router.post("/workorders/{wid}/start-work")
def start_work(wid: int, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    if wo.installation and wo.installation.started_at:
        raise HTTPException(400, "施工已开始")
    cq = confirmed_quote(wo)
    if not cq:
        raise HTTPException(400, "报价尚未获车主确认，不能安排施工")
    if not (wo.inventory_confirmed and wo.reserved_glass_model == cq.glass_model):
        raise HTTPException(400, f"库存未确认（需按当前报价的玻璃型号 {cq.glass_model} 确认库存）")
    if cq.payment_method == "INSURANCE":
        approved = any(c.quote_revision == cq.revision and c.status == "APPROVED"
                       for c in wo.claims)
        if not approved:
            raise HTTPException(400, "保险方案尚未批复，不能安排施工")
    inst = wo.installation or models.Installation(work_order_id=wo.id)
    inst.started_at = utcnow()
    db.add(inst)
    add_event(db, wo, "WORK_STARTED", f"开始施工：安装玻璃型号 {cq.glass_model}")
    db.commit()
    return services.wo_detail(wo)


@router.post("/workorders/{wid}/pause")
def pause_work(wid: int, data: PauseIn, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    if not (wo.installation and wo.installation.started_at):
        raise HTTPException(400, "施工尚未开始，无法暂停")
    if wo.is_paused:
        raise HTTPException(400, "施工已处于暂停状态")
    if data.reason not in services.PAUSE_LABELS:
        raise HTTPException(400, "无效的暂停原因")
    wo.is_paused = True
    wo.paused_at = utcnow()
    wo.pause_reason = data.reason
    wo.pause_note = data.note.strip()
    add_event(db, wo, "WORK_PAUSED",
              f"施工暂停（{services.PAUSE_LABELS[data.reason]}）：{wo.pause_note or '未填写说明'}。"
              f"需重新说明方案和费用，生成新报价并经车主确认后才能恢复施工")
    db.commit()
    return services.wo_detail(wo)


@router.post("/workorders/{wid}/resume")
def resume_work(wid: int, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    if not wo.is_paused:
        raise HTTPException(400, "施工未处于暂停状态")
    cq = confirmed_quote(wo)
    if not cq or not cq.confirmed_at or cq.confirmed_at < wo.paused_at:
        raise HTTPException(400, "暂停后尚未生成并确认新的方案与费用，不能恢复施工")
    if not (wo.inventory_confirmed and wo.reserved_glass_model == cq.glass_model):
        raise HTTPException(400, f"玻璃型号已变更，需重新确认库存（{cq.glass_model}）")
    wo.is_paused = False
    add_event(db, wo, "WORK_RESUMED",
              f"恢复施工：按第 {cq.revision} 版方案（{REASON_LABELS.get(cq.reason, cq.reason)}）继续")
    db.commit()
    return services.wo_detail(wo)


@router.post("/workorders/{wid}/photos")
async def upload_photo(wid: int, file: UploadFile = File(...),
                       stage: str = Form("DURING"), note: str = Form(""),
                       db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    if not (wo.installation and wo.installation.started_at):
        raise HTTPException(400, "开始施工后才能上传安装照片")
    if stage not in services.PHOTO_STAGE_LABELS:
        raise HTTPException(400, "无效的照片阶段")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_IMG_EXT:
        raise HTTPException(400, f"仅支持图片文件（{', '.join(sorted(ALLOWED_IMG_EXT))}）")
    filename = f"wo{wid}_{uuid.uuid4().hex[:10]}{ext}"
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "图片大小不能超过 10MB")
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        f.write(content)
    photo = models.Photo(work_order_id=wo.id, filename=filename, stage=stage, note=note.strip())
    db.add(photo)
    add_event(db, wo, "PHOTO_UPLOADED",
              f"上传安装照片（{services.PHOTO_STAGE_LABELS[stage]}）")
    db.commit()
    return services.wo_detail(wo)


@router.post("/workorders/{wid}/installation/finish")
def finish_installation(wid: int, data: FinishIn, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    inst = wo.installation
    if not (inst and inst.started_at):
        raise HTTPException(400, "施工尚未开始")
    if wo.is_paused:
        raise HTTPException(400, "施工暂停中，请先恢复施工")
    inst.finished_at = utcnow()
    inst.glue_type = data.glue_type.strip()
    inst.curing_deadline = naive_utc(data.curing_deadline)
    # 重新登记安装完成视为返工，验收结果重置
    inst.acceptance_result = "PENDING"
    inst.acceptance_note = ""
    inst.accepted_at = None
    add_event(db, wo, "CURING_SET",
              f"安装完成，使用{inst.glue_type}，固化截止 {services.fmt_cn(inst.curing_deadline)}。"
              f"固化时间未到不得交车")
    db.commit()
    return services.wo_detail(wo)


@router.post("/workorders/{wid}/installation/acceptance")
def record_acceptance(wid: int, data: AcceptanceIn, db: Session = Depends(get_db)):
    wo = get_wo_or_404(db, wid)
    ensure_open(wo)
    inst = wo.installation
    if not (inst and inst.finished_at):
        raise HTTPException(400, "请先登记安装完成与固化信息")
    if data.result not in ("PASSED", "FAILED"):
        raise HTTPException(400, "验收结果必须为 PASSED 或 FAILED")
    inst.acceptance_result = data.result
    inst.acceptance_note = data.note.strip()
    inst.accepted_at = utcnow()
    label = "通过" if data.result == "PASSED" else "未通过"
    add_event(db, wo, "ACCEPTANCE",
              f"安装验收{label}：{inst.acceptance_note or '无备注'}"
              + ("" if data.result == "PASSED" else "。验收未通过不得交车"))
    db.commit()
    return services.wo_detail(wo)


# ---------------- 交车 ----------------

@router.get("/workorders/{wid}/delivery-check")
def get_delivery_check(wid: int, db: Session = Depends(get_db)):
    return services.delivery_check(get_wo_or_404(db, wid))


@router.post("/workorders/{wid}/deliver")
def deliver(wid: int, db: Session = Depends(get_db)):
    """交车。服务端强制复核全部交付条件，前端禁用按钮不构成校验。"""
    wo = get_wo_or_404(db, wid)
    if wo.delivered_at:
        raise HTTPException(400, "工单已交付，请勿重复操作")
    check = services.delivery_check(wo)
    if not check["deliverable"]:
        failed = [c["label"] for c in check["checks"] if not c["passed"]]
        raise HTTPException(400, "当前不允许交付：" + "；".join(failed))
    wo.delivered_at = utcnow()
    add_event(db, wo, "DELIVERED", "车辆已交付车主，工单关闭")
    db.commit()
    return services.wo_detail(wo)


# ---------------- 车主端 ----------------

@router.get("/owner/{token}")
def owner_view(token: str, db: Session = Depends(get_db)):
    wo = db.query(models.WorkOrder).filter_by(owner_token=token).first()
    if not wo:
        raise HTTPException(404, "工单不存在或链接无效")
    return services.owner_dict(wo)


@router.post("/owner/{token}/quotes/{qid}/confirm")
def owner_confirm_quote(token: str, qid: int, db: Session = Depends(get_db)):
    """车主确认报价（授权）。拒赔改价、方案变更后必须经此重新授权。"""
    wo = db.query(models.WorkOrder).filter_by(owner_token=token).first()
    if not wo:
        raise HTTPException(404, "工单不存在或链接无效")
    quote = db.get(models.Quote, qid)
    if not quote or quote.work_order_id != wo.id:
        raise HTTPException(404, "报价不存在")
    services.confirm_quote(db, quote, by="车主")
    return services.owner_dict(wo)


# ---------------- 应用组装 ----------------

app.include_router(router)
app.mount("/mock-insurance", mock_app)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
