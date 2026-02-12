from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Tuple

from sqlalchemy.orm import Session

from app.models import Order, Payment
from app.services.scb_client import scb_client
from app.settings import settings


def _digits_only(s: str) -> str:
    return re.sub(r"\D+", "", s)


async def create_scb_qr(db: Session, order_id: int) -> Tuple[str, str, str]:
    """
    create_scb_qr(order_id) -> (qr_image_base64, qr_payload, scb_txn_ref)
    - Uses SCB API to create dynamic QR for the bill amount.
    - Does NOT compose ThaiQR payload by ourselves in production.
    """
    order = db.get(Order, order_id)
    if not order:
        raise ValueError("Order not found")

    if not order.payment:
        payment = Payment(
            provider="SCB",
            order_id=order.id,
            amount=float(order.total_amount),
            invoice_ref=order.invoice_ref,
            status="pending",
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
    else:
        payment = order.payment

    if payment.status == "paid" and payment.qr_image_base64:
        return payment.qr_image_base64, payment.qr_raw, payment.scb_txn_ref

    # Reference strategy:
    # - Some SCB APIs require ref1/ref2 numeric-only; use digits from invoice_ref
    # - Keep invoice_ref unique in our DB, and also store it in payment
    ref1 = _digits_only(order.invoice_ref)[:20] or str(order.id)
    ref2 = str(int(datetime.utcnow().timestamp()))[-10:]
    ref3 = settings.SCB_REF3_PREFIX[:10] if settings.SCB_REF3_PREFIX else "SCB"

    # NOTE:
    # This payload matches SCB "deeplink/transactions" example style (v3) from SCB Open API articles.
    # If your SCB product provides a dedicated "QR create" endpoint, replace SCB_QR_CREATE_PATH and payload accordingly.
    payload = {
        "transactionType": "PURCHASE",
        "transactionSubType": ["BP"],  # bill payment
        "billPayment": {
            "paymentAmount": float(order.total_amount),
            "accountTo": settings.SCB_BILLER_ID,
            "ref1": ref1,
            "ref2": ref2,
            "ref3": ref3,
        },
        # Some SCB products allow callback_url; keep optional.
        # "callbackUrl": f"{settings.APP_BASE_URL}/t/{order.table.token}/status"
    }

    resp = await scb_client.post_json(settings.SCB_QR_CREATE_PATH, payload)

    # Normalize response
    data = resp.get("data") or resp

    scb_txn_ref = data.get("transactionId") or data.get("transactionRef") or ""
    qr_payload = data.get("qrPayload") or data.get("deeplinkUrl") or ""
    qr_b64 = data.get("qrImageBase64") or ""

    # If SCB doesn't return image, we can still render QR for display ONLY in sandbox/dev
    # but requirement says production should not compose payload => keep it opt-in
    if (not qr_b64) and qr_payload and settings.SCB_MODE == "sandbox":
        # display convenience in sandbox
        qr_b64 = scb_client._fake_qr_png_base64(qr_payload)

    payment.scb_txn_ref = scb_txn_ref
    payment.biller_ref = ref1
    payment.invoice_ref = order.invoice_ref
    payment.qr_raw = json.dumps({"request": payload, "response": resp}, ensure_ascii=False)
    payment.qr_image_base64 = qr_b64
    payment.status = "pending"

    db.add(payment)
    db.commit()
    db.refresh(payment)

    return payment.qr_image_base64, qr_payload, payment.scb_txn_ref


async def poll_payment_status(db: Session, order_id: int) -> str:
    """
    poll_payment_status(order_id) -> status string
    Fallback when webhook is not available.
    """
    order = db.get(Order, order_id)
    if not order or not order.payment:
        raise ValueError("Order/payment not found")

    p = order.payment
    if p.status == "paid":
        return "paid"
    if not p.scb_txn_ref:
        return p.status

    path = settings.SCB_PAYMENT_INQUIRY_PATH.format(scb_txn_ref=p.scb_txn_ref)
    resp = await scb_client.get_json(path)

    data = resp.get("data") or resp
    # Normalize: possible fields: paymentStatus / status / transactionStatus
    status_raw = (data.get("paymentStatus") or data.get("status") or data.get("transactionStatus") or "").upper()

    if status_raw in {"SUCCESS", "PAID", "COMPLETED"}:
        p.status = "paid"
        p.paid_at = datetime.utcnow()
        db.add(p)
        db.commit()
        db.refresh(p)
        return "paid"

    if status_raw in {"FAILED", "CANCELLED", "EXPIRED"}:
        p.status = "failed"
        db.add(p)
        db.commit()
        db.refresh(p)
        return "failed"

    return p.status
