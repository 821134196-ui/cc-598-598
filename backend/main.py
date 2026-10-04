import os
import shutil
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import models, schemas, services
from .database import Base, engine, get_db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(UPLOAD_DIR, exist_ok=True)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="汽车玻璃保险直赔与安装验收系统", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- 序列化

def _quote_out(q: models.Quote) -> dict:
    return {
        "id": q.id,
        "version": q.version,
        "kind": q.kind,
        "status": q.status,
        "glass_model": q.glass_model,
        "glass_spec": q.glass_spec,
        "price_glass": q.price_glass,
        "price_labor": q.price_labor,
        "price_sealant": q.price_sealant,
        "price_other": q.price_other,
        "total_amount": q.total_amount,
        "insurance_cover": q.insurance_cover,
        "self_pay": q.self_pay,
        "change_reason": q.change_reason,
        "customer_authorization": q.customer_authorization,
        "created_at": q.created_at,
        "confirmed_at": q.confirmed_at,
    }


def serialize_order(order: models.WorkOrder) -> dict:
    gate = services.delivery_gate(order)
    cur = services.active_quote(order)
    cure_deadline = order.install.cure_deadline if order.install else None
    eta = None
    if cure_deadline and order.status != models.ST_DELIVERED:
        eta = f"{cure_deadline:%Y-%m-%d %H:%M} 固化到期后可提车"

    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "plate_no": order.plate_no,
        "car_model": order.car_model,
        "glass_position": order.glass_position,
        "note": order.note,
        "status": order.status,
        "insurance_company": order.insurance_company,
        "claim_no": order.claim_no,
        "insurance_decision": order.insurance_decision,
        "stock_confirmed": order.stock_confirmed,
        "stock_confirmed_at": order.stock_confirmed_at,
        "delivered_at": order.delivered_at,
        "delivered_by": order.delivered_by,
        "created_at": order.created_at,
        "quotes": [_quote_out(q) for q in order.quotes],
        "receipts": [
            {
                "id": r.id,
                "decision": r.decision,
                "cover_amount": r.cover_amount,
                "reason": r.reason,
                "issued_at": r.issued_at,
                "received_at": r.received_at,
                "applied": r.applied,
                "ignore_reason": r.ignore_reason,
            }
            for r in order.receipts
        ],
        "photos": [
            {
                "id": p.id,
                "filename": p.filename,
                "original_name": p.original_name,
                "stage": p.stage,
                "uploaded_at": p.uploaded_at,
            }
            for p in order.photos
        ],
        "delivery_gate": gate,
        "cure_deadline": cure_deadline,
        "inspection_result": order.install.inspection_result if order.install else "pending",
        "inspection_note": order.install.inspection_note if order.install else "",
        "pause_reason": order.install.pause_reason if order.install else "",
        "current_glass_model": cur.glass_model if cur else None,
        "current_total": cur.total_amount if cur else 0,
        "current_insurance_cover": cur.insurance_cover if cur else 0,
        "current_self_pay": cur.self_pay if cur else 0,
        "eta": eta,
    }


def get_order_or_404(db: Session, order_id_or_no: str) -> models.WorkOrder:
    if order_id_or_no.isdigit():
        order = db.get(models.WorkOrder, int(order_id_or_no))
        if order:
            return order
    order = (
        db.query(models.WorkOrder)
        .filter(models.WorkOrder.order_no == order_id_or_no)
        .one_or_none()
    )
    if order is None:
        raise HTTPException(404, "工单不存在")
    return order


# ---------------------------------------------------------------- 工单

@app.post("/api/orders", response_model=schemas.OrderOut, tags=["工单"])
def create_order(payload: schemas.OrderCreate, db: Session = Depends(get_db)):
    today = datetime.utcnow().strftime("%Y%m%d")
    count_today = (
        db.query(models.WorkOrder)
        .filter(models.WorkOrder.order_no.like(f"WO{today}%"))
        .count()
    )
    order = models.WorkOrder(
        order_no=f"WO{today}{count_today + 1:03d}",
        **payload.model_dump(),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.get("/api/orders", response_model=List[schemas.OrderOut], tags=["工单"])
def list_orders(status: Optional[str] = None, phone: Optional[str] = None,
                plate: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.WorkOrder)
    if status:
        q = q.filter(models.WorkOrder.status == status)
    if phone:
        q = q.filter(models.WorkOrder.customer_phone.contains(phone))
    if plate:
        q = q.filter(models.WorkOrder.plate_no.contains(plate))
    return [serialize_order(o) for o in q.order_by(models.WorkOrder.id.desc()).all()]


@app.get("/api/orders/{order_id_or_no}", response_model=schemas.OrderOut, tags=["工单"])
def get_order(order_id_or_no: str, db: Session = Depends(get_db)):
    return serialize_order(get_order_or_404(db, order_id_or_no))


# ---------------------------------------------------------------- 报价与授权

@app.post("/api/orders/{order_id_or_no}/quotes", response_model=schemas.OrderOut, tags=["报价"])
def add_quote(order_id_or_no: str, payload: schemas.QuoteIn, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.create_quote(db, order, payload)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/convert-self-pay",
          response_model=schemas.OrderOut, tags=["报价"])
def convert_self_pay(order_id_or_no: str, payload: schemas.QuoteIn, db: Session = Depends(get_db)):
    """保险拒赔 → 生成自费新报价（原报价保留），等待车主重新确认授权。"""
    order = get_order_or_404(db, order_id_or_no)
    services.convert_self_pay(db, order, payload)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/quotes/{version}/confirm",
          response_model=schemas.OrderOut, tags=["报价"])
