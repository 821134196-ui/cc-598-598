from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WorkOrderCreate(BaseModel):
    plate_number: str
    owner_name: str
    owner_phone: str = ""
    vehicle_model: str = ""
    glass_model: str
    damage_desc: str = ""
    estimated_pickup_at: Optional[datetime] = None
    glass_price: float = 0
    labor_fee: float = 0
    other_fee: float = 0
    payment_method: str = "INSURANCE"   # INSURANCE / SELF_PAY
    insurance_amount: float = 0
    note: str = ""


class QuoteCreate(BaseModel):
    reason: str                          # DENIAL_CONVERT / MODEL_MISMATCH / NEW_DAMAGE / OWNER_REQUEST
    glass_model: str
    glass_price: float = 0
    labor_fee: float = 0
    other_fee: float = 0
    payment_method: str = "SELF_PAY"
    insurance_amount: float = 0
    note: str = ""                       # 方案说明（变更原因与费用）


class ClaimSubmit(BaseModel):
    delay_seconds: int = 10              # 模拟回执延迟
    force_decision: Optional[str] = None  # 模拟接口专用：强制 APPROVED / DENIED


class PauseIn(BaseModel):
    reason: str                          # MODEL_MISMATCH / NEW_DAMAGE / OTHER
    note: str = ""


class FinishIn(BaseModel):
    glue_type: str = "聚氨酯结构胶"
    curing_deadline: datetime            # 胶的固化截止时间


class AcceptanceIn(BaseModel):
    result: str                          # PASSED / FAILED
    note: str = ""


class EstimatedPickupIn(BaseModel):
    estimated_pickup_at: datetime
