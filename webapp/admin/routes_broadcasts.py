"""Admin uchun ommaviy xabarnomalar — Rassilka.

Endpoint'lar:
  GET    /api/admin/broadcasts                — oxirgi 30 ta
  POST   /api/admin/broadcasts                — yaratish (multipart: rasm + matn)
  GET    /api/admin/broadcasts/{id}           — bitta rassilka holati (polling)
  POST   /api/admin/broadcasts/{id}/cancel    — yuborishni to'xtatish
  GET    /api/admin/broadcasts/{id}/photo     — yuklangan rasmni ko'rish (admin preview)
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from Domain.constants import MAX_BROADCAST_BODY_LENGTH, MAX_BROADCAST_TITLE_LENGTH
from Service.broadcast_service import BroadcastInput, BroadcastService
from Service.exceptions import (
    DomainError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from webapp.admin.auth import admin_required
from webapp.auth import TelegramUser
from webapp.deps import get_broadcast_service
from webapp.pagination import Page

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/broadcasts", tags=["admin:broadcasts"])

# Loyiha media katalogi (broadcast rasmlari uchun)
_MEDIA_ROOT = Path(__file__).resolve().parent.parent.parent / "media"
_BCAST_DIR = _MEDIA_ROOT / "broadcasts"

# Ruxsat etilgan rasm formatlari va maksimal hajm
_ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_PHOTO_BYTES = 5 * 1024 * 1024  # 5 MB


# ---------------------- Schemas ----------------------

class BroadcastOut(BaseModel):
    id: int
    title: str
    body: str
    photo_url: Optional[str] = None
    status: str
    total: int
    sent: int
    failed: int
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_error: str = ""


def _iso(dt):
    return dt.isoformat() if dt is not None else None


def _photo_url(br) -> Optional[str]:
    if not getattr(br, "photo_path", None):
        return None
    # `photo_path` "media/broadcasts/xxx.jpg" — to'g'ridan-to'g'ri statik mountdan beriladi.
    return "/" + str(br.photo_path).lstrip("/")


def _to_out(br) -> BroadcastOut:
    return BroadcastOut(
        id=br.id,
        title=br.title or "",
        body=br.body,
        photo_url=_photo_url(br),
        status=br.status.value,
        total=int(br.total or 0),
        sent=int(br.sent or 0),
        failed=int(br.failed or 0),
        created_at=_iso(br.created_at),
        started_at=_iso(br.started_at),
        finished_at=_iso(br.finished_at),
        last_error=br.last_error or "",
    )


# ---------------------- Helpers ----------------------

async def _save_photo(file: UploadFile) -> str:
    """UploadFile'ni media/broadcasts/<uuid>.<ext> ga saqlab, nisbiy yo'l qaytaradi."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Faqat {', '.join(sorted(_ALLOWED_EXTS))} formatdagi rasmlar qabul qilinadi.",
        )
    _BCAST_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    abs_path = _BCAST_DIR / name
    size = 0
    with open(abs_path, "wb") as f:
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_PHOTO_BYTES:
                f.close()
                try:
                    abs_path.unlink(missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=400,
                    detail=f"Rasm juda katta ({_MAX_PHOTO_BYTES // 1024 // 1024} MB dan oshmasin).",
                )
            f.write(chunk)
    return f"media/broadcasts/{name}"


# ---------------------- Endpoints ----------------------

@router.get("", response_model=Page[BroadcastOut])
async def list_broadcasts(
    _=Depends(admin_required),
    svc: BroadcastService = Depends(get_broadcast_service),
    limit: int = Query(default=30, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[BroadcastOut]:
    items, total = await svc.list_paginated(limit=limit, offset=offset)
    return Page[BroadcastOut](
        items=[_to_out(b) for b in items],
        total=total, limit=limit, offset=offset,
    )


@router.post("", response_model=BroadcastOut, status_code=201)
async def create_broadcast(
    title: str = Form(default="", max_length=MAX_BROADCAST_TITLE_LENGTH),
    body: str = Form(min_length=1, max_length=MAX_BROADCAST_BODY_LENGTH),
    photo: Optional[UploadFile] = File(default=None),
    user: TelegramUser = Depends(admin_required),
    svc: BroadcastService = Depends(get_broadcast_service),
) -> BroadcastOut:
    """Multipart/form-data:
      title (str, ixtiyoriy)
      body  (str, majburiy; rasm bilan max 1024 belgi, rasmsiz max 3500)
      photo (file, ixtiyoriy; jpg/png/webp, max 5 MB)
    """
    photo_path: Optional[str] = None
    if photo is not None and photo.filename:
        photo_path = await _save_photo(photo)

    try:
        br = await svc.create_and_send(
            BroadcastInput(
                title=title,
                body=body,
                created_by=int(user.id),
                photo_path=photo_path,
            )
        )
    except ValidationError as e:
        # Saqlangan faylni o'chiramiz (orfan bo'lmasin)
        if photo_path:
            try:
                (_MEDIA_ROOT.parent / photo_path).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidOperationError as e:
        if photo_path:
            try:
                (_MEDIA_ROOT.parent / photo_path).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(status_code=409, detail=str(e))
    except DomainError as e:
        if photo_path:
            try:
                (_MEDIA_ROOT.parent / photo_path).unlink(missing_ok=True)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))
    return _to_out(br)


@router.get("/{broadcast_id}", response_model=BroadcastOut)
async def get_broadcast(
    broadcast_id: int,
    _=Depends(admin_required),
    svc: BroadcastService = Depends(get_broadcast_service),
) -> BroadcastOut:
    try:
        br = await svc.get(broadcast_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Rassilka topilmadi")
    return _to_out(br)


@router.post("/{broadcast_id}/cancel", response_model=BroadcastOut)
async def cancel_broadcast(
    broadcast_id: int,
    _=Depends(admin_required),
    svc: BroadcastService = Depends(get_broadcast_service),
) -> BroadcastOut:
    try:
        br = await svc.cancel(broadcast_id)
    except EntityNotFoundError:
        raise HTTPException(status_code=404, detail="Rassilka topilmadi")
    return _to_out(br)
