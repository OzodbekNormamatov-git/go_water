"""NotificationService uchun barqaror import nuqtasi (fasad).

Amalda butun kod (main.py, webapp, botlar) `NotificationService`ni shu
moduldan import qiladi — bu kanonik yo'l:

    from Service.notification_service import NotificationService

Haqiqiy implementatsiya `Service/notifications/service.py` da; formatterlar
(`Service/notifications/formatters.py`) o'sha package ichida ishlatiladi va
bu yerdan re-export qilinmaydi (tashqi import qiluvchi yo'q edi).
"""
from Service.notifications import NotificationService

__all__ = ["NotificationService"]
