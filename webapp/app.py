"""FastAPI app factory.

main.py'da `create_app(container)` chaqiriladi va natija uvicorn'ga beriladi.
"""
from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from sqlalchemy.orm.exc import StaleDataError

from Service.exceptions import (
    DomainError,
    EntityNotFoundError,
    InvalidOperationError,
    ValidationError,
)
from webapp.admin import routes_auth as admin_auth_routes
from webapp.admin import routes_broadcasts as admin_broadcasts_routes
from webapp.admin import routes_expenses as admin_expenses_routes
from webapp.admin import routes_finance as admin_finance_routes
from webapp.admin import routes_operator as admin_operator_routes
from webapp.admin import routes_promoters as admin_promoters_routes
from webapp.admin import routes_reorder as admin_reorder_routes
from webapp.admin import routes_reports as admin_reports_routes
from webapp.admin import routes_resources as admin_resources
from webapp.admin import routes_settings as admin_settings_routes
from webapp.admin import routes_stats as admin_stats_routes
from webapp.deps import AppContainer
from webapp.routes import addresses as address_routes
from webapp.routes import cart as cart_routes
from webapp.routes import config as config_routes
from webapp.routes import courier as courier_routes
from webapp.routes import debug_log as debug_log_routes
from webapp.routes import geocode as geocode_routes
from webapp.routes import me as me_routes
from webapp.routes import orders as order_routes
from webapp.routes import products as product_routes
from webapp.routes import promo as promo_routes

log = logging.getLogger(__name__)

# Loyiha ildizi (delivery_bot/) — `media/` va `webapp/static/` shu yerda joylashgan.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MEDIA_DIR = PROJECT_ROOT / "media"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ADMIN_STATIC_DIR = Path(__file__).resolve().parent / "admin_static"
COURIER_STATIC_DIR = Path(__file__).resolve().parent / "courier_static"


def _rate_limit_key(request: Request) -> str:
    """Rate limit kaliti — initData ichidagi Telegram user_id (verifikatsiyasiz parsing).

    Verifikatsiyani auth dependency'larda qilamiz; bu yerda faqat keying maqsadida
    ID ni ajratamiz. ID topilmasa, IP'ga fallback (oddiy proxy himoyasi).
    """
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("tma "):
        import urllib.parse
        import json
        try:
            parsed = dict(urllib.parse.parse_qsl(auth[4:].strip()))
            user_raw = parsed.get("user")
            if user_raw:
                obj = json.loads(user_raw)
                uid = obj.get("id")
                if uid:
                    # IP + uid kombinatsiyasi: initData bu bosqichda TEKSHIRILMAGAN,
                    # faqat uid bo'lsa hujumchi soxta id aylantirib har so'rovda
                    # yangi bucket olardi (limit chetlab o'tilardi). IP prefiks
                    # bilan soxta id'lar bitta IP kvotasiga yig'iladi.
                    return f"{get_remote_address(request)}:tg:{uid}"
        except (ValueError, KeyError):
            pass
    return get_remote_address(request)


