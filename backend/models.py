from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base

# ---- 工单状态 ----
ST_CREATED = "created"            # 已接车，报价中
ST_READY = "ready"                # 库存+方案已确认，待安排施工
ST_SCHEDULED = "scheduled"        # 已安排施工
ST_INSTALLING = "installing"      # 施工中
ST_PAUSED = "paused"              # 施工暂停（型号不符 / 新破损）
ST_INSTALLED = "installed"        # 安装完成，待固化/验收/交车
ST_DELIVERED = "delivered"        # 已交车

ORDER_STATUSES = [
    ST_CREATED,
    ST_READY,
    ST_SCHEDULED,
    ST_INSTALLING,
    ST_PAUSED,
    ST_INSTALLED,
    ST_DELIVERED,
]

# ---- 报价类型 ----
QK_INSURANCE = "insurance"   # 保险直赔
QK_SELF_PAY = "self_pay"     # 自费（含拒赔转自费）
QK_REWORK = "rework"         # 施工中方案变更（型号不符 / 新破损）

# ---- 报价状态 ----
QS_DRAFT = "draft"
QS_PENDING = "pending_customer"   # 待车主确认
QS_CONFIRMED = "confirmed"        # 车主已确认
QS_SUPERSEDED = "superseded"      # 已被更新版本取代（记录保留）

# ---- 保险回执 ----
IN_PENDING = "pending"
IN_APPROVED = "approved"
IN_REJECTED = "rejected"


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True)
    order_no = Column(String(32), unique=True, nullable=False, index=True)
    customer_name = Column(String(64), nullable=False)
    customer_phone = Column(String(32), nullable=False, index=True)
    plate_no = Column(String(16), nullable=False)
    car_model = Column(String(64), nullable=False)
    glass_position = Column(String(32), nullable=False)   # 前挡 / 后挡 / 左前门...
    note = Column(Text, default="")

    status = Column(String(16), default=ST_CREATED, nullable=False)

    # 保险信息
    insurance_company = Column(String(64), default="")
    claim_no = Column(String(64), default="", index=True)
    insurance_decision = Column(String(16), default=IN_PENDING, nullable=False)

    # 门店库存确认
    stock_confirmed = Column(Boolean, default=False, nullable=False)
    stock_confirmed_at = Column(DateTime)

    delivered_at = Column(DateTime)
    delivered_by = Column(String(64), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    quotes = relationship(
        "Quote",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="Quote.version",
    )
    receipts = relationship(
        "InsuranceReceipt",
        back_populates="order",
        order_by="InsuranceReceipt.received_at",
    )
    install = relationship(
        "InstallRecord",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )
    photos = relationship(
        "InstallationPhoto",
        back_populates="order",
        cascade="all, delete-orphan",
        order_by="InstallationPhoto.uploaded_at",
    )


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("order_id", "version", name="uq_quote_version"),)

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    version = Column(Integer, nullable=False)
    kind = Column(String(16), nullable=False)
    status = Column(String(24), default=QS_DRAFT, nullable=False)

    glass_model = Column(String(128), nullable=False)
    glass_spec = Column(String(128), default="")
    price_glass = Column(Float, default=0.0)
    price_labor = Column(Float, default=0.0)
    price_sealant = Column(Float, default=0.0)
    price_other = Column(Float, default=0.0)
    total_amount = Column(Float, default=0.0)
    insurance_cover = Column(Float, default=0.0)

    change_reason = Column(Text, default="")  # 初次报价 / 拒赔转自费 / 型号不符 / 新增破损
    # 车主授权凭证：拒赔改价、施工中变更时必须重新授权
    customer_authorization = Column(String(128), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    confirmed_at = Column(DateTime)

    order = relationship("WorkOrder", back_populates="quotes")

    @property
    def self_pay(self) -> float:
        return round(max(0.0, (self.total_amount or 0.0) - (self.insurance_cover or 0.0)), 2)


class InsuranceReceipt(Base):
    """保险回执。迟到的回执只入库留痕，不覆盖车主已确认的方案。"""

    __tablename__ = "insurance_receipts"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    decision = Column(String(16), nullable=False)
    cover_amount = Column(Float, default=0.0)
    reason = Column(Text, default="")
    issued_at = Column(DateTime, nullable=False)    # 保险公司签发时间
    received_at = Column(DateTime, default=datetime.utcnow)  # 到店时间
    applied = Column(Boolean, default=False)        # 是否实际作用于工单
    ignore_reason = Column(Text, default="")        # 未应用原因（如：迟到，车主已确认自费方案）

    order = relationship("WorkOrder", back_populates="receipts")


class InstallRecord(Base):
    __tablename__ = "install_records"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("work_orders.id"), unique=True, nullable=False)

    started_at = Column(DateTime)
    paused_at = Column(DateTime)
    pause_reason = Column(Text, default="")
    resumed_at = Column(DateTime)
    finished_at = Column(DateTime)

    cure_deadline = Column(DateTime)               # 胶固化截止时间
    cure_registered_at = Column(DateTime)

    inspection_result = Column(String(16), default="pending")  # pending / pass / fail
    inspected_at = Column(DateTime)
    inspection_note = Column(Text, default="")

    order = relationship("WorkOrder", back_populates="install")


class InstallationPhoto(Base):
    __tablename__ = "installation_photos"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255), default="")
    stage = Column(String(32), default="install")
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    order = relationship("WorkOrder", back_populates="photos")
