"""业务规则核心：报价版本、保险回执应用、交付门槛。

关键规则：
1. 交付前必须同时满足：报价已获车主确认授权、费用方案已确定（保险已批复或自费已确认）、
   施工未暂停、已上传安装照片、已登记固化信息且固化时间已到、验收通过。
2. 保险拒赔后必须生成新报价（自费）并由车主重新确认授权，原报价保留为历史版本。
3. 理赔回执应用时，若其对应的报价版本已不是当前确认版本（车主已变更方案），
   则回执标记为 STALE，只记录日志，绝不覆盖已确认的方案与金额。
"""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models
from .models import utcnow

# ---------------- 文案 ----------------

REASON_LABELS = {
    "INITIAL": "初始报价",
    "DENIAL_CONVERT": "拒赔转自费",
    "MODEL_MISMATCH": "型号不符",
    "NEW_DAMAGE": "新发现破损",
    "OWNER_REQUEST": "车主变更方案",
}
PAYMENT_LABELS = {"INSURANCE": "保险直赔", "SELF_PAY": "车主自费"}
QUOTE_STATUS_LABELS = {
    "PENDING_OWNER": "待车主确认",
    "CONFIRMED": "已确认",
    "SUPERSEDED": "已作废（历史保留）",
}
CLAIM_STATUS_LABELS = {
    "SUBMITTED": "待回执",
    "APPROVED": "已批复",
    "DENIED": "已拒赔",
    "STALE": "迟到回执·未应用",
}
PAUSE_LABELS = {
    "MODEL_MISMATCH": "型号不符",
    "NEW_DAMAGE": "新发现破损",
    "OTHER": "其他",
}
PHOTO_STAGE_LABELS = {"BEFORE": "施工前", "DURING": "施工中", "AFTER": "施工后"}
STATUS_LABELS = {
    "INTAKE": "已接车",
    "QUOTE_PENDING": "待车主确认报价",
    "CONFIRMED": "报价已确认",
    "INSURANCE_REVIEW": "保险理赔中",
    "DENIED": "保险拒赔·待新方案",
    "READY": "待施工",
    "IN_PROGRESS": "施工中",
    "PAUSED": "施工暂停",
    "INSTALLED": "固化/验收中",
    "DELIVERED": "已交车",
}


def iso(dt):
    return dt.isoformat() + "Z" if dt else None


def fmt_cn(dt):
    """事件消息中嵌入的时间，用服务器本地时区显示。"""
    if not dt:
        return "-"
    return dt.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def parse_dt(s):
    if not s:
        return None
    if isinstance(s, datetime):
        d = s
    else:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def naive_utc(d):
    """把带时区的时间统一转为 UTC 朴素时间存储。"""
    if d is None:
        return None
    if d.tzinfo is not None:
        return d.astimezone(timezone.utc).replace(tzinfo=None)
    return d


def get_setting(db: Session, key: str, default=None):
    row = db.get(models.Setting, key)
    if row is None:
        return default
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return row.value


def set_setting(db: Session, key: str, value):
    row = db.get(models.Setting, key)
    if row is None:
        db.add(models.Setting(key=key, value=str(value)))
    else:
        row.value = str(value)


def add_event(db: Session, wo: models.WorkOrder, type_: str, message: str):
    db.add(models.Event(work_order_id=wo.id, type=type_, message=message, created_at=utcnow()))


# ---------------- 报价与理赔查询 ----------------

def latest_quote(wo: models.WorkOrder):
    return wo.quotes[-1] if wo.quotes else None


def confirmed_quote(wo: models.WorkOrder):
    for q in reversed(wo.quotes):
        if q.status == "CONFIRMED":
            return q
    return None


def insurance_settled(wo: models.WorkOrder):
    """费用方案是否已确定：自费方案已确认，或保险方案已批复。"""
    cq = confirmed_quote(wo)
    if not cq:
        return False, "无已确认报价"
    if cq.payment_method == "SELF_PAY":
        return True, f"自费方案已确认，车主自付 ¥{cq.self_pay_amount:.2f}"
    for c in sorted(wo.claims, key=lambda c: c.id):
        if c.quote_revision != cq.revision:
            continue
        if c.status == "APPROVED":
            return True, f"保险已批复 ¥{c.approved_amount:.2f}（{c.claim_number}）"
        if c.status == "DENIED":
            return False, f"保险已拒赔（{c.decision_reason or '未说明原因'}），需生成自费新报价并由车主确认"
        if c.status == "SUBMITTED":
            return False, f"理赔 {c.claim_number} 已提交，等待保险回执"
    return False, "尚未提交保险理赔"


