# Delivery Bot — Telegram bot + Mini App + Admin paneli

Bitta jarayonda ishlaydigan to'liq yetkazib berish tizimi:

- **3 ta Telegram bot**: customer, admin, courier
- **User Mini App**: mijoz uchun grafik buyurtma berish interfeysi (Telegram WebApp)
- **Admin Web paneli**: mahsulot/buyurtma/kuryer + moliya/faollik/rassilka boshqaruvi (Telegram WebApp)
- **REST API**: FastAPI, ham mijoz ham admin Mini App'lari uchun

## Arxitektura — N-tier

```
Bots / WebApp / Admin Panel (presentation)
        ↓ uses
Service (application + business rules)
        ↓ uses
Data (repositories + UnitOfWork)
        ↓ maps
Domain (entities, enums, constants)
```

Asosiy patternlar:
- **Repository pattern** + generic `BaseRepository`
- **UnitOfWork** — atomik tranzaksiyalar (`async with uow:`)
- **Domain exceptions** + `Service/i18n.py` orqali xato kodlarini matnga aylantirish (`raise ValidationError("cart_empty")`)
- **Telegram initData HMAC** auth — ham foydalanuvchi, ham admin Mini App'lari uchun (`webapp/auth.py:verify_init_data`)
- **Idempotency** — buyurtma yaratishda `idempotency_key` (UUID) takroriy POST'larni qaytaradi
- **SELECT FOR UPDATE** — kuryer claim'da va balans yangilashda race-condition'siz
- **Row-level lock + atomik balans** — cashback/bottle balans har orderda atomik ravishda yangilanadi

## Tizim imkoniyatlari

### 📍 Mijozlar uchun

