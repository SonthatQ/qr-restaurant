from __future__ import annotations

import json
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Payment
from app.services.payment_verify import verify_signature, idempotent_record_event, mark_paid_if_match
from app.services.ws_manager import ws_manager

router = APIRouter()


@router.post("/payments/scb/callback")
async def webhook_scb_callback(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()

    ok, reason = await verify_signature(request, raw)
    if not ok:
        raise HTTPException(status_code=401, detail=f"Webhook verify failed: {reason}")

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        payload = {}

    # Find payment: prefer transactionId -> scb_txn_ref, otherwise ref1 -> biller_ref
    txn_id = str(payload.get("transactionId") or payload.get("transaction_id") or "")
    ref1 = str(payload.get("billPaymentRef1") or payload.get("ref1") or "")

    payment = None
    if txn_id:
        payment = db.query(Payment).filter(Payment.scb_txn_ref == txn_id).first()
    if not payment and ref1:
        payment = db.query(Payment).filter(Payment.biller_ref == ref1).first()

    if not payment:
        # Still store as "unmatched" would require separate table; for now reject with 404
        raise HTTPException(status_code=404, detail="Payment not found for callback")

    inserted = idempotent_record_event(db, payment, payload, event_type="scb_callback")

    updated = False
    if inserted:
        updated = mark_paid_if_match(db, payment, payload)

    # Broadcast to staff + the table group
    table_token = payment.order.table.token
    await ws_manager.broadcast_multi(
        groups=["staff", f"table:{table_token}"],
        message={
            "type": "payment_update",
            "order_id": payment.order_id,
            "payment_status": payment.status,
        },
    )

    return {"ok": True, "inserted": inserted, "updated": updated}
