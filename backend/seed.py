"""初始化库存与一条演示工单（幂等：已有数据则跳过）。"""
from datetime import timedelta

from .database import Base, SessionLocal, engine
from . import models
from .models import utcnow
from .services import add_event

INVENTORY = [
    ("FW-CAMRY-2020", "丰田凯美瑞 2020 前挡玻璃", 5),
    ("FW-ACCORD-2019", "本田雅阁 2019 前挡玻璃", 4),
    ("FW-CRV-2021", "本田 CR-V 2021 前挡玻璃", 3),
    ("FW-MODEL3-2022", "特斯拉 Model 3 2022 前挡玻璃", 2),
    ("RW-GOLF-2018", "大众高尔夫 2018 后挡玻璃", 2),
    ("SW-SAGITAR-2020", "大众速腾 2020 侧窗玻璃", 6),
]


def seed_all(include_demo: bool = True):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(models.InventoryItem).count() == 0:
            for model, name, total in INVENTORY:
                db.add(models.InventoryItem(glass_model=model, name=name, total=total))
            db.commit()

        if include_demo and db.query(models.WorkOrder).count() == 0:
            import secrets
            wo = models.WorkOrder(
                order_no="WO" + utcnow().strftime("%Y%m%d") + "-001",
                plate_number="沪A·D12345",
                owner_name="张先生",
                owner_phone="138****0001",
                vehicle_model="丰田凯美瑞 2020 款",
                damage_desc="前挡玻璃被石子击中，裂纹约 15cm",
                estimated_pickup_at=utcnow() + timedelta(days=1),
                owner_token=secrets.token_hex(8),
            )
            db.add(wo)
            db.flush()
            q = models.Quote(
                work_order_id=wo.id, revision=1, glass_model="FW-CAMRY-2020",
                glass_price=1800, labor_fee=500, other_fee=100, total=2400,
                payment_method="INSURANCE", insurance_amount=2000, self_pay_amount=400,
                reason="INITIAL", note="初始报价：更换前挡玻璃，含工时与辅料",
                status="CONFIRMED", confirmed_at=utcnow(),
            )
            db.add(q)
            item = db.query(models.InventoryItem).filter_by(glass_model="FW-CAMRY-2020").first()
            item.reserved += 1
            wo.inventory_confirmed = True
            wo.reserved_glass_model = "FW-CAMRY-2020"
            add_event(db, wo, "WO_CREATED", "演示工单已创建（接车）")
            add_event(db, wo, "QUOTE_CONFIRMED", "车主已确认第 1 版报价（初始报价）：总价 ¥2400.00，保险承担 ¥2000.00，车主自付 ¥400.00")
            add_event(db, wo, "INVENTORY_CONFIRMED", "库存已确认：FW-CAMRY-2020 预留 1 件")
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
    print("初始化完成：库存与演示工单")
