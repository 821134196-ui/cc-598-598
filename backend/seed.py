"""初始化演示数据：python -m backend.seed（重复执行会跳过）"""
from .database import Base, SessionLocal, engine
from . import models

Base.metadata.create_all(bind=engine)


def run():
    db = SessionLocal()
    try:
        if db.query(models.WorkOrder).count() > 0:
            print("已存在工单数据，跳过种子初始化。")
            return

        order = models.WorkOrder(
            order_no="WO20261004001",
            customer_name="张伟",
            customer_phone="13800001234",
            plate_no="沪A·12345",
            car_model="比亚迪 汉 EV",
            glass_position="前挡风玻璃",
            note="高速石子击中，有 8cm 裂纹",
            insurance_company="平安财险",
            claim_no="CLM-DEMO-001",
        )
        db.add(order)
        db.flush()
        db.add(models.Quote(
            order_id=order.id, version=1, kind=models.QK_INSURANCE,
            status=models.QS_PENDING,
            glass_model="FY XYG-汉EV-2024-FW-LAM",
            glass_spec="夹层隔音前挡 / HUD 兼容 / 2080×1020",
            price_glass=1850, price_labor=300, price_sealant=120, price_other=0,
            total_amount=2270, insurance_cover=0,
            change_reason="初次报价，待保险核定理赔金额",
        ))
        db.commit()
        print("已创建演示工单 WO20261004001（车主：张伟，报案号 CLM-DEMO-001）")
    finally:
        db.close()


if __name__ == "__main__":
    run()
