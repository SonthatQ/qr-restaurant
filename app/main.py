from __future__ import annotations
from app.services.ws_manager import ws_manager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine, SessionLocal
from app.models import Table, MenuItem
from app.routes.customer import router as customer_router
from app.routes.staff import router as staff_router
from app.routes.admin import router as admin_router
from app.routes.scb_webhook import router as scb_router
app = FastAPI(title="QR Table Ordering + SCB PromptPay QR", version="1.0.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(customer_router)
app.include_router(staff_router)
app.include_router(admin_router)
app.include_router(scb_router)

from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws/staff")
async def ws_staff(ws: WebSocket):
    group = "staff"
    await ws_manager.connect(group, ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(group, ws)

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    seed_data()


def seed_data():
    db = SessionLocal()
    try:
        # Seed tables
        if db.query(Table).count() == 0:
            db.add_all(
                [
                    Table(name="Table 1", token="table1token-demo-123456", is_active=1),
                    Table(name="Table 2", token="table2token-demo-123456", is_active=1),
                ]
            )
            db.commit()

        # Seed menu
        if db.query(MenuItem).count() == 0:
            db.add_all(
                [
                    MenuItem(name="Americano", description="Coffee", category="Drinks", price=60, image_url="", is_available=1),
                    MenuItem(name="Latte", description="Milk coffee", category="Drinks", price=75, image_url="", is_available=1),
                    MenuItem(name="Fried Rice", description="Classic", category="Foods", price=89, image_url="", is_available=1),
                    MenuItem(name="Pad Thai", description="Noodles", category="Foods", price=99, image_url="", is_available=1),
                ]
            )
            db.commit()
    finally:
        db.close()
