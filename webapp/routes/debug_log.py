"""Mini App'dan frontend loglarni serverga yuborish — debug uchun.

Foydalanish: frontend `_glog()` har xabarni `POST /api/debug/log` ga yuboradi,
server uni terminalga chiqaradi. Production'da o'chirilishi kerak yoki rate-limit
qo'shilishi kerak — hozircha faqat lokal debug.

Kerakli emas auth — debug uchun. Tashqi tahdid yo'q (faqat log yozadi).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/debug", tags=["debug"])

# Alohida logger — terminal'da boshqa noise'dan ajralib turadi.
log = logging.getLogger("webapp.frontend")


class FrontLog(BaseModel):
    tag: str = Field(default="gps", max_length=32)
    msg: str = Field(max_length=500)
    t_ms: int = Field(default=0, ge=0, le=10_000_000)
    extra: Any = None


def _one_line(value: object, cap: int = 300) -> str:
    """Log-injection va flood himoyasi: yangi-qatorlar olib tashlanadi,
    uzunlik cheklanadi (extra ixtiyoriy JSON — chegarasiz bo'lmasin)."""
    s = str(value)
    s = s.replace("\r", " ").replace("\n", " ")
    return s[:cap] + ("…" if len(s) > cap else "")


@router.post("/log")
async def frontend_log(payload: FrontLog, request: Request) -> dict:
    """Frontend qisqacha log yuboradi — terminalga formatlangan chiqaramiz."""
    ua = (request.headers.get("user-agent") or "")[:80]
    log.info(
        "[%s T+%dms] %s | extra=%s | ua=%s",
        payload.tag, payload.t_ms, _one_line(payload.msg, 500),
        _one_line(payload.extra), ua,
    )
    return {"ok": True}