def customer_confirm(order_id_or_no: str, version: int, payload: schemas.CustomerConfirmIn,
                     db: Session = Depends(get_db)):
    """车主确认方案；初次/改价/施工变更均须本人授权语句。"""
    order = get_order_or_404(db, order_id_or_no)
    services.confirm_quote(db, order, version, payload.customer_authorization)
    services._maybe_ready(order)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


# ---------------------------------------------------------------- 门店流转

@app.post("/api/orders/{order_id_or_no}/stock", response_model=schemas.OrderOut, tags=["门店"])
def confirm_stock(order_id_or_no: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.confirm_stock(db, order)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/schedule", response_model=schemas.OrderOut, tags=["门店"])
def schedule(order_id_or_no: str, payload: schemas.ScheduleIn, db: Session = Depends(get_db)):
    """库存 + 已确认且保险通过的方案，缺一不可。"""
    order = get_order_or_404(db, order_id_or_no)
    services.schedule_install(db, order)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


# ---------------------------------------------------------------- 施工

@app.post("/api/orders/{order_id_or_no}/install/start", response_model=schemas.OrderOut,
          tags=["施工"])
def install_start(order_id_or_no: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.start_install(db, order)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/install/pause", response_model=schemas.OrderOut,
          tags=["施工"])
def install_pause(order_id_or_no: str, payload: schemas.PauseIn, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.pause_install(db, order, payload.reason)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/install/resume", response_model=schemas.OrderOut,
          tags=["施工"])
def install_resume(order_id_or_no: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.resume_install(db, order)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/install/finish", response_model=schemas.OrderOut,
          tags=["施工"])
def install_finish(order_id_or_no: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.finish_install(db, order)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/photos", response_model=schemas.OrderOut, tags=["施工"])
def upload_photo(order_id_or_no: str, file: UploadFile = File(...),
                 stage: str = Form("install"), db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    if order.status in (models.ST_CREATED, models.ST_DELIVERED):
        raise HTTPException(409, "当前状态不能上传安装照片")
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise HTTPException(422, "仅支持 jpg/png/webp/gif 图片")
    filename = f"{order.order_no}_{uuid.uuid4().hex[:10]}{ext}"
    target = os.path.join(UPLOAD_DIR, filename)
    with open(target, "wb") as f:
        shutil.copyfileobj(file.file, f)
    db.add(models.InstallationPhoto(
        order_id=order.id, filename=filename,
        original_name=file.filename or filename, stage=stage,
    ))
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/cure", response_model=schemas.OrderOut, tags=["施工"])
def register_cure(order_id_or_no: str, payload: schemas.CureIn, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.register_cure(db, order, payload.cure_minutes)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


@app.post("/api/orders/{order_id_or_no}/inspect", response_model=schemas.OrderOut, tags=["施工"])
def inspect(order_id_or_no: str, payload: schemas.InspectIn, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    services.inspect(db, order, payload.passed, payload.note)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


# ---------------------------------------------------------------- 交车

@app.get("/api/orders/{order_id_or_no}/delivery-gate",
         response_model=schemas.DeliveryGate, tags=["交车"])
def gate(order_id_or_no: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id_or_no)
    return services.delivery_gate(order)


@app.post("/api/orders/{order_id_or_no}/deliver", response_model=schemas.OrderOut, tags=["交车"])
def deliver(order_id_or_no: str, payload: schemas.DeliverIn, db: Session = Depends(get_db)):
    """服务端再次强校验：未固化/验收未过/缺照片/授权无效 → 409 拒绝交车。"""
    order = get_order_or_404(db, order_id_or_no)
    services.deliver(db, order, payload.operator)
    db.commit()
    db.refresh(order)
    return serialize_order(order)


# ---------------------------------------------------------------- 模拟保险接口

@app.post("/api/sim/insurance/receipt", response_model=schemas.OrderOut,
          tags=["模拟保险"])
def sim_receipt(payload: schemas.ReceiptSimIn, db: Session = Depends(get_db)):
    """
    模拟保险公司按报案号推送理赔回执。
    issued_minutes_ago 可把签发时间提前，模拟“回执晚于车主方案变更到达”：
    迟到回执只留痕，不覆盖车主已确认的方案。
    """
    order = (
        db.query(models.WorkOrder)
        .filter(models.WorkOrder.claim_no == payload.claim_no)
        .one_or_none()
    )
    if order is None:
        raise HTTPException(404, f"报案号 {payload.claim_no} 无对应工单")
    if payload.decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision 仅支持 approved / rejected")
    issued_at = datetime.utcnow() - timedelta(minutes=payload.issued_minutes_ago)
    services.ingest_receipt(
        db, order, payload.decision, payload.cover_amount,
        payload.reason, issued_at,
    )
    db.commit()
    db.refresh(order)
    return serialize_order(order)


# ---------------------------------------------------------------- 上传文件

@app.get("/uploads/{filename}", include_in_schema=False)
def get_upload(filename: str):
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path)


# ---------------------------------------------------------------- 前端

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