def derive_status(wo: models.WorkOrder) -> str:
    if wo.delivered_at:
        return "DELIVERED"
    if wo.is_paused:
        return "PAUSED"
    inst = wo.installation
    if inst and inst.started_at:
        return "INSTALLED" if inst.finished_at else "IN_PROGRESS"
    lq = latest_quote(wo)
    if not lq:
        return "INTAKE"
    cq = confirmed_quote(wo)
    if not cq:
        return "QUOTE_PENDING"
    if cq.payment_method == "INSURANCE":
        st = None
        for c in wo.claims:
            if c.quote_revision == cq.revision:
                st = c.status
        if st == "SUBMITTED":
            return "INSURANCE_REVIEW"
        if st == "DENIED":
            return "DENIED"
        if st != "APPROVED":
            return "CONFIRMED"
    # 自费已确认 或 保险已批复：再看库存
    if wo.inventory_confirmed and wo.reserved_glass_model == cq.glass_model:
        return "READY"
    return "CONFIRMED"


# ---------------- 交付门槛 ----------------

def delivery_check(wo: models.WorkOrder) -> dict:
    checks = []

    def add(key, label, ok, detail=""):
        checks.append({"key": key, "label": label, "passed": bool(ok), "detail": detail})

    cq = confirmed_quote(wo)
    lq = latest_quote(wo)
    if lq and lq.status == "PENDING_OWNER":
        # 最新方案（如拒赔改价）尚未获车主重新授权，即使旧报价曾确认也不得交付
        add("quote_confirmed", "当前报价已获车主确认授权", False,
            f"第 {lq.revision} 版报价（{REASON_LABELS.get(lq.reason, lq.reason)}）尚未获得车主确认授权，"
            f"交付前须完成重新授权")
    elif cq:
        add("quote_confirmed", "当前报价已获车主确认授权", True,
            f"第 {cq.revision} 版 · {REASON_LABELS.get(cq.reason, cq.reason)} · 确认于 {fmt_cn(cq.confirmed_at)}")
    elif lq:
        add("quote_confirmed", "当前报价已获车主确认授权", False,
            f"第 {lq.revision} 版报价（{REASON_LABELS.get(lq.reason, lq.reason)}）尚未获得车主确认授权")
    else:
        add("quote_confirmed", "当前报价已获车主确认授权", False, "尚无报价")

    ok, detail = insurance_settled(wo)
    add("insurance_settled", "费用方案已确定（保险已批复或自费已确认）", ok, detail)

    add("not_paused", "施工未处于暂停状态", not wo.is_paused,
        f"已暂停（{PAUSE_LABELS.get(wo.pause_reason, wo.pause_reason or '')}），需确认新方案后恢复施工"
        if wo.is_paused else "施工正常")

    n = len(wo.photos)
    add("photos", "安装照片已上传", n > 0, f"已上传 {n} 张")

    inst = wo.installation
    add("finished", "安装完成并已登记固化信息", bool(inst and inst.finished_at),
        f"完成于 {fmt_cn(inst.finished_at)}" if inst and inst.finished_at else "尚未登记安装完成")

    if inst and inst.curing_deadline:
        now = utcnow()
        if now >= inst.curing_deadline:
            add("curing", "玻璃胶已固化（固化截止时间已到）", True, f"固化截止 {fmt_cn(inst.curing_deadline)}，时间已到")
        else:
            remain = int((inst.curing_deadline - now).total_seconds() // 60)
            add("curing", "玻璃胶已固化（固化截止时间已到）", False,
                f"固化中，截止 {fmt_cn(inst.curing_deadline)}，剩余约 {remain} 分钟，不得提前交车")
    else:
        add("curing", "玻璃胶已固化（固化截止时间已到）", False, "未登记固化截止时间")

    if inst and inst.acceptance_result == "PASSED":
        add("acceptance", "安装验收通过", True, inst.acceptance_note or "验收通过")
    elif inst and inst.acceptance_result == "FAILED":
        add("acceptance", "安装验收通过", False, f"验收未通过：{inst.acceptance_note or '未填写原因'}")
    else:
        add("acceptance", "安装验收通过", False, "尚未验收")

    return {
        "deliverable": all(c["passed"] for c in checks),
        "delivered": bool(wo.delivered_at),
        "delivered_at": iso(wo.delivered_at),
        "checks": checks,
    }


# ---------------- 报价操作 ----------------

def confirm_quote(db: Session, quote: models.Quote, by: str = "车主"):
    """车主确认报价（授权）。新版本确认后，旧的已确认版本转为 SUPERSEDED（保留历史）。"""
    wo = quote.work_order
    if wo.delivered_at:
        raise HTTPException(400, "工单已交付，无法变更方案")
    if quote.status != "PENDING_OWNER":
        raise HTTPException(400, "该报价不在待确认状态（可能已被更新的报价取代）")
    for q in wo.quotes:
        if q.status == "CONFIRMED":
            q.status = "SUPERSEDED"
    quote.status = "CONFIRMED"
    quote.confirmed_at = utcnow()
    # 玻璃型号变更 -> 释放原库存预留，需重新确认库存
    if wo.inventory_confirmed and wo.reserved_glass_model != quote.glass_model:
        item = db.query(models.InventoryItem).filter_by(glass_model=wo.reserved_glass_model).first()
        if item and item.reserved > 0:
            item.reserved -= 1
        add_event(db, wo, "INVENTORY_RELEASED",
                  f"玻璃型号由 {wo.reserved_glass_model} 变更为 {quote.glass_model}，"
                  f"原库存预留已释放，需重新确认库存")
        wo.inventory_confirmed = False
        wo.reserved_glass_model = None
    add_event(db, wo, "QUOTE_CONFIRMED",
              f"{by}已确认第 {quote.revision} 版报价（{REASON_LABELS.get(quote.reason, quote.reason)}）："
              f"总价 ¥{quote.total:.2f}，保险承担 ¥{quote.insurance_amount:.2f}，"
              f"车主自付 ¥{quote.self_pay_amount:.2f}")
    db.commit()


# ---------------- 保险回执应用（核心防错规则） ----------------

def apply_receipt(db: Session, r: dict) -> dict:
    """应用一条保险回执。

    迟到回执判定：回执对应的是提交理赔时的报价版本；若当前已确认的报价版本
    与之不同（车主在回执到达前已变更并确认了新方案），则回执标记 STALE，
    只记录事件，不修改任何金额与方案。
    """
    claim = db.query(models.InsuranceClaim).filter_by(claim_number=r["claim_number"]).first()
    if not claim:
        return {"outcome": "unknown", "claim_number": r["claim_number"]}
    if claim.status != "SUBMITTED":
        return {"outcome": "duplicate", "claim_number": claim.claim_number}

    wo = claim.work_order
    claim.decided_at = parse_dt(r.get("decided_at"))
    claim.received_at = utcnow()
    cq = confirmed_quote(wo)

    if cq is None or cq.revision != claim.quote_revision:
        claim.status = "STALE"
        cur = (f"第 {cq.revision} 版方案（{fmt_cn(cq.confirmed_at)} 确认）" if cq else "无已确认方案")
        add_event(db, wo, "RECEIPT_STALE",
                  f"收到迟到的理赔回执（{claim.claim_number}，对应第 {claim.quote_revision} 版方案，"
                  f"决定：{'批复' if r['decision'] == 'APPROVED' else '拒赔'}，决定时间 {fmt_cn(claim.decided_at)}），"
                  f"但车主已确认{cur}。回执未应用，工单方案与金额不受影响。")
        db.commit()
        return {"outcome": "stale", "claim_number": claim.claim_number}

    if r["decision"] == "APPROVED":
        claim.status = "APPROVED"
        claim.approved_amount = round(float(r["approved_amount"]), 2)
        old_ins = cq.insurance_amount
        cq.insurance_amount = claim.approved_amount
        cq.self_pay_amount = round(cq.total - cq.insurance_amount, 2)
        add_event(db, wo, "CLAIM_APPROVED",
                  f"理赔批复（{claim.claim_number}）：保险公司承担 ¥{claim.approved_amount:.2f}，"
                  f"车主自付 ¥{cq.self_pay_amount:.2f}")
        if abs(old_ins - cq.insurance_amount) > 0.005:
            # 批复金额与报价不一致 -> 金额发生变化，需车主重新授权
            cq.status = "PENDING_OWNER"
            cq.confirmed_at = None
            add_event(db, wo, "QUOTE_RECONFIRM_REQUIRED",
                      "批复金额与报价不一致，方案金额已更新，需车主重新确认授权后方可继续")
    else:
        claim.status = "DENIED"
        claim.decision_reason = r.get("reason", "") or "保险公司拒赔"
        add_event(db, wo, "CLAIM_DENIED",
                  f"保险拒赔（{claim.claim_number}）：{claim.decision_reason}。"
                  f"可转为自费——须生成新报价并取得车主确认，原报价保留。")
    db.commit()
    return {"outcome": "applied", "claim_number": claim.claim_number, "decision": r["decision"]}


# ---------------- 序列化 ----------------

def quote_dict(q: models.Quote) -> dict:
    return {
        "id": q.id, "revision": q.revision,
        "reason": q.reason, "reason_label": REASON_LABELS.get(q.reason, q.reason),
        "glass_model": q.glass_model,
        "glass_price": q.glass_price, "labor_fee": q.labor_fee, "other_fee": q.other_fee,
        "total": q.total,
        "payment_method": q.payment_method,
        "payment_label": PAYMENT_LABELS.get(q.payment_method, q.payment_method),
        "insurance_amount": q.insurance_amount, "self_pay_amount": q.self_pay_amount,
        "status": q.status, "status_label": QUOTE_STATUS_LABELS.get(q.status, q.status),
        "note": q.note,
        "created_at": iso(q.created_at), "confirmed_at": iso(q.confirmed_at),
    }


def claim_dict(c: models.InsuranceClaim) -> dict:
    return {
        "id": c.id, "claim_number": c.claim_number, "quote_revision": c.quote_revision,
        "amount": c.amount, "status": c.status,
        "status_label": CLAIM_STATUS_LABELS.get(c.status, c.status),
        "approved_amount": c.approved_amount, "decision_reason": c.decision_reason,
        "submitted_at": iso(c.submitted_at), "decided_at": iso(c.decided_at),
        "received_at": iso(c.received_at),
    }


def installation_dict(inst: models.Installation):
    if not inst:
        return None
    return {
        "started_at": iso(inst.started_at), "finished_at": iso(inst.finished_at),
        "glue_type": inst.glue_type, "curing_deadline": iso(inst.curing_deadline),
        "acceptance_result": inst.acceptance_result, "acceptance_note": inst.acceptance_note,
        "accepted_at": iso(inst.accepted_at),
    }


def photo_dict(p: models.Photo) -> dict:
    return {
        "id": p.id, "url": f"/uploads/{p.filename}",
        "stage": p.stage, "stage_label": PHOTO_STAGE_LABELS.get(p.stage, p.stage),
        "note": p.note, "uploaded_at": iso(p.uploaded_at),
    }


def event_dict(e: models.Event) -> dict:
    return {"id": e.id, "type": e.type, "message": e.message, "created_at": iso(e.created_at)}


def wo_brief(wo: models.WorkOrder) -> dict:
    lq = latest_quote(wo)
    status = derive_status(wo)
    return {
        "id": wo.id, "order_no": wo.order_no, "plate_number": wo.plate_number,
        "owner_name": wo.owner_name, "vehicle_model": wo.vehicle_model,
        "status": status, "status_label": STATUS_LABELS[status],
        "glass_model": lq.glass_model if lq else "",
        "total": lq.total if lq else 0,
        "estimated_pickup_at": iso(wo.estimated_pickup_at),
        "delivered_at": iso(wo.delivered_at), "created_at": iso(wo.created_at),
    }


def wo_detail(wo: models.WorkOrder) -> dict:
    d = wo_brief(wo)
    d.update({
        "owner_phone": wo.owner_phone,
        "damage_desc": wo.damage_desc,
        "is_paused": wo.is_paused,
        "pause_reason": wo.pause_reason,
        "pause_reason_label": PAUSE_LABELS.get(wo.pause_reason, wo.pause_reason or ""),
        "pause_note": wo.pause_note,
        "inventory": {"confirmed": wo.inventory_confirmed, "reserved_model": wo.reserved_glass_model},
        "owner_path": f"/#/owner/{wo.owner_token}",
        "quotes": [quote_dict(q) for q in wo.quotes],
        "claims": [claim_dict(c) for c in wo.claims],
        "installation": installation_dict(wo.installation),
        "photos": [photo_dict(p) for p in wo.photos],
        "events": [event_dict(e) for e in reversed(wo.events)],
        "delivery": delivery_check(wo),
    })
    return d


def owner_dict(wo: models.WorkOrder) -> dict:
    """车主视图：玻璃型号、保险承担、自付、预计提车时间、待确认报价。"""
    status = derive_status(wo)
    cq = confirmed_quote(wo)
    lq = latest_quote(wo)
    shown = cq or lq
    ins_ok, ins_detail = insurance_settled(wo)
    return {
        "order_no": wo.order_no, "plate_number": wo.plate_number,
        "owner_name": wo.owner_name, "vehicle_model": wo.vehicle_model,
        "status": status, "status_label": STATUS_LABELS[status],
        "glass_model": shown.glass_model if shown else "",
        "estimated_pickup_at": iso(wo.estimated_pickup_at),
        "delivered_at": iso(wo.delivered_at),
        "current_quote": quote_dict(cq) if cq else None,
        "insurance_detail": ins_detail,
        "quotes": [quote_dict(q) for q in reversed(wo.quotes)],
        "events": [event_dict(e) for e in reversed(wo.events)],
    }
