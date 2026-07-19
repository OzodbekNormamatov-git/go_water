"""Admin hisobotlar API — /api/admin/reports/*.

Excel eksport (Variant A): sana oralig'i → .xlsx quriladi → so'ragan
adminning O'ZIGA admin bot orqali hujjat sifatida yuboriladi. Admin-only
(to'liq mijoz balanslari va moliyaviy jurnal — operator ko'rmaydi).
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from Service.report_service import ReportService
from webapp.admin.auth import admin_required
from webapp.auth import TelegramUser
from webapp.deps import get_report_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/reports", tags=["admin:reports"])


class ExcelReportIn(BaseModel):
    date_from: date
    date_to: date


class ExcelReportOut(BaseModel):
    # sent=False bo'lsa fayl qurildi-yu DM bormadi (masalan, admin botga
    # /start yubormagan) — frontend warning ko'rsatadi.
    sent: bool
    filename: str
    size_kb: int
    orders: int
    customers: int
    entries: int
    error: str = ""


@router.post("/excel", response_model=ExcelReportOut)
async def export_excel(
    payload: ExcelReportIn,
    user: TelegramUser = Depends(admin_required),
    reports: ReportService = Depends(get_report_service),
) -> ExcelReportOut:
    result = await reports.build_and_send(
        date_from=payload.date_from,
        date_to=payload.date_to,
        admin_telegram_id=user.id,
    )
    log.info(
        "Excel hisobot (tg=%s): %s, %d KB, sent=%s",
        user.id, result.filename, result.size_bytes // 1024, result.sent,
    )
    return ExcelReportOut(
        sent=result.sent,
        filename=result.filename,
        size_kb=max(1, result.size_bytes // 1024),
        orders=result.orders,
        customers=result.customers,
        entries=result.entries,
        error="" if result.sent else (
            "Bot xabar yubora olmadi — admin botiga /start yuborib qayta urining."
        ),
    )