- **Erkin geolokatsiya** — xaritadan (OpenStreetMap, kalit yo'q) istalgan manzilni belgilash
- **Manzillar xotirasi** — "Uy", "Ishxona" kabi yorliqlangan manzillarni saqlash, default belgilash; checkout'da bir bosishda tanlash
- **Telegram Mini App** — bot ichida toza, brand'lashtirilgan SPA
- **Yagona "holat lentasi"** — buyurtma davomida bitta DM xabar tahrirlanib boradi

### 📊 Rahbar uchun (Admin Mini App)

- **Dashboard** — bugungi KPI'lar, top mahsulotlar, kuryerlar, status doughnut
- **Moliyaviy hisobotlar** — Oylik (kunlar kesimida) va Yillik (oylar kesimida); daromad **faqat yetkazilgan (DELIVERED) buyurtmalardan** hisoblanadi va to'lov usuli kesimida ko'rsatiladi (naqd / karta / balans)
- **Rasxodlar (P&L)** — kategoriyalar, doimiy shablonlar, **davrga taqsimlash**: oldindan to'langan oylik/ijara `period_start..period_end` bilan kiritilsa, hisobotlarda har oyga faqat o'sha oyning ulushi tushadi ("faqat ishlatilgan rasxod" printsipi)
- **Mijozlar faolligi** — bazasi o'sishi grafigi + pik soatlar + pik hafta kunlari
- **Buyurtmalar / Mahsulotlar / Kuryerlar / Mijozlar / Operatorlar** — to'liq CRUD + filtrlar

### 💳 To'lov usullari va balanslar

- **To'lov usuli har buyurtmada tanlanadi**: 💵 naqd (kuryer oladi) / 💳 karta / 💰 balansdan
- **Depozit (avans) balans** — MChJ mijozlar oldindan pul o'tkazadi: admin mijoz kartasidan balansni to'ldiradi, buyurtmalar shundan yechiladi (yaratilishda escrow, bekor bo'lsa avto-qaytadi)
- **Kuryer naqd hisobi** — faqat NAQD buyurtmalar kuryer qo'lidagi pulga qo'shiladi; karta/balans buyurtmalarda kuryerdan pul so'ralmaydi (kuryer ilovasida ogohlantirish ko'rinadi)
- **Operatorlar boshqaruvi** — operator admin botga /start bosadi → admin "Operatorlar" bo'limidan aktivlashtiradi (kuryer patterni; `.env` restart talab qilinmaydi)
- **Telefon +998 avto-normalizatsiya** — `901234567` kiritilsa ham `+998901234567` sifatida saqlanadi/qidiriladi (bot + barcha Mini App'lar + backend yagona qoida)

### 🔄 Idishlar nazorati va Avto-Sotuv

- **Bottle balans** — har mijoz uchun qo'ldagi bo'sh idishlar sonini hisobga olib boriladi
- **Buyurtmada qaytarish** — checkout'da mijoz kuryerga necha idish qaytarayotganini ko'rsatadi; balansdan ortig'ini qaytarib bo'lmaydi (DB-level CHECK)
- **Admin manual ajustment** — mijoz kartasidan keshbek/idish balansini qo'lda o'zgartirish (har bir o'zgarish uchun atomarlik bilan)

### 🎯 Marketing va Mijozlarni ushlab qolish

- **Keshbek tizimi** — har sotuvdan keshbek (default **1.5%**; live qiymat admin Mini App "Sozlamalar" orqali `AppSettings` jadvalida, dastlabki seed `Domain/constants.py:DEFAULT_CASHBACK_PERCENT`)
  - har 100 so'mga FLOOR (pastga yaxlitlanadi; masalan 708 → 700)
  - Bitta buyurtmada qoplash chegarasi sozlanadi (default **100%** — to'liq qoplash; live qiymat `AppSettings.max_cashback_usage_ratio`, seed `DEFAULT_MAX_CASHBACK_USAGE_RATIO = 1.00`)
  - Buyurtma yaratilganda darhol ushlab qo'yiladi (escrow); bekor qilinsa avtomatik qaytariladi
  - DELIVERED bo'lganda yangi keshbek qo'shiladi
  - Har bir balans o'zgarishi append-only **ledger** (`ledger_entries`) ga yoziladi — to'liq audit + tiklash
- **Ommaviy xabarnomalar (Rassilka)** — barcha mijozlar bazasiga DM. Background asyncio task; sent/failed jonli kuzatiladi; bitta vaqtda faqat bittasi ishlaydi; admin to'xtatishi mumkin; Telegram rate-limit (`BROADCAST_SEND_DELAY_SECONDS = 0.05`)

## Talablar

- Python 3.11+
- **PostgreSQL 14+** (asyncpg driver bilan)
- HTTPS public URL (Mini App uchun shart) — production'da domen, local dev'da [ngrok](https://ngrok.com/)
- 3 ta Telegram bot ([@BotFather](https://t.me/BotFather))

## Local development

```bash
# 1. Repo + virtualenv
python -m venv .venv
. .venv/Scripts/activate              # Windows
# . .venv/bin/activate                # Linux/Mac
pip install -r requirements.txt

# 2. PostgreSQL DB
psql -U postgres -c "CREATE DATABASE delivery;"

# 3. .env — namuna `.env` da, real tokenlaringizni qo'ying.
#    Avvalo BotFather'da 3 ta bot yarating va ularning tokenlarini oling.

# 4. ngrok (Mini App HTTPS uchun)
ngrok http 8080
# ngrok bergan URL ni .env > WEBAPP_PUBLIC_URL ga yozing

# 5. @BotFather'da har 2 ta bot (customer va admin) uchun:
#       /setdomain → <ngrok host, masalan abcde.ngrok-free.app>
#    (WebApp tugmalari faqat shu host'dan ochiladi)

# 6. Ishga tushirish
python main.py
```

Manzillar:
- `http://localhost:8080/` — foydalanuvchi Mini App (Telegram'dan ochish kerak)
- `http://localhost:8080/admin/` — admin paneli (Telegram'dan ochish kerak)
- `http://localhost:8080/courier/` — kuryer ilovasi (kuryer botidan ochiladi)
- `http://localhost:8080/docs` — FastAPI Swagger (auth talab qilmaydi; production'da yopib qo'yish mumkin)
- `http://localhost:8080/healthz` — health check

## Buyurtma hayot tsikli

```
NEW  ─claim─►  ACCEPTED  ─delivering─►  DELIVERING  ─delivered─►  DELIVERED
                                                                       │
                                            └────cancel (admin)──────► CANCELLED
```

Har bir transitsiyada:
1. DBda atomik yangilanish (UoW + SELECT FOR UPDATE).
2. Kuryer guruhidagi xabar `edit_message_text` orqali yangilanadi.
3. Mijozga DM da yagona **"holat lentasi"** xabar `edit` qilinadi (5 ta alohida xabar emas).
4. **DELIVERED**:
   * `user.cashback_balance += order.cashback_earned`
   * `user.bottles_balance += order.bottles_issued - order.bottles_returned`
5. **CANCELLED**: order.cashback_used user balansiga qaytariladi (escrow refund).

## Production deploy

### Tezkor checklist

- [ ] `.env` ichidagi tokenlar to'g'ri va botlar @BotFather'da `/setdomain` qilingan
- [ ] PostgreSQL ishlab turibdi, `DATABASE_URL` to'g'ri (asyncpg driver bilan)
- [ ] HTTPS sertifikat (Let's Encrypt / Cloudflare / nginx)
- [ ] Reverse proxy 8080 portga proxy qiladi (nginx)
- [ ] Migratsiyalar qo'llanildi:
   - **Yangi muhit**: `alembic upgrade head`
   - **Mavjud baza (eski versiyadan ko'tarilish)**: `alembic stamp 0001_baseline && alembic upgrade head` — yoki shunchaki `python main.py` ishga tushiring (idempotent ALTER'lar `Data/database.py` ichida)
- [ ] systemd / Docker — auto-restart bilan
- [ ] Log fayl rotatsiyasi (logrotate yoki `RotatingFileHandler`)
- [ ] Database backuplari (cron + `pg_dump`)
- [ ] Bo't guruhga **admin** sifatida qo'shilgan (kuryer guruhga xabar yuborish uchun)
- [ ] Customer (`/`), Admin (`/admin/`) va **Kuryer** (`/courier/`) botlarining Menu Button'lari `WEBAPP_PUBLIC_URL` bilan o'rnatilgan (jarayon ishga tushganda avtomatik). **Uchala bot** uchun ham @BotFather'da `/setdomain` host bilan moslangan bo'lishi shart (web_app tugmalari shu host'dan ochiladi)
- [ ] **Health-check** monitoringi (`GET /healthz`) — masalan, UptimeRobot

### Nginx misol

```nginx
server {
    listen 443 ssl http2;
    server_name delivery.example.uz;
    ssl_certificate /etc/letsencrypt/live/delivery.example.uz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/delivery.example.uz/privkey.pem;

    # Body size — broadcast matn 3500 belgi, lekin keyinchalik rasm yuborilsa o'sadi.
    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

### systemd unit (misol)

`/etc/systemd/system/delivery-bot.service`:
```ini
[Unit]
Description=Delivery Bot + Mini App
After=network.target postgresql.service

[Service]
Type=simple
User=delivery
WorkingDirectory=/opt/delivery_bot
ExecStart=/opt/delivery_bot/.venv/bin/python main.py
Restart=on-failure
RestartSec=5
EnvironmentFile=/opt/delivery_bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now delivery-bot
sudo journalctl -u delivery-bot -f       # log ko'rish
```

### Migrations (Alembic)

Yangi muhitda boshlash:
```bash
alembic upgrade head
```

Mavjud bazada (idempotent migratsiyalar yordamida o'rnatilgan) Alembic'ga o'tish:
```bash
alembic stamp 0001_baseline   # mavjud sxema baseline deb belgilanadi
alembic upgrade head          # 0002_loyalty qo'llanadi (yangi ustunlar/jadvallar)
```

Yangi schema o'zgarishi:
```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Kataloglar

| Yo'l | Tarkibi |
|---|---|
| `Bots/{customer,admin,courier}/` | aiogram 3 dispatcher, FSM, keyboards |
| `Service/` | Biznes mantiq (UserService, OrderService, AddressService, LedgerService, AnalyticsService, BroadcastService, NotificationService, CartService, ...) |
| `Data/repositories/` | SQLAlchemy repolar + UnitOfWork |
| `Domain/models/` | SQLAlchemy modellar (User, Order, Food, Courier, CartItem, CustomerAddress, Broadcast) |
| `Domain/enums.py`, `constants.py` | OrderStatus + emoji/color, MAX_QTY, keshbek/bottle konstantalar |
| `webapp/` | FastAPI app, auth, dependencies |
| `webapp/routes/` | User API: `me`, `addresses`, `products`, `orders`, `cart`, `config` |
| `webapp/admin/` | Admin API: auth, stats, finance, activity, broadcasts, resources |
| `webapp/static/` | User Mini App (HTML + JS modules + CSS + Leaflet map picker) |
| `webapp/admin_static/` | Admin Mini App SPA (HTML + JS + CSS + Chart.js) |
| `alembic/` | Migration tool sozlamalari + versions |

## API endpointlari

### Mijoz Mini App (Telegram initData auth)
- `GET /api/me` — joriy foydalanuvchi (+ cashback_balance, bottles_balance)
- `POST /api/me/register` — ro'yxatdan o'tish (ism + telefon)
- `GET /api/me/balance` — real-time balans (cashback %, max usage ratio)
- `GET /api/me/addresses` — saqlangan manzillar ro'yxati
- `POST /api/me/addresses` — yangi manzil qo'shish (limit: 10 ta)
- `PATCH /api/me/addresses/{id}` — manzilni tahrirlash
- `POST /api/me/addresses/{id}/default` — default belgilash
- `DELETE /api/me/addresses/{id}` — o'chirish (default o'chirilsa keyingisi default bo'ladi)
- `GET /api/config` — TTL'lar, brand, status katalogi
- `GET /api/geocode?q=` — manzil/ko'cha/mahalla qidirish (Photon/OSM, kalitsiz)
- `GET /api/reverse-geocode?lat=&lon=` — x,y → o'qiladigan manzil (ko'cha/uy/mahalla)
- `GET /api/products` — mahsulotlar ro'yxati
- `GET /api/products/{id}` — bitta mahsulot
- `GET /api/cart` / `POST /api/cart/items` / `DELETE /api/cart` — server-side savatcha
- `POST /api/orders` — buyurtma yaratish (idempotency_key + cashback_to_use + bottles_returned + address_label/details)
- `GET /api/orders` — mening buyurtmalarim
- `GET /api/orders/{id}` — buyurtma batafsil (timeline + kuryer + cashback breakdown)

### Admin paneli (admin Telegram initData + whitelist)
- `GET /api/admin/auth/me` — sessiya tekshiruvi
- `GET /api/admin/stats` — dashboard (KPI + 30 kun trend + soatlik + top mahsulotlar)
- `GET /api/admin/finance/monthly?year=&month=` — oylik moliyaviy hisobot (kunlar kesimida)
- `GET /api/admin/finance/yearly?year=` — yillik moliyaviy hisobot (oylar kesimida)
- `GET /api/admin/activity?days=N` — mijozlar o'sishi + pik soatlar/kunlar
- `GET /api/admin/broadcasts` — oxirgi rassilkalar
- `POST /api/admin/broadcasts` — yangi rassilka boshlash
- `GET /api/admin/broadcasts/{id}` — bitta rassilka holati (polling uchun)
- `POST /api/admin/broadcasts/{id}/cancel` — yuborishni to'xtatish
- `GET /api/admin/orders[?status=&customer_id=&...]` — filtrlangan ro'yxat
- `GET /api/admin/orders/{id}` / `POST /api/admin/orders/{id}/cancel`
- `GET/POST/PATCH/DELETE /api/admin/products` — CRUD
- `GET /api/admin/couriers` / `PATCH /api/admin/couriers/{id}`
- `GET /api/admin/customers?q=...` — qidirish + xarid statistikasi + balans (operator: balanslar 0)
- `POST /api/admin/customers` — yangi mijoz qo'shish (operator ham; telefon mavjud bo'lsa `created=false`, dublikat yaratilmaydi)
- `POST /api/admin/customers/{id}/cashback` — keshbek balansini ± (ledger yozadi)
- `POST /api/admin/customers/{id}/bottles` — idishlar balansini ± (ledger yozadi)
- `POST /api/admin/customers/{id}/deposit` — avans (depozit) balansini ± (ledger yozadi)
- `GET/POST /api/admin/customers/{id}/phones` — mijoz raqamlari (operator ham); `DELETE`/`.../primary` faqat admin
- `GET /api/admin/customers/{id}/ledger` / `GET /api/admin/couriers/{id}/ledger` — moliyaviy jurnal tarixi
- `GET /api/admin/settings` / `PATCH /api/admin/settings` — cashback konfiguratsiyasi (live)
- `GET /api/admin/settings/cashback` — cashback dasturining moliyaviy ko'rinishi
- `GET /api/admin/operator/customer-lookup?phone=` — operator: mijozni telefonda topish
- `GET /api/admin/operator/customers/{id}/recent-orders` — operator: oxirgi buyurtmalar (takrorlash uchun)
- `POST /api/admin/operator/orders` — operator nomidan buyurtma yaratish

### Kuryer API (kuryer Telegram initData)
- `GET /api/courier/available` / `GET /api/courier/active` / `GET /api/courier/stats`
- `POST /api/courier/orders/{id}/claim|delivering|arrived|delivered` — oqim (race-safe)
- `POST /api/courier/orders/{id}/delivered-items` — haqiqatda yetkazilgan dona (order noldan qayta hisoblanadi)
- `POST /api/courier/orders/{id}/payment-method` — yakuniy to'lov usuli: naqd/karta (depozit o'zgartirilmaydi)
- `POST /api/courier/orders/{id}/bottles` — qaytarib olingan bo'sh idishlar

## Xavfsizlik

- **Telegram initData HMAC** har so'rovda tekshiriladi (bot_token bilan)
- Admin uchun qo'shimcha **whitelist** (`ADMIN_TELEGRAM_IDS`)
- **Rate limiting** — `slowapi` orqali per-user 60/minute (config'dan)
- **CORS** — bo'sh bo'lsa `*` (auth Telegram tomonidan), production'da aniq origin'lar
- Default xato javoblari ichki ma'lumotni ifsho qilmaydi (`{"error","message"}`)
- **DB-level CHECK constraints** — cashback_balance va bottles_balance manfiy bo'lib qola olmaydi
- **Row-level lock** — balans yangilash race-condition'siz
- **Idempotency** — bir xil key bilan qayta yuborilsa duplikat buyurtma yaratilmaydi

## Mavjud kutubxonalar

`requirements.txt`:
- `aiogram==3.13.1` — Telegram Bot framework
- `fastapi==0.115.5` + `uvicorn[standard]` — API
- `SQLAlchemy[asyncio]==2.0.36` + `asyncpg` — async ORM/DB
- `alembic` — migrations
- `slowapi` — rate limiting
- `pydantic` + `pydantic-settings` — validatsiya va konfiguratsiya
- `python-dotenv` — `.env` o'qish (pydantic-settings uchun)
- `python-multipart` — rasm yuklash (broadcast + mahsulot rasmi, multipart/form-data)
- `tzdata` — Windows uchun zoneinfo

Frontend qaramligi (CDN orqali yuklanadi, pip kerak emas):
- **Leaflet 1.9.4** — xarita-piker (OpenStreetMap, kalit yo'q)
- **Chart.js 4.4.6** — admin dashboard grafiklar
- **Telegram WebApp SDK** — Telegram tomonidan beriladi
