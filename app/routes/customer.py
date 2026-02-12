from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models import Table, MenuItem, Order, OrderItem
from app.services.scb_qr import create_scb_qr, poll_payment_status
from app.services.ws_manager import ws_manager

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ----------------------------
# Jinja filter: Bangkok time (UTC naive -> +7)
# ----------------------------
def to_bkk(dt: datetime | None) -> str:
    if not dt:
        return ""
    # ระบบคุณบันทึก utcnow() แบบ naive → บวก 7 ชั่วโมงตรง ๆ
    return (dt + timedelta(hours=7)).strftime("%d/%m/%Y %H:%M")


templates.env.filters["bkk"] = to_bkk


def _make_invoice_ref(table_token: str) -> str:
    ts = int(datetime.utcnow().timestamp())
    rnd = secrets.token_hex(3)
    return f"T{table_token[:6].upper()}-{ts}-{rnd}".upper()


# ----------------------------
# Customer: menu page
# ----------------------------
@router.get("/t/{table_token}", response_class=HTMLResponse)
def table_menu(request: Request, table_token: str, db: Session = Depends(get_db)):
    table = db.query(Table).filter(Table.token == table_token, Table.is_active == 1).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    items = (
        db.query(MenuItem)
        .filter(MenuItem.is_available == 1)
        .order_by(MenuItem.category, MenuItem.name)
        .all()
    )
    categories = sorted({i.category for i in items}) if items else []

    # ✅ เอาแค่ออเดอร์ล่าสุด (เพื่อไม่รกหน้าเมนู)
    latest_order = (
        db.query(Order)
        .options(joinedload(Order.payment))
        .filter(Order.table_id == table.id)
        .order_by(Order.id.desc())
        .first()
    )
    orders = [latest_order] if latest_order else []

    return templates.TemplateResponse(
        "customer_menu.html",
        {
            "request": request,
            "table": table,
            "items": items,
            "categories": categories,
            "orders": orders,
        },
    )


# ----------------------------
# Customer: reset session
# ----------------------------
CID_COOKIE = "cid"
CID_MAX_AGE = 60 * 60 * 24 * 30


@router.get("/t/{table_token}/reset", response_class=HTMLResponse)
def reset_customer_session(request: Request, table_token: str):
    """
    ล้าง session ของลูกค้า (cid cookie) + ล้าง cart ใน localStorage แล้วเด้งกลับหน้าเมนู
    """
    html = f"""
    <html><head><meta charset="utf-8"></head>
    <body>
      <script>
        try {{
          const tableToken = "{table_token}";
          const prefixes = [
            `cart:${{tableToken}}`,
            `cart:${{tableToken}}:`,
            `cart_${{tableToken}}`,
            `cart_${{tableToken}}_`,
          ];
          const keys = [];
          for (let i = 0; i < localStorage.length; i++) {{
            const k = localStorage.key(i);
            if (!k) continue;
            if (prefixes.some(p => k.startsWith(p))) keys.push(k);
          }}
          keys.forEach(k => localStorage.removeItem(k));
        }} catch (e) {{}}

        window.location.href = "/t/{table_token}";
      </script>
    </body></html>
    """
    resp = HTMLResponse(html)
    resp.delete_cookie(CID_COOKIE)
    return resp


# ----------------------------
# Customer: checkout
# ----------------------------
@router.get("/t/{table_token}/checkout", response_class=HTMLResponse)
def checkout_page(request: Request, table_token: str, db: Session = Depends(get_db)):
    table = db.query(Table).filter(Table.token == table_token, Table.is_active == 1).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    return templates.TemplateResponse("customer_checkout.html", {"request": request, "table": table})


# ----------------------------
# Create order
# ----------------------------
@router.post("/api/t/{table_token}/orders")
async def create_order(request: Request, table_token: str, db: Session = Depends(get_db)):
    table = db.query(Table).filter(Table.token == table_token, Table.is_active == 1).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    body = await request.json()
    cart = body.get("cart") or []
    note = (body.get("note") or "").strip()

    if not cart:
        raise HTTPException(status_code=400, detail="Cart is empty")

    invoice_ref = _make_invoice_ref(table_token)
    order = Order(table_id=table.id, note=note, status="created", invoice_ref=invoice_ref, total_amount=0)
    db.add(order)
    db.commit()
    db.refresh(order)

    total = 0.0
    for line in cart:
        mid = int(line.get("menu_item_id", 0))
        qty = int(line.get("qty", 1))
        inote = (line.get("note") or "").strip()
        if qty <= 0:
            continue

        item = db.get(MenuItem, mid)
        if not item or item.is_available != 1:
            continue

        unit = float(item.price)
        line_total = unit * qty
        total += line_total

        db.add(
            OrderItem(
                order_id=order.id,
                menu_item_id=item.id,
                qty=qty,
                unit_price=unit,
                line_total=line_total,
                note=inote,
            )
        )

    if total <= 0:
        db.delete(order)
        db.commit()
        raise HTTPException(status_code=400, detail="No valid items in cart")

    order.total_amount = total
    db.add(order)
    db.commit()
    db.refresh(order)

    # ✅ Create SCB QR immediately
    qr_b64, qr_payload, scb_txn_ref = await create_scb_qr(db, order.id)

    # ✅ Staff realtime
    await ws_manager.broadcast(
        "staff",
        {
            "type": "new_order",
            "order_id": order.id,
            "table": table.name,
            "total": float(order.total_amount),
            "invoice_ref": order.invoice_ref,
            "created_at": order.created_at.isoformat(),
        },
    )

    # ✅ Table realtime
    await ws_manager.broadcast("staff", {"type": "order_created", "order_id": order.id})
    await ws_manager.broadcast(f"table:{table.token}", {"type": "order_created", "order_id": order.id})

    return {
        "ok": True,
        "order_id": order.id,
        "invoice_ref": order.invoice_ref,
        "pay_url": f"/t/{table_token}/pay/{order.id}",
        "status_url": f"/t/{table_token}/status",
        "qr_ready": True,
        "scb_txn_ref": scb_txn_ref,
        "qr_payload": qr_payload,
        "qr_image_base64": qr_b64,
    }


