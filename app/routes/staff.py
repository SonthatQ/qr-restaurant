# ----------------------------
# Sales report
# ----------------------------
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Order, Payment, OrderItem, ReportSnapshot
from app.services.ws_manager import ws_manager
from app.settings import settings
import os
# ----------------------------
# Router / Templates / Security  (ต้องอยู่ก่อนใช้ @router)
# ----------------------------
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
security = HTTPBasic()

# ----------------------------
# Auth  (ต้องอยู่ก่อน Depends(_require_staff))
# ----------------------------
def _require_staff(creds: HTTPBasicCredentials = Depends(security)) -> None:
    ok_staff = (
        secrets.compare_digest(creds.username, settings.STAFF_USER)
        and secrets.compare_digest(creds.password, settings.STAFF_PASS)
    )
    ok_admin = (
        secrets.compare_digest(creds.username, settings.ADMIN_USER)
        and secrets.compare_digest(creds.password, settings.ADMIN_PASS)
    )
    if not (ok_staff or ok_admin):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

# ----------------------------
# Jinja filter: Bangkok time (UTC naive -> +7)
# ----------------------------
def to_bkk(dt: datetime | None) -> str:
    if not dt:
        return ""
    return (dt + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")

templates.env.filters["bkk"] = to_bkk

# ----------------------------
# Report Snapshots (view/list/delete/clear/save)
# ----------------------------
@router.get(
    "/staff/report/snapshots",
    response_class=HTMLResponse,
    dependencies=[Depends(_require_staff)],
)
def report_snapshots(request: Request, db: Session = Depends(get_db)):
    snaps = db.query(ReportSnapshot).order_by(ReportSnapshot.id.desc()).limit(200).all()
    return templates.TemplateResponse(
        "staff_report_snapshots.html",
        {"request": request, "snaps": snaps},
    )

@router.get(
    "/staff/report/snapshots/{snapshot_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(_require_staff)],
)
def report_snapshot_detail(request: Request, snapshot_id: int, db: Session = Depends(get_db)):
    snap = db.query(ReportSnapshot).filter(ReportSnapshot.id == snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    ids = [int(x) for x in (snap.order_ids_csv or "").split(",") if x.strip().isdigit()]
    orders = []
    if ids:
        orders = (
            db.query(Order)
            .options(joinedload(Order.table), joinedload(Order.payment))
            .filter(Order.id.in_(ids))
            .order_by(Order.id.desc())
            .all()
        )

    return templates.TemplateResponse(
        "staff_report_snapshot_detail.html",
        {"request": request, "snap": snap, "orders": orders},
    )

@router.post(
    "/staff/report/snapshots/{snapshot_id}/delete",
    dependencies=[Depends(_require_staff)],
)
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    snap = db.query(ReportSnapshot).filter(ReportSnapshot.id == snapshot_id).first()
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    db.delete(snap)
    db.commit()
    return {"ok": True}

@router.post(
    "/staff/report/snapshots/clear",
    dependencies=[Depends(_require_staff)],
)
def clear_all_snapshots(db: Session = Depends(get_db)):
    db.query(ReportSnapshot).delete()
    db.commit()
    return {"ok": True}

@router.post(
    "/staff/report/save",
    dependencies=[Depends(_require_staff)],
)
def save_report_snapshot(
    request: Request,
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    hour_from: str | None = None,
    hour_to: str | None = None,
    note: str | None = None,
):
    q = (
        db.query(Order)
        .join(Payment, Payment.order_id == Order.id)
        .filter(Payment.status == "paid")
    )

    if date_from and date_to:
        start = f"{date_from} 00:00:00"
        end = f"{date_to} 23:59:59"
        if hour_from:
            start = f"{date_from} {hour_from}:00"
        if hour_to:
            end = f"{date_to} {hour_to}:59"
        q = q.filter(Order.created_at >= start).filter(Order.created_at <= end)

    orders = q.order_by(Order.id.desc()).all()
    total_amount = sum(float(o.total_amount) for o in orders)
    total_count = len(orders)
    order_ids_csv = ",".join(str(o.id) for o in orders)

    snap = ReportSnapshot(
        date_from=date_from,
        date_to=date_to,
        hour_from=hour_from,
        hour_to=hour_to,
        total_amount=total_amount,
        total_count=total_count,
        order_ids_csv=order_ids_csv,
        note=note,
    )
    db.add(snap)
    db.commit()

    return {"ok": True, "snapshot_id": snap.id}

# ----------------------------
# Staff Dashboard
# ----------------------------
@router.get("/staff", response_class=HTMLResponse, dependencies=[Depends(_require_staff)])
def staff_dashboard(request: Request, db: Session = Depends(get_db)):
    orders = (
        db.query(Order)
        .options(
            joinedload(Order.table),
            joinedload(Order.payment),
            joinedload(Order.items).joinedload(OrderItem.menu_item),
        )
        .order_by(Order.id.desc())
        .limit(50)
        .all()
    )

    return templates.TemplateResponse(
        "staff_dashboard.html",
        {"request": request, "orders": orders},
    )

# ----------------------------
# Order detail
# ----------------------------
@router.get(
    "/staff/orders/{order_id}",
    response_class=HTMLResponse,
    dependencies=[Depends(_require_staff)],
)
def staff_order_detail(request: Request, order_id: int, db: Session = Depends(get_db)):
    order = (
        db.query(Order)
        .options(
            joinedload(Order.table),
            joinedload(Order.payment),
            joinedload(Order.items).joinedload(OrderItem.menu_item),
        )
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return templates.TemplateResponse(
        "staff_order_detail.html",
        {"request": request, "order": order},
    )

# ----------------------------
# Update order status
# ----------------------------
@router.post("/staff/orders/{order_id}/status", dependencies=[Depends(_require_staff)])
async def update_order_status(order_id: int, status: str, db: Session = Depends(get_db)):
    order = (
        db.query(Order)
        .options(joinedload(Order.table))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    allowed = {"new", "cooking", "served", "cancelled"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status")

    order.order_status = status
    now = datetime.utcnow()

    if status == "cooking":
        order.accepted_at = now
    elif status == "served":
        order.served_at = now
    elif status == "cancelled":
        order.cancelled_at = now

    db.commit()

    payload = {"type": "order_status", "order_id": order.id, "order_status": order.order_status}

    await ws_manager.broadcast("staff", payload)

    if getattr(order, "table", None) is not None and getattr(order.table, "token", None):
        await ws_manager.broadcast(f"table:{order.table.token}", payload)

    return {"ok": True, "order_id": order.id, "order_status": order.order_status}

# ----------------------------
# Confirm payment
# ----------------------------
@router.post("/staff/orders/{order_id}/notify_payment", dependencies=[Depends(_require_staff)])
async def notify_payment_received(order_id: int, db: Session = Depends(get_db)):
    order = (
        db.query(Order)
        .options(joinedload(Order.table), joinedload(Order.payment))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    payment = getattr(order, "payment", None)
    if not payment:
        raise HTTPException(status_code=400, detail="Order has no payment record")

    if payment.status != "paid":
        payment.status = "paid"
        payment.paid_at = datetime.utcnow()
        db.commit()
    else:
        db.commit()

    payload = {
        "type": "payment_update",
        "order_id": order.id,
        "payment_status": payment.status,
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
    }

    await ws_manager.broadcast("staff", payload)

    token = getattr(getattr(order, "table", None), "token", None)
    if token:
        await ws_manager.broadcast(f"table:{token}", payload)

    return {"ok": True, "order_id": order.id, "payment_status": payment.status}

# ----------------------------
# Sales report
# ----------------------------
@router.get("/staff/report", response_class=HTMLResponse, dependencies=[Depends(_require_staff)])
def staff_report(
    request: Request,
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    hour_from: str | None = None,
    hour_to: str | None = None,
):
    q = (
        db.query(Order)
        .join(Payment, Payment.order_id == Order.id)
        .filter(Payment.status == "paid")
    )

    if date_from and date_to:
        start = f"{date_from} 00:00:00"
        end = f"{date_to} 23:59:59"
        if hour_from:
            start = f"{date_from} {hour_from}:00"
        if hour_to:
            end = f"{date_to} {hour_to}:59"
        q = q.filter(Order.created_at >= start).filter(Order.created_at <= end)

    orders = q.order_by(Order.id.desc()).all()

    total_amount = sum(float(o.total_amount) for o in orders)
    total_count = len(orders)

    return templates.TemplateResponse(
        "staff_report.html",
        {
            "request": request,
            "orders": orders,
            "total_amount": total_amount,
            "total_count": total_count,
            "date_from": date_from,
            "date_to": date_to,
            "hour_from": hour_from,
            "hour_to": hour_to,
            "render_commit": (os.getenv("RENDER_GIT_COMMIT") or "")[:7],
        },
    )