def create_app(*, container: AppContainer, cors_origins: List[str]) -> FastAPI:
    app = FastAPI(
        title="Delivery Mini App API",
        version="1.0.0",
        # /docs va /redoc — production'da yopib qo'yish mumkin, lekin diagnostika
        # uchun foydali. Auth talab qilmaydi, biroq hech qanday sirli ma'lumot ham bermaydi.
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.container = container

    # Rate limiting — per user_id (yoki IP) daqiqada 60 so'rov.
    limit_per_min = getattr(container, "rate_limit_per_minute", 60)
    limiter = Limiter(
        key_func=_rate_limit_key,
        default_limits=[f"{limit_per_min}/minute"],
        headers_enabled=True,
    )
    app.state.limiter = limiter

    async def _on_rate_limited(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "message": "Juda ko'p so'rov, biroz kuting."},
        )
    app.add_exception_handler(RateLimitExceeded, _on_rate_limited)
    app.add_middleware(SlowAPIMiddleware)

    # CORS — Telegram Mini App o'zining iframeida ishlaydi, default'da bizga
    # cross-origin so'rov keladi (origin = `null` yoki `https://web.telegram.org`).
    # Konfig orqali kerakli origin'larni qo'shamiz; bo'sh bo'lsa "*" qo'yamiz
    # (auth Telegram InitData orqali, bu xavfsiz).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_credentials=False,
        # Bizning API'da PATCH/DELETE ham bor (manzillar, mahsulotlar, kuryerlar).
        # OPTIONS — CORS preflight uchun shart.
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Xavfsizlik header'lari + so'rov ID + log qatori.
    @app.middleware("http")
    async def request_logging(request: Request, call_next):  # type: ignore[no-redef]
        rid = uuid.uuid4().hex[:8]
        request.state.request_id = rid
        t0 = time.monotonic()
        try:
            resp = await call_next(request)
        except Exception:
            log.exception("[%s] %s %s — UNHANDLED", rid, request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={"error": "internal_error", "message": "Server xatosi yuz berdi.", "request_id": rid},
            )
        dur_ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code >= 500 or dur_ms > 3000:
            log.warning("[%s] %s %s -> %s (%dms)", rid, request.method, request.url.path, resp.status_code, dur_ms)
        else:
            log.debug("[%s] %s %s -> %s (%dms)", rid, request.method, request.url.path, resp.status_code, dur_ms)
        resp.headers["X-Request-ID"] = rid
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        # Telegram Mini App'ni iframe'da yuklaydi — frame-ancestors ni ochiq qoldirish kerak.
        # CSP'ni qattiq qilmaymiz, chunki ramz/skript Telegram CDN'dan yuklanadi.

        # HTML / JS / CSS uchun aggressive cache'ni o'chiramiz (WebView eski versiyani
        # ko'rsatmasligi uchun). API JSON javoblariga bu tegmaydi.
        path = request.url.path
        if path == "/" or path.startswith("/app/") or path.startswith("/admin") or path.startswith("/courier"):
            resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
        return resp

    # Validation xatolari — bizning ErrorOut formatiga moslab javob qaytaramiz.
    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError):
        # Birinchi xato xabarini tanlaymiz (UI uchun yetarli).
        msg = "So'rov noto'g'ri."
        try:
            err = exc.errors()[0]
            msg = err.get("msg") or msg
        except Exception:
            pass
        return JSONResponse(
            status_code=422,
            content={"error": "validation_error", "message": msg},
        )

    # HTTPException — FastAPI default'da {"detail": ...} qaytaradi; biz {error, message} ga moslaymiz.
    @app.exception_handler(HTTPException)
    async def _on_http_exc(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": f"http_{exc.status_code}",
                "message": exc.detail if isinstance(exc.detail, str) else "Xatolik.",
            },
            headers=exc.headers or {},
        )

    # Domain xatolari — odatda routerda tutiladi, lekin bu ishonchlilik uchun tarmoq.
    @app.exception_handler(EntityNotFoundError)
    async def _on_not_found(request: Request, exc: EntityNotFoundError):
        return JSONResponse(status_code=404, content={"error": "not_found", "message": str(exc)})

    @app.exception_handler(ValidationError)
    async def _on_validation_domain(request: Request, exc: ValidationError):
        return JSONResponse(status_code=400, content={"error": "validation_error", "message": str(exc)})

    @app.exception_handler(InvalidOperationError)
    async def _on_invalid_op(request: Request, exc: InvalidOperationError):
        return JSONResponse(status_code=409, content={"error": "invalid_operation", "message": str(exc)})

    @app.exception_handler(DomainError)
    async def _on_domain_other(request: Request, exc: DomainError):
        return JSONResponse(status_code=400, content={"error": "domain_error", "message": str(exc)})

    # Konkurrent UPDATE/DELETE: get() bilan flush() orasida boshqa sessiya
    # qatorni o'chirgan. 500 emas, 409 Conflict + tushunarli xabar.
    @app.exception_handler(StaleDataError)
    async def _on_stale_data(request: Request, exc: StaleDataError):
        rid = getattr(request.state, "request_id", "?")
        log.info("[%s] StaleDataError at %s — concurrent modification", rid, request.url.path)
        return JSONResponse(
            status_code=409,
            content={
                "error": "stale_data",
                "message": "Ma'lumot boshqa joydan o'zgartirilgan. Sahifani yangilab, qayta urinib ko'ring.",
            },
        )

    # Eng oxirgi tarmoq — har qanday kutilmagan xatolikni 500 ga aylantiradi.
    @app.exception_handler(Exception)
    async def _on_unhandled(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", "?")
        log.exception("[%s] Unhandled at %s", rid, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "Server xatosi yuz berdi.", "request_id": rid},
        )

    # ----- API marshrutlari
    app.include_router(product_routes.router)
    app.include_router(me_routes.router)
    app.include_router(address_routes.router)
    app.include_router(order_routes.router)
    app.include_router(config_routes.router)
    app.include_router(cart_routes.router)
    app.include_router(geocode_routes.router)
    app.include_router(courier_routes.router)
    app.include_router(promo_routes.router)
    # Debug — frontend loglar terminalda ko'rinsin. Production'da o'chiriladi
    # (env DEBUG_FRONTEND_LOGS=false default). Frontend baribir 404'ga toqat qiladi.
    from config import get_settings as _get_settings
    if _get_settings().debug_frontend_logs:
        app.include_router(debug_log_routes.router)
        log.info("Frontend debug log endpoint enabled (DEBUG_FRONTEND_LOGS=true)")
    # Admin paneli marshrutlari
    app.include_router(admin_auth_routes.router)
    app.include_router(admin_stats_routes.router)
    app.include_router(admin_finance_routes.router)
    app.include_router(admin_finance_routes.activity_router)
    app.include_router(admin_expenses_routes.router)
    app.include_router(admin_reorder_routes.router)
    app.include_router(admin_reports_routes.router)
    app.include_router(admin_settings_routes.router)
    app.include_router(admin_broadcasts_routes.router)
    app.include_router(admin_operator_routes.router)
    app.include_router(admin_promoters_routes.router)
    app.include_router(admin_resources.orders_router)
    app.include_router(admin_resources.products_router)
    app.include_router(admin_resources.couriers_router)
    app.include_router(admin_resources.customers_router)
    app.include_router(admin_resources.operators_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    # ----- Statik fayllar
    if MEDIA_DIR.is_dir():
        app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
    else:
        log.warning("MEDIA_DIR topilmadi: %s — rasmlar 404 berishi mumkin.", MEDIA_DIR)

    if STATIC_DIR.is_dir():
        app.mount("/app", StaticFiles(directory=str(STATIC_DIR), html=True), name="webapp")
    else:
        log.warning("STATIC_DIR topilmadi: %s", STATIC_DIR)

    if ADMIN_STATIC_DIR.is_dir():
        app.mount("/admin", StaticFiles(directory=str(ADMIN_STATIC_DIR), html=True), name="admin")
    else:
        log.warning("ADMIN_STATIC_DIR topilmadi: %s", ADMIN_STATIC_DIR)

    if COURIER_STATIC_DIR.is_dir():
        app.mount("/courier", StaticFiles(directory=str(COURIER_STATIC_DIR), html=True), name="courier")
    else:
        log.warning("COURIER_STATIC_DIR topilmadi: %s", COURIER_STATIC_DIR)

    @app.get("/", include_in_schema=False)
    async def root():
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return JSONResponse({"error": "not_built", "message": "Mini App static fayllari topilmadi."}, status_code=500)

    log.info("FastAPI Mini App tayyor (media=%s, static=%s)", MEDIA_DIR, STATIC_DIR)
    return app
