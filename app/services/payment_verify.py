from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from fastapi import Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Payment, PaymentEvent
from app.settings import settings


def _hmac_sha256_hex(secret: str, msg: str) -> str:
    return hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()


async def verify_signature(request: Request, raw_body: bytes) -> Tuple[bool, str]:
    """
    Verify webhook signature (configurable).
    Many gateways use: signature = HMAC(secret, timestamp + "." + body)
    You MUST adapt this to SCB spec for your product. We keep it strict but configurable.
    """
    secret = settings.SCB_WEBHOOK_SECRET
    sig_header = settings.SCB_WEBHOOK_SIGNATURE_HEADER.lower()
    ts_header = settings.SCB_WEBHOOK_TIMESTAMP_HEADER.lower()

    if not secret:
        # If secret is not configured, do not accept silently in production
        if settings.APP_ENV == "production":
            return False, "Webhook secret not configured"
        return True, "No secret (dev mode)"

    headers = {k.lower(): v for k, v in request.headers.items()}
    signature = headers.get(sig_header, "")
    ts = headers.get(ts_header, "")

    if not signature:
        return False, f"Missing signature header: {settings.SCB_WEBHOOK_SIGNATURE_HEADER}"
    if not ts:
        return False, f"Missing timestamp header: {settings.SCB_WEBHOOK_TIMESTAMP_HEADER}"

    signing_payload = f"{ts}.{raw_body.decode('utf-8')}"
    expected = _hmac_sha256_hex(secret, signing_payload)

    ok = hmac.compare_digest(signature, expected)
    return ok, "OK" if ok else "Invalid signature"


def extract_payment_keys(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalize keys from SCB callback payload.
    From SCB Open API payment confirmation example: transactionId, amount, billPaymentRef1, billPaymentRef3 ...
    """
    txn_id = str(payload.get("transactionId") or payload.get("transaction_id") or "")
    amount = str(payload.get("amount") or "")
    ref1 = str(payload.get("billPaymentRef1") or payload.get("ref1") or "")
    ref2 = str(payload.get("billPaymentRef2") or payload.get("ref2") or "")
    ref3 = str(payload.get("billPaymentRef3") or payload.get("ref3") or "")
    return {"txn_id": txn_id, "amount": amount, "ref1": ref1, "ref2": ref2, "ref3": ref3}


def compute_unique_key(payload: Dict[str, Any]) -> str:
    keys = extract_payment_keys(payload)
    base = keys["txn_id"] or f'{keys["ref1"]}-{keys["amount"]}-{keys["ref3"]}'
    if not base.strip():
        base = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def idempotent_record_event(
    db: Session,
    payment: Payment,
    payload: Dict[str, Any],
    event_type: str = "scb_callback",
    unique_key: Optional[str] = None,
) -> bool:
    """
    Store raw callback into PaymentEvent; returns True if new event inserted, False if duplicate.
    """
    uk = unique_key or compute_unique_key(payload)
    ev = PaymentEvent(
        payment_id=payment.id,
        received_at=datetime.utcnow(),
        event_type=event_type,
        unique_key=uk,
        raw_payload=json.dumps(payload, ensure_ascii=False),
    )
    db.add(ev)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def mark_paid_if_match(db: Session, payment: Payment, payload: Dict[str, Any]) -> bool:
    """
    Update payment status to paid (idempotent).
    """
    keys = extract_payment_keys(payload)
    txn_id = keys["txn_id"]
    amount = keys["amount"]
    ref1 = keys["ref1"]

    # Basic matching rules:
    # - If SCB provides txn id, store it.
    # - If billPaymentRef1 exists, compare to payment.biller_ref.
    # - Amount must match (as string/float tolerant).
    if txn_id and not payment.scb_txn_ref:
        payment.scb_txn_ref = txn_id

    if ref1 and payment.biller_ref and ref1 != payment.biller_ref:
        return False

    try:
        amt = float(amount) if amount else None
    except Exception:
        amt = None

    if amt is not None:
        try:
            expected = float(payment.amount)
        except Exception:
            expected = None
        if expected is not None and abs(amt - expected) > 0.01:
            return False

    if payment.status != "paid":
        payment.status = "paid"
        payment.paid_at = datetime.utcnow()
        db.add(payment)
        db.commit()
        db.refresh(payment)
        return True

    return False
