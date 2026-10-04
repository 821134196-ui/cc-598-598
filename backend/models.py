from datetime import datetime, timezone

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow() -> datetime:
    """统一的 UTC 朴素时间，避免时区不一致。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WorkOrder(Base):
    """玻璃维修工单：接车 -> 报价 -> 保险 -> 施工 -> 交车，全程一单。"""

    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True)
    order_no = Column(String, unique=True, index=True)
    plate_number = Column(String, index=True)
    owner_name = Column(String)
    owner_phone = Column(String, default="")
    vehicle_model = Column(String, default="")
    damage_desc = Column(Text, default="")
    estimated_pickup_at = Column(DateTime, nullable=True)  # 预计提车时间
    owner_token = Column(String, unique=True, index=True)  # 车主页访问令牌

    inventory_confirmed = Column(Boolean, default=False)   # 库存是否已确认
    reserved_glass_model = Column(String, nullable=True)   # 已预留的玻璃型号

    is_paused = Column(Boolean, default=False)             # 施工是否暂停
    pause_reason = Column(String, nullable=True)           # MODEL_MISMATCH / NEW_DAMAGE / OTHER
    pause_note = Column(Text, default="")
    paused_at = Column(DateTime, nullable=True)

    delivered_at = Column(DateTime, nullable=True)         # 交车时间（唯一权威交付标记）
    created_at = Column(DateTime, default=utcnow)

    quotes = relationship("Quote", back_populates="work_order", order_by="Quote.revision")
    claims = relationship("InsuranceClaim", back_populates="work_order", order_by="InsuranceClaim.id")
    installation = relationship("Installation", back_populates="work_order", uselist=False)
    photos = relationship("Photo", back_populates="work_order", order_by="Photo.id")
    events = relationship("Event", back_populates="work_order", order_by="Event.id")


class Quote(Base):
    """报价版本。每次方案变更生成新版本，历史版本保留（SUPERSEDED），不删除。"""

    __tablename__ = "quotes"

    id = Column(Integer, primary_key=True)
    work_order_id = Column(ForeignKey("work_orders.id"))
    revision = Column(Integer)                 # 版本号，从 1 递增
    glass_model = Column(String)
    glass_price = Column(Float, default=0.0)
    labor_fee = Column(Float, default=0.0)
    other_fee = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    payment_method = Column(String)            # INSURANCE / SELF_PAY
    insurance_amount = Column(Float, default=0.0)   # 保险承担金额
    self_pay_amount = Column(Float, default=0.0)    # 车主自付金额
    reason = Column(String)                    # INITIAL / DENIAL_CONVERT / MODEL_MISMATCH / NEW_DAMAGE / OWNER_REQUEST
    note = Column(Text, default="")            # 方案说明（变更原因与费用说明）
    status = Column(String, default="PENDING_OWNER")  # PENDING_OWNER / CONFIRMED / SUPERSEDED
    created_at = Column(DateTime, default=utcnow)
    confirmed_at = Column(DateTime, nullable=True)    # 车主确认（授权）时间

    work_order = relationship("WorkOrder", back_populates="quotes")


class InsuranceClaim(Base):
    """提交给保险公司的理赔记录。STALE 表示迟到回执，未应用到工单。"""

    __tablename__ = "claims"

    id = Column(Integer, primary_key=True)
    work_order_id = Column(ForeignKey("work_orders.id"))
    claim_number = Column(String, unique=True)
    quote_revision = Column(Integer)           # 提交理赔时对应的报价版本
    amount = Column(Float)                     # 申请赔付金额
    status = Column(String, default="SUBMITTED")  # SUBMITTED / APPROVED / DENIED / STALE
    approved_amount = Column(Float, nullable=True)
    decision_reason = Column(String, default="")
    submitted_at = Column(DateTime, default=utcnow)
    decided_at = Column(DateTime, nullable=True)    # 回执上的决定时间
    received_at = Column(DateTime, nullable=True)   # 本系统收到回执的时间

    work_order = relationship("WorkOrder", back_populates="claims")


class Installation(Base):
    """施工记录：开工、胶的固化截止时间、验收结果。"""

    __tablename__ = "installations"

    id = Column(Integer, primary_key=True)
    work_order_id = Column(ForeignKey("work_orders.id"), unique=True)
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)
    glue_type = Column(String, default="")
    curing_deadline = Column(DateTime, nullable=True)      # 胶固化截止时间，未到不得交车
    acceptance_result = Column(String, default="PENDING")  # PENDING / PASSED / FAILED
    acceptance_note = Column(Text, default="")
    accepted_at = Column(DateTime, nullable=True)

    work_order = relationship("WorkOrder", back_populates="installation")


class Photo(Base):
    """安装照片，文件保存在本地 uploads/ 目录。"""

    __tablename__ = "photos"

    id = Column(Integer, primary_key=True)
    work_order_id = Column(ForeignKey("work_orders.id"))
    filename = Column(String)
    stage = Column(String, default="DURING")   # BEFORE / DURING / AFTER
    note = Column(String, default="")
    uploaded_at = Column(DateTime, default=utcnow)

    work_order = relationship("WorkOrder", back_populates="photos")


class InventoryItem(Base):
    """玻璃库存。total 为总件数，reserved 为已预留件数。"""

    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True)
    glass_model = Column(String, unique=True)
    name = Column(String, default="")
    total = Column(Integer, default=0)
    reserved = Column(Integer, default=0)


class Event(Base):
    """工单事件日志：所有关键动作留痕，便于审计（如迟到回执被忽略）。"""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    work_order_id = Column(ForeignKey("work_orders.id"))
    type = Column(String)
    message = Column(Text)
    created_at = Column(DateTime, default=utcnow)

    work_order = relationship("WorkOrder", back_populates="events")


class MockClaim(Base):
    """模拟保险公司一侧的数据（独立于业务表，模拟外部系统）。"""

    __tablename__ = "mock_claims"

    id = Column(Integer, primary_key=True)     # id 同时作为回执编号
    claim_number = Column(String, unique=True, index=True)
    plate_number = Column(String, default="")
    amount = Column(Float, default=0.0)
    decision = Column(String)                  # APPROVED / DENIED
    approved_amount = Column(Float, default=0.0)
    reason = Column(String, default="")
    decided_at = Column(DateTime)
    available_at = Column(DateTime)            # 回执对业务系统可见的时间（模拟延迟）
    created_at = Column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String, default="")
