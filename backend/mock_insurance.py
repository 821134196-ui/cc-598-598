"""模拟保险公司接口。

以独立子应用形式挂载在 /mock-insurance，业务后端通过 HTTP（ASGI 传输）调用，
模拟真实的外部保险直赔接口：
- POST /claims   受理理赔，按规则（或强制参数）生成决定，回执在 delay_seconds 后可见
- GET  /receipts 业务系统轮询拉取已生成的回执（after_id 增量）
- GET  /claims   调试用，查看保险公司侧所有案件
"""
from datetime import timedelta

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

from .database import SessionLocal
from . import models
from .models import utcnow
from .services import iso

mock_app = FastAPI(title="模拟保险公司接口")

DENY_THRESHOLD = 8000.0  # 默认规则：申请金额超过该值则拒赔


class MockClaimIn(BaseModel):
    claim_number: str
    plate_number: str = ""
    amount: float
    delay_seconds: int = 10
    force_decision: Optional[str] = None  # APPROVED / DENIED，演示用


@mock_app.post("/claims")
def submit_claim(inp: MockClaimIn):
    db = SessionLocal()
    try:
        existing = db.query(models.MockClaim).filter_by(claim_number=inp.claim_number).first()
        if existing:
            return {"ok": True, "claim_number": inp.claim_number, "message": "案件已受理（重复提交忽略）"}
        decision = inp.force_decision or ("DENIED" if inp.amount > DENY_THRESHOLD else "APPROVED")
        now = utcnow()
        mc = models.MockClaim(
            claim_number=inp.claim_number,
            plate_number=inp.plate_number,
            amount=inp.amount,
            decision=decision,
            approved_amount=inp.amount if decision == "APPROVED" else 0.0,
            reason="" if decision == "APPROVED" else "案件需人工核保，暂不予直赔",
            decided_at=now,
            available_at=now + timedelta(seconds=max(0, inp.delay_seconds)),
        )
        db.add(mc)
        db.commit()
        return {"ok": True, "claim_number": inp.claim_number,
                "message": f"已受理，回执将在 {inp.delay_seconds} 秒后生成"}
    finally:
        db.close()


@mock_app.get("/receipts")
def receipts(after_id: int = 0):
    """返回已到达可见时间、且编号大于 after_id 的回执。"""
    db = SessionLocal()
    try:
        now = utcnow()
        rows = (db.query(models.MockClaim)
                .filter(models.MockClaim.id > after_id, models.MockClaim.available_at <= now)
                .order_by(models.MockClaim.id).all())
        return {"receipts": [{
            "receipt_id": r.id,
            "claim_number": r.claim_number,
            "decision": r.decision,
            "approved_amount": r.approved_amount,
            "reason": r.reason,
            "decided_at": iso(r.decided_at),
        } for r in rows]}
    finally:
        db.close()


@mock_app.get("/claims")
def list_claims():
    db = SessionLocal()
    try:
        rows = db.query(models.MockClaim).order_by(models.MockClaim.id).all()
        return {"claims": [{
            "receipt_id": r.id, "claim_number": r.claim_number, "amount": r.amount,
            "decision": r.decision, "approved_amount": r.approved_amount,
            "decided_at": iso(r.decided_at), "available_at": iso(r.available_at),
        } for r in rows]}
    finally:
        db.close()
