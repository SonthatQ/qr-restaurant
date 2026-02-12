from __future__ import annotations

import io
import secrets
import os
from pathlib import Path
# from fastapi import UploadFile, File
from fastapi import UploadFile, File, Form
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MenuItem, Table
from app.settings import settings

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()
security = HTTPBasic()
UPLOAD_DIR = Path("app/static/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _require_admin(creds: HTTPBasicCredentials = Depends(security)) -> None:
    if creds.username != settings.ADMIN_USER or creds.password != settings.ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})


def _new_table_token() -> str:
    return secrets.token_urlsafe(16)


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, _: None = Depends(_require_admin)):
    return templates.TemplateResponse("admin_dashboard.html", {"request": request})


# ---- Menu CRUD ----
@router.get("/admin/menu", response_class=HTMLResponse)
def admin_menu_list(request: Request, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    items = db.query(MenuItem).order_by(MenuItem.category, MenuItem.name).all()
    return templates.TemplateResponse("admin_menu_list.html", {"request": request, "items": items})


@router.get("/admin/menu/new", response_class=HTMLResponse)
def admin_menu_new(request: Request, _: None = Depends(_require_admin)):
    return templates.TemplateResponse("admin_menu_edit.html", {"request": request, "item": None})


@router.get("/admin/menu/{item_id}", response_class=HTMLResponse)
def admin_menu_edit(request: Request, item_id: int, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    item = db.get(MenuItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Menu item not found")
    return templates.TemplateResponse("admin_menu_edit.html", {"request": request, "item": item})




@router.post("/admin/menu/save")
async def admin_menu_save(
    db: Session = Depends(get_db),
    _: None = Depends(_require_admin),

    item_id: Optional[int] = Form(default=None),
    name: str = Form(...),
    description: str = Form(default=""),
    category: str = Form(default="General"),
    price: float = Form(...),
    image_url: str = Form(default=""),
    is_available: int = Form(default=1),

    image_file: UploadFile | None = File(default=None),  # ✅ ต้องมี
):
    ...

    if item_id:
        item = db.get(MenuItem, int(item_id))
        if not item:
            raise HTTPException(status_code=404, detail="Menu item not found")
    else:
        item = MenuItem(name=name, price=price)
        db.add(item)

    # ถ้ามีอัปโหลดไฟล์ -> เซฟไฟล์ แล้ว override image_url ให้เป็น path ใน static
    if image_file and image_file.filename:
        ext = Path(image_file.filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            raise HTTPException(status_code=400, detail="File type not allowed")

        safe_name = secrets.token_hex(12) + ext
        save_path = UPLOAD_DIR / safe_name

        content = await image_file.read()
        save_path.write_bytes(content)

        image_url = f"/static/uploads/{safe_name}"

    item.name = name
    item.description = description
    item.category = category
    item.price = price
    item.image_url = image_url
    item.is_available = 1 if int(is_available) == 1 else 0

    db.commit()
    return RedirectResponse(url="/admin/menu", status_code=303)


@router.post("/admin/menu/{item_id}/delete")
def admin_menu_delete(item_id: int, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    item = db.get(MenuItem, item_id)
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse(url="/admin/menu", status_code=303)


# ---- Table CRUD + QR download ----
@router.get("/admin/tables", response_class=HTMLResponse)
def admin_tables_list(request: Request, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    tables = db.query(Table).order_by(Table.id).all()
    return templates.TemplateResponse("admin_tables_list.html", {"request": request, "tables": tables})


@router.get("/admin/tables/new", response_class=HTMLResponse)
def admin_tables_new(request: Request, _: None = Depends(_require_admin)):
    return templates.TemplateResponse("admin_tables_edit.html", {"request": request, "table": None})


@router.get("/admin/tables/{table_id}", response_class=HTMLResponse)
def admin_tables_edit(request: Request, table_id: int, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    table = db.get(Table, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")
    return templates.TemplateResponse("admin_tables_edit.html", {"request": request, "table": table})


@router.post("/admin/tables/save")
def admin_tables_save(
    db: Session = Depends(get_db),
    _: None = Depends(_require_admin),
    table_id: Optional[int] = Form(default=None),
    name: str = Form(...),
    is_active: int = Form(default=1),
):
    if table_id:
        table = db.get(Table, int(table_id))
        if not table:
            raise HTTPException(status_code=404, detail="Table not found")
    else:
        table = Table(name=name, token=_new_table_token(), is_active=1)
        db.add(table)

    table.name = name
    table.is_active = 1 if int(is_active) == 1 else 0
    db.commit()
    return RedirectResponse(url="/admin/tables", status_code=303)


@router.post("/admin/tables/{table_id}/delete")
def admin_tables_delete(table_id: int, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    table = db.get(Table, table_id)
    if table:
        db.delete(table)
        db.commit()
    return RedirectResponse(url="/admin/tables", status_code=303)


@router.get("/admin/tables/{table_id}/qr.png")
def admin_table_qr(table_id: int, db: Session = Depends(get_db), _: None = Depends(_require_admin)):
    table = db.get(Table, table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Table not found")

    import qrcode
    from PIL import Image
    url = f"{settings.APP_BASE_URL}/t/{table.token}"
    img: Image.Image = qrcode.make(url)
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)

    return StreamingResponse(bio, media_type="image/png")