# ----------------------------
# Pay page
# ----------------------------
@router.get("/t/{table_token}/pay/{order_id}", response_class=HTMLResponse)
def pay_page(request: Request, table_token: str, order_id: int, db: Session = Depends(get_db)):
    table = db.query(Table).filter(Table.token == table_token, Table.is_active == 1).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    order = (
        db.query(Order)
        .options(joinedload(Order.payment), joinedload(Order.items).joinedload(OrderItem.menu_item))
        .filter(Order.id == order_id)
        .first()
    )
    if not order or order.table_id != table.id:
        raise HTTPException(status_code=404, detail="Order not found")

    if not order.payment:
        raise HTTPException(status_code=400, detail="Payment not initialized")

    return templates.TemplateResponse(
        "customer_pay.html",
        {"request": request, "table": table, "order": order, "payment": order.payment},
    )


# ----------------------------
# Status page
# ----------------------------
@router.get("/t/{table_token}/status", response_class=HTMLResponse)
def table_status_page(request: Request, table_token: str, db: Session = Depends(get_db)):
    table = db.query(Table).filter(Table.token == table_token, Table.is_active == 1).first()
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    orders = (
        db.query(Order)
        .options(joinedload(Order.payment))
        .filter(Order.table_id == table.id)
        .order_by(Order.id.desc())
        .limit(20)
        .all()
    )

    return templates.TemplateResponse(
        "customer_status.html",
        {"request": request, "table": table, "orders": orders},
    )


# ----------------------------
# API: get order
# ----------------------------
@router.get("/api/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return {
        "order_id": order.id,
        "invoice_ref": order.invoice_ref,
        "total": float(order.total_amount),
        "status": order.status,
        "payment_status": order.payment.status if order.payment else "unpaid",
    }


# ----------------------------
# API: poll payment
# ----------------------------
@router.post("/api/orders/{order_id}/poll")
async def poll_order_payment(order_id: int, db: Session = Depends(get_db)):
    status = await poll_payment_status(db, order_id)

    order = (
        db.query(Order)
        .options(joinedload(Order.payment), joinedload(Order.table))
        .filter(Order.id == order_id)
        .first()
    )
    if order and order.payment and order.table and order.table.token:
        table_token = order.table.token
        await ws_manager.broadcast_multi(
            ["staff", f"table:{table_token}"],
            {"type": "payment_update", "order_id": order.id, "payment_status": order.payment.status},
        )

    return {"ok": True, "payment_status": status}

from fastapi import HTTPException
from sqlalchemy.orm import joinedload

@router.get("/api/orders/{order_id}/status")
def get_order_status(order_id: int, db: Session = Depends(get_db)):
    order = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.menu_item),
            joinedload(Order.payment),
        )
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "ok": True,
        "order_id": order.id,
        "invoice_ref": order.invoice_ref,
        "total": float(order.total_amount or 0),
        "note": order.note or "",
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "payment_status": order.payment.status if order.payment else "unpaid",
        "items": [
            {
                "name": it.menu_item.name if it.menu_item else "",
                "qty": int(it.qty or 0),
                "note": it.note or "",
                "line_total": float(it.line_total or 0),
            }
            for it in (order.items or [])
        ],
    }


# ----------------------------
# WebSocket: table
# ----------------------------
@router.websocket("/ws/table/{table_token}")
async def ws_table(ws: WebSocket, table_token: str, db: Session = Depends(get_db)):
    table = db.query(Table).filter(Table.token == table_token, Table.is_active == 1).first()
    if not table:
        await ws.close(code=4404)
        return

    group = f"table:{table_token}"
    await ws_manager.connect(group, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(group, ws)
@router.get("/api/orders/{order_id}/status")
def get_order_status(order_id: int, db: Session = Depends(get_db)):
    order = (
        db.query(Order)
        .options(joinedload(Order.payment), joinedload(Order.items).joinedload(OrderItem.menu_item))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "ok": True,
        "order_id": order.id,
        "payment_status": order.payment.status if order.payment else "unpaid",
        "invoice_ref": order.invoice_ref,
        "total": float(order.total_amount),
        "items": [
            {
                "name": it.menu_item.name if it.menu_item else "",
                "qty": int(it.qty),
                "line_total": float(it.line_total),
                "note": it.note or "",
            }
            for it in (order.items or [])
        ],
        "note": order.note or "",
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }
