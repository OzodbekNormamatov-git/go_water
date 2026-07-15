"""Notification subsystem.

`formatters` — sof matn quruvchilar (test'lash oson, framework-free).
`dispatcher` — Telegram API'ga yuborish/edit qilish (I/O bilan ishlaydigan qatlam).
`service`    — yuqori darajadagi orkestrator (eski NotificationService API ni saqlaydi).
"""
from Service.notifications.service import NotificationService

__all__ = ["NotificationService"]
