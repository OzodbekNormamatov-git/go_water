from __future__ import annotations

import re
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    """
    .env / muhit o'zgaruvchilaridan o'qiladi.
    DATABASE_URL faqat local Postgres + asyncpg formatida bo'lishi shart.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    customer_bot_token: str
    admin_bot_token: str
    courier_bot_token: str

    courier_group_chat_id: int

    admin_telegram_ids: str = Field(default="")
    # Eslatma: operatorlar .env'da EMAS — `operators` jadvalida (admin botga
    # /start bosadi, admin panel "Operatorlar" bo'limidan aktivlashtiradi).

    database_url: str
    log_level: str = "INFO"

    # Brend nomi — botdagi salom-alik va xabarlarda ishlatiladi.
    # MAJBURIY: .env ichida `BRAND_NAME=...` ko'rsatilishi shart.
    # Misol: "Akilawater". Hardcoded fallback yo'q — har bir deploy o'z brendi.
    brand_name: str = Field(default="")

    # ------------------------- Telegram Mini App -------------------------
    # WEBAPP_PUBLIC_URL — production'da botga "Web App" tugmasini qo'shish va
    # Mini App'ni ochish uchun foydalanuvchiga uzatiladigan HTTPS manzil.
    # Bo'sh bo'lsa — Mini App tugmasi ko'rsatilmaydi (faqat reply-keyboard ishlaydi).
    webapp_public_url: str = Field(default="")
    webapp_host: str = Field(default="0.0.0.0")
    webapp_port: int = Field(default=8080)
    # CORS uchun: ishonchli source'lar (vergul bilan ajratilgan).
    # Telegram Mini App o'z ichida ishlaydi, shuning uchun odatda bo'sh qoldirsa bo'ladi.
    webapp_cors_origins: str = Field(default="")

    # ------------------------- Lokalizatsiya / valyuta -------------------------
    # Default — Toshkent. Brand boshqa joyga ko'chirilsa, .env'da o'zgartirish.
    timezone: str = Field(default="Asia/Tashkent")
    currency_symbol: str = Field(default="so'm")
    locale: str = Field(default="uz")
    rate_limit_per_minute: int = Field(default=60)

    # ------------------------- Geocoding (xarita qidiruvi) -------------------------
    # Manzil qidiruv + teskari geocoding (x,y -> ko'cha/uy/mahalla). Bepul, OSM:
    #   * search  — Photon (avtocomplete, struktura). Default: ommaviy instans.
    #   * reverse — Nominatim. Default: ommaviy instans.
    # PRODUCTION: o'z serveringizda Photon/Nominatim ko'tarib, bu URL'larni
    # o'zgartiring (rate-limit/ishonchlilik uchun). Kalit kerak emas.
    geocode_search_url: str = Field(default="https://photon.komoot.io/api")
    geocode_reverse_url: str = Field(default="https://nominatim.openstreetmap.org/reverse")
    # Nominatim siyosati uchun User-Agent (ideal: aloqa email bilan).
    geocode_user_agent: str = Field(default="rbi-water-delivery-bot")
    # Natijalarni shu hududga moyil qilish (Toshkent markazi) + davlat filtri.
    geocode_bias_lat: float = Field(default=41.3111)
    geocode_bias_lon: float = Field(default=69.2797)

    # ------------------------- Debug / diagnostika -------------------------
    # Production'da `false` — frontend'ning `/api/debug/log` endpoint'i o'chiriladi.
    # Local development'da `true` qilib qo'yib, brauzer'dan GPS va boshqa
    # logs'larni server terminaliga oqim qilish mumkin (qulay debug).
    # Frontend baribir fetch'ni `.catch(()=>{})` bilan o'rab oladi — 404 zarar bermaydi.
    debug_frontend_logs: bool = Field(default=False)

    @field_validator("courier_group_chat_id", mode="before")
    @classmethod
    def _clean_chat_id(cls, v):
        if isinstance(v, str):
            cleaned = re.sub(r"[^\d-]", "", v)
            if not cleaned:
                raise ValueError("COURIER_GROUP_CHAT_ID bo'sh yoki noto'g'ri.")
            return int(cleaned)
        return v

    @field_validator("brand_name", mode="after")
    @classmethod
    def _ensure_brand_name(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError(
                "BRAND_NAME bo'sh. Iltimos, .env fayliga `BRAND_NAME=Akilawater` "
                "(yoki o'z brendingiz nomini) qo'shing."
            )
        return v

    @field_validator("database_url", mode="after")
    @classmethod
    def _ensure_asyncpg(cls, v: str) -> str:
        if not v:
            raise ValueError("DATABASE_URL kiritilmagan.")
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL faqat 'postgresql+asyncpg://...' formatida bo'lishi shart "
                "(local Postgres + asyncpg)."
            )
        return v

    @staticmethod
    def _parse_ids(raw: str) -> List[int]:
        return [int(x.strip()) for x in (raw or "").split(",") if x.strip()]

    @property
    def admin_ids(self) -> List[int]:
        return self._parse_ids(self.admin_telegram_ids)

    @property
    def cors_origins(self) -> List[str]:
        return [
            x.strip()
            for x in (self.webapp_cors_origins or "").split(",")
            if x.strip()
        ]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
