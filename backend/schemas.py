from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class QuoteIn(BaseModel):
    glass_model: str = Field(..., min_length=1)
    glass_spec: str = ""
    price_glass: float = 0
    price_labor: float = 0
    price_sealant: float = 0
    price_other: float = 0
    insurance_cover: float = 0
    change_reason: str = ""


class OrderCreate(BaseModel):
    customer_name: str = Field(..., min_length=1)
    customer_phone: str = Field(..., min_length=4)
    plate_no: str = Field(..., min_length=2)
    car_model: str = Field(..., min_length=1)
    glass_position: str = Field(..., min_length=1)
    note: str = ""
    insurance_company: str = ""
    claim_no: str = ""


class CustomerConfirmIn(BaseModel):
    customer_authorization: str = Field(
        ..., min_length=4, description="车主授权语句，如：本人确认并同意支付自付金额"
    )


class ScheduleIn(BaseModel):
    worker: str = Field("", description="登记施工人员（仅记录用）")


class PauseIn(BaseModel):
    reason: str = Field(..., min_length=2, description="型号不符 / 新破损 等")


class CureIn(BaseModel):
    cure_minutes: int = Field(..., ge=1, description="胶固化需要的分钟数，从登记时刻起算")


class InspectIn(BaseModel):
    passed: bool
    note: str = ""


class DeliverIn(BaseModel):
    operator: str = Field("", description="交车经办人")


class ReceiptSimIn(BaseModel):
    """模拟保险公司推送回执。"""
    claim_no: str
    decision: str  # approved / rejected
    cover_amount: float = 0
    reason: str = ""
    issued_minutes_ago: int = 0  # 模拟回执签发时间；>0 可模拟迟到回执


class QuoteOut(BaseModel):
    id: int
    version: int
    kind: str
    status: str
    glass_model: str
    glass_spec: str
    price_glass: float
    price_labor: float
    price_sealant: float
    price_other: float
    total_amount: float
    insurance_cover: float
    self_pay: float
    change_reason: str
    customer_authorization: str
    created_at: datetime
    confirmed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PhotoOut(BaseModel):
    id: int
    filename: str
    original_name: str
    stage: str
    uploaded_at: datetime

    class Config:
        from_attributes = True


class ReceiptOut(BaseModel):
    id: int
    decision: str
    cover_amount: float
    reason: str
    issued_at: datetime
    received_at: datetime
    applied: bool
    ignore_reason: str

    class Config:
        from_attributes = True


class DeliveryGate(BaseModel):
    allow: bool
    cured: bool
    minutes_until_cured: Optional[int] = None
    inspection_passed: bool
    photos_ok: bool
    confirmed_quote_ok: bool
    reasons: list[str]


class OrderOut(BaseModel):
    id: int
    order_no: str
    customer_name: str
    customer_phone: str
    plate_no: str
    car_model: str
    glass_position: str
    note: str
    status: str
    insurance_company: str
    claim_no: str
    insurance_decision: str
    stock_confirmed: bool
    stock_confirmed_at: Optional[datetime]
    delivered_at: Optional[datetime]
    delivered_by: str
    created_at: datetime
    quotes: list[QuoteOut]
    receipts: list[ReceiptOut]
    photos: list[PhotoOut]
    delivery_gate: DeliveryGate
    cure_deadline: Optional[datetime] = None
    inspection_result: str = "pending"
    inspection_note: str = ""
    pause_reason: str = ""
    # 车主视图摘要
    current_glass_model: Optional[str] = None
    current_total: float = 0
    current_insurance_cover: float = 0
    current_self_pay: float = 0
    eta: Optional[str] = None  # 预计提车时间（固化截止后可提）

    class Config:
        from_attributes = True
