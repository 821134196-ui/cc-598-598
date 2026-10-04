"""汽车玻璃保险直赔与安装验收系统 —— 核心业务规则（服务端强制）"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models

# ---------------------------------------------------------------- 状态查询

def active_quote(order: models.WorkOrder) -> Optional[models.Quote]:
    """当前有效报价：最近一份已车主确认的报价。"""
    confirmed = [q for q in order.quotes if q.status == models.QS_CONFIRMED]
    return confirmed[-1] if confirmed else None


def latest_quote(order: models.WorkOrder) -> Optional[models.Quote]:
    return order.quotes[-1] if order.quotes else None


def delivery_gate(order: models.WorkOrder, now: Optional[datetime] = None) -> dict:
    """交车前硬性条件：固化到期 + 验收通过 + 有安装照片 + 报价有效且已授权。"""
    now = now or datetime.utcnow()
    install = order.install
    reasons = []

    cure_deadline = install.cure_deadline if install else None
    cured = bool(cure_deadline and now >= cure_deadline)
    minutes_left = None
    if cure_deadline and not cured:
        minutes_left = max(1, int((cure_deadline - now).total_seconds() // 60 + 1))
        reasons.append(f"胶尚未固化，预计还需 {minutes_left} 分钟（截止 {cure_deadline:%Y-%m-%d %H:%M}）")
    elif not cure_deadline:
        reasons.append("尚未登记胶的固化截止时间")

    inspection_passed = bool(install and install.inspection_result == "pass")
    if not inspection_passed:
        if install and install.inspection_result == "fail":
            reasons.append(f"安装验收未通过：{install.inspection_note or '需整改后复检'}")
        else:
            reasons.append("安装验收尚未完成")

    photos_ok = len(order.photos) >= 1
    if not photos_ok:
        reasons.append("缺少施工安装照片")

    q = active_quote(order)
    confirmed_quote_ok = q is not None
    if q is None:
        reasons.append("没有车主已确认的报价方案")
    elif q.kind == models.QK_INSURANCE and order.insurance_decision == models.IN_REJECTED:
        confirmed_quote_ok = False
        reasons.append("保险已拒赔，原保险方案失效，须转自费并由车主重新确认")

    allow = cured and inspection_passed and photos_ok and confirmed_quote_ok
    return {
        "allow": allow,
        "cured": cured,
        "minutes_until_cured": minutes_left,
        "inspection_passed": inspection_passed,
        "photos_ok": photos_ok,
        "confirmed_quote_ok": confirmed_quote_ok,
        "reasons": reasons,
    }


# ---------------------------------------------------------------- 报价

def _total(payload) -> float:
    return round(
        payload.price_glass
        + payload.price_labor
        + payload.price_sealant
        + payload.price_other,
        2,
    )


def _supersede_others(db: Session, order: models.WorkOrder, keep: models.Quote):
    for q in order.quotes:
        if q.id != keep.id and q.status in (models.QS_DRAFT, models.QS_PENDING, models.QS_CONFIRMED):
            q.status = models.QS_SUPERSEDED


def create_quote(db: Session, order: models.WorkOrder, payload, kind: Optional[str] = None,
                 insurance_cover: Optional[float] = None, reason: str = "") -> models.Quote:
    """新建报价版本。无历史报价=初次保险报价；暂停中=施工变更报价。历史版本一律保留。"""
    if order.status == models.ST_DELIVERED:
        raise HTTPException(409, "工单已交车，不能再修改报价")

    if not order.quotes:
        kind = models.QK_INSURANCE
        status = models.QS_PENDING
    elif order.status != models.ST_PAUSED:
        raise HTTPException(409, "只有施工暂停（型号不符/新破损）后才能出具变更报价")
    else:
        kind = models.QK_REWORK
        status = models.QS_PENDING

    version = (max((q.version for q in order.quotes), default=0)) + 1
    total = _total(payload)
    cover = insurance_cover if insurance_cover is not None else payload.insurance_cover
    quote = models.Quote(
        order_id=order.id,
        version=version,
        kind=kind,
        status=status,
        glass_model=payload.glass_model,
        glass_spec=payload.glass_spec,
        price_glass=payload.price_glass,
        price_labor=payload.price_labor,
        price_sealant=payload.price_sealant,
        price_other=payload.price_other,
        total_amount=total,
        insurance_cover=round(cover, 2),
        change_reason=reason or payload.change_reason or "初次报价",
    )
    db.add(quote)
    db.flush()
    # 变更报价出具后，原确认方案立即失效（记录保留为 superseded），复工必须等新版授权
    _supersede_others(db, order, quote)
    return quote


def convert_self_pay(db: Session, order: models.WorkOrder, payload) -> models.Quote:
    """保险拒赔 → 转自费：生成新报价（保险承担 0），原报价保留为 superseded，待车主重新授权。"""
    if order.insurance_decision != models.IN_REJECTED:
        raise HTTPException(409, "只有保险拒赔后才能转为自费")
    if order.status == models.ST_DELIVERED:
        raise HTTPException(409, "工单已交车")

    version = (max((q.version for q in order.quotes), default=0)) + 1
    quote = models.Quote(
        order_id=order.id,
        version=version,
        kind=models.QK_SELF_PAY,
        status=models.QS_PENDING,
        glass_model=payload.glass_model,
        glass_spec=payload.glass_spec,
        price_glass=payload.price_glass,
        price_labor=payload.price_labor,
        price_sealant=payload.price_sealant,
        price_other=payload.price_other,
        total_amount=_total(payload),
        insurance_cover=0.0,
        change_reason=payload.change_reason or "保险拒赔，转自费报价",
    )
    db.add(quote)
    db.flush()
    _supersede_others(db, order, quote)
    return quote


def confirm_quote(db: Session, order: models.WorkOrder, version: int, authorization: str) -> models.Quote:
    """车主确认报价。拒赔改价/施工变更必须重新授权——任何确认都记录授权语句。"""
    quote = next((q for q in order.quotes if q.version == version), None)
    if quote is None:
        raise HTTPException(404, "报价版本不存在")
    if quote.status == models.QS_SUPERSEDED:
        raise HTTPException(409, "该报价版本已被取代，不能确认")
    if quote.status == models.QS_CONFIRMED:
        raise HTTPException(409, "该版本已确认，无需重复确认")
    if not authorization or len(authorization.strip()) < 4:
        raise HTTPException(422, "必须填写完整的车主授权确认语（不少于 4 个字）")

    quote.status = models.QS_CONFIRMED
    quote.confirmed_at = datetime.utcnow()
    quote.customer_authorization = authorization.strip()
    _supersede_others(db, order, quote)
    db.flush()
    return quote


# ---------------------------------------------------------------- 保险回执（模拟）

def ingest_receipt(db: Session, order: models.WorkOrder, decision: str, cover_amount: float,
                   reason: str, issued_at: datetime, received_at: Optional[datetime] = None,
                   ) -> models.InsuranceReceipt:
    """
    回执落库并按规则决定是否应用。
    关键规则：车主方案确认时间晚于回执签发时间 → 回执迟到，只能留痕，不得覆盖已确认方案。
    """
    received_at = received_at or datetime.utcnow()
    receipt = models.InsuranceReceipt(
        order_id=order.id,
        decision=decision,
        cover_amount=round(cover_amount, 2),
        reason=reason,
        issued_at=issued_at,
        received_at=received_at,
    )

    q = active_quote(order)
    stale = q is not None and q.confirmed_at is not None and q.confirmed_at > issued_at
    non_insurance_plan = q is not None and q.kind in (models.QK_SELF_PAY, models.QK_REWORK)

    if stale and non_insurance_plan:
        # 车主已带着方案离开保险路径（拒赔转自费 / 施工变更），迟到回执一律不得改单
        receipt.applied = False
        receipt.ignore_reason = (
            f"迟到回执：车主已于 {q.confirmed_at:%Y-%m-%d %H:%M} 确认"
            f"第 {q.version} 版方案，该回执（签发 {issued_at:%Y-%m-%d %H:%M}）不得覆盖"
        )
    elif non_insurance_plan and decision == "approved":
        receipt.applied = False
        receipt.ignore_reason = f"当前执行第 {q.version} 版自费/变更方案，保险赔付不再自动改单"
    else:
        # 回执作用于工单理赔状态；不直接删除/改写已确认报价，
        # 与已确认保险方案冲突（拒赔）时由转自费+重新授权流程处理。
        receipt.applied = True
        order.insurance_decision = decision
        target = q
        if target is None:
            # 回执早于车主确认到达：作用于最新一份待确认的保险报价
            target = next(
                (x for x in reversed(order.quotes)
                 if x.kind == models.QK_INSURANCE and x.status == models.QS_PENDING),
                None,
            )
        if stale:
            receipt.ignore_reason = (
                f"迟到回执（签发 {issued_at:%Y-%m-%d %H:%M}，车主已于 "
                f"{q.confirmed_at:%Y-%m-%d %H:%M} 确认方案）：仅更新理赔状态，"
                + ("原保险报价保留，须改走自费并由车主重新授权" if decision == models.IN_REJECTED
                   else "已确认报价不被改写")
            )
        if decision == models.IN_APPROVED and target and target.kind == models.QK_INSURANCE:
            target.insurance_cover = round(cover_amount, 2)
        if decision == models.IN_REJECTED and target and target.kind == models.QK_INSURANCE:
            target.insurance_cover = 0.0

    db.add(receipt)
    db.flush()
    return receipt


# ---------------------------------------------------------------- 工单流转

def confirm_stock(db: Session, order: models.WorkOrder) -> models.WorkOrder:
    if order.status not in (models.ST_CREATED, models.ST_READY):
        raise HTTPException(409, f"当前状态 {order.status} 不能确认库存")
    order.stock_confirmed = True
    order.stock_confirmed_at = datetime.utcnow()
    _maybe_ready(order)
    db.flush()
    return order


def _maybe_ready(order: models.WorkOrder):
    q = active_quote(order)
    plan_ok = q is not None and not (
        q.kind == models.QK_INSURANCE and order.insurance_decision == models.IN_REJECTED
    )
    insurance_ok = (
        q is not None
        and (q.kind != models.QK_INSURANCE or order.insurance_decision == models.IN_APPROVED)
    )
    if order.stock_confirmed and plan_ok and insurance_ok and order.status == models.ST_CREATED:
        order.status = models.ST_READY


def schedule_install(db: Session, order: models.WorkOrder) -> models.WorkOrder:
    """门店确认库存和保险方案后才能安排施工。"""
    if order.status not in (models.ST_READY, models.ST_SCHEDULED):
        raise HTTPException(409, f"当前状态 {order.status} 不能安排施工")
    q = active_quote(order)
    if not order.stock_confirmed:
        raise HTTPException(409, "门店尚未确认库存")
    if q is None:
        raise HTTPException(409, "报价尚未经车主确认")
    if q.kind == models.QK_INSURANCE and order.insurance_decision != models.IN_APPROVED:
        raise HTTPException(
            409,
            "保险方案尚未确认通过"
            + ("（保险已拒赔，须转自费重新报价）" if order.insurance_decision == models.IN_REJECTED
               else "（仍在等待保险回执）"),
        )
    order.status = models.ST_SCHEDULED
    if order.install is None:
        db.add(models.InstallRecord(order_id=order.id))
    db.flush()
    return order


def start_install(db: Session, order: models.WorkOrder) -> models.WorkOrder:
    if order.status not in (models.ST_SCHEDULED, models.ST_PAUSED):
        raise HTTPException(409, f"当前状态 {order.status} 不能开始/继续施工")
    inst = order.install
    if inst is None:
        inst = models.InstallRecord(order_id=order.id)
        db.add(inst)
    if order.status == models.ST_SCHEDULED:
        inst.started_at = datetime.utcnow()
    if order.status == models.ST_PAUSED:
        inst.resumed_at = datetime.utcnow()
        inst.pause_reason = ""
    order.status = models.ST_INSTALLING
    db.flush()
    return order


def pause_install(db: Session, order: models.WorkOrder, reason: str) -> models.WorkOrder:
    """施工中发现型号不符或新的破损 → 暂停，重新说明方案和费用。"""
    if order.status != models.ST_INSTALLING:
        raise HTTPException(409, "只有施工中的工单可以暂停")
    order.status = models.ST_PAUSED
    order.install.paused_at = datetime.utcnow()
    order.install.pause_reason = reason
    db.flush()
    return order


def resume_install(db: Session, order: models.WorkOrder) -> models.WorkOrder:
    """暂停后必须出具并由车主确认新的变更报价，才能复工。"""
    if order.status != models.ST_PAUSED:
        raise HTTPException(409, "只有暂停中的工单可以复工")
    q = active_quote(order)
    if q is None or not (q.kind == models.QK_REWORK and q.confirmed_at
                         and order.install.paused_at and q.confirmed_at > order.install.paused_at):
        raise HTTPException(409, "须先出具变更报价并取得车主重新授权，才能复工")
    order.status = models.ST_INSTALLING
    order.install.resumed_at = datetime.utcnow()
    order.install.pause_reason = ""
    db.flush()
    return order


def finish_install(db: Session, order: models.WorkOrder) -> models.WorkOrder:
    if order.status != models.ST_INSTALLING:
        raise HTTPException(409, "只有施工中的工单可以完成安装")
    if not order.photos:
        raise HTTPException(409, "请先上传安装照片再完成安装")
    order.status = models.ST_INSTALLED
    order.install.finished_at = datetime.utcnow()
    db.flush()
    return order


def register_cure(db: Session, order: models.WorkOrder, minutes: int) -> models.WorkOrder:
    if order.status not in (models.ST_INSTALLING, models.ST_INSTALLED):
        raise HTTPException(409, "施工开始后才能登记固化时间")
    now = datetime.utcnow()
    order.install.cure_registered_at = now
    order.install.cure_deadline = now + timedelta(minutes=minutes)
    db.flush()
    return order


def inspect(db: Session, order: models.WorkOrder, passed: bool, note: str) -> models.WorkOrder:
    if order.status != models.ST_INSTALLED:
        raise HTTPException(409, "安装完成后才能验收")
    order.install.inspection_result = "pass" if passed else "fail"
    order.install.inspected_at = datetime.utcnow()
    order.install.inspection_note = note
    db.flush()
    return order


def deliver(db: Session, order: models.WorkOrder, operator: str,
            now: Optional[datetime] = None) -> models.WorkOrder:
    """固化时间未到或验收未通过（或缺照片/授权），一律禁止交车。"""
    if order.status == models.ST_DELIVERED:
        raise HTTPException(409, "工单已交车，不能重复交车")
    gate = delivery_gate(order, now)
    if not gate["allow"]:
        raise HTTPException(409, "当前不允许交车：" + "；".join(gate["reasons"]))
    order.status = models.ST_DELIVERED
    order.delivered_at = datetime.utcnow()
    order.delivered_by = operator
    db.flush()
    return order
