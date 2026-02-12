from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Table(Base):
    __tablename__ = "tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1)

    orders: Mapped[list["Order"]] = relationship(
        "Order",
        back_populates="table",
        cascade="all, delete-orphan",
    )


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(80), default="General", index=True)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    is_available: Mapped[int] = mapped_column(Integer, default=1)

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="menu_item",
        cascade="all, delete-orphan",
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    table_id: Mapped[int] = mapped_column(
        ForeignKey("tables.id"),
        nullable=False,
        index=True,
    )

    # ✅ แยกออเดอร์ราย “user/อุปกรณ์” (เอาไว้กรองโชว์เฉพาะคน)
    customer_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    note: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(
        String(20),
        default="created",
        index=True,
    )  # created|accepted|done|cancelled (ตามที่คุณใช้)

    order_status: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
    )  # new|cooking|served|cancelled (ของ staff)

    total_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    currency: Mapped[str] = mapped_column(String(10), default="THB")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    served_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    invoice_ref: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    table: Mapped["Table"] = relationship("Table", back_populates="orders")

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
    )

    payment: Mapped[Optional["Payment"]] = relationship(
        "Payment",
        back_populates="order",
        uselist=False,
        cascade="all, delete-orphan",
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"),
        nullable=False,
        index=True,
    )

    menu_item_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id"),
        nullable=False,
        index=True,
    )

    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    note: Mapped[str] = mapped_column(String(300), default="")

    order: Mapped["Order"] = relationship("Order", back_populates="items")
    menu_item: Mapped["MenuItem"] = relationship("MenuItem", back_populates="items")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(20), default="SCB", index=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id"),
        unique=True,
        nullable=False,
        index=True,
    )

    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    scb_txn_ref: Mapped[str] = mapped_column(String(120), default="", index=True)
    biller_ref: Mapped[str] = mapped_column(String(120), default="")
    invoice_ref: Mapped[str] = mapped_column(String(120), default="", index=True)

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
    )  # unpaid|pending|paid|failed

    qr_raw: Mapped[str] = mapped_column(Text, default="")
    qr_image_base64: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="payment")

    events: Mapped[list["PaymentEvent"]] = relationship(
        "PaymentEvent",
        back_populates="payment",
        cascade="all, delete-orphan",
    )


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (
        UniqueConstraint("unique_key", name="uq_payment_events_unique_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id"),
        nullable=False,
        index=True,
    )

    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(60), default="callback")

    unique_key: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_payload: Mapped[str] = mapped_column(Text, default="")

    payment: Mapped["Payment"] = relationship("Payment", back_populates="events")
