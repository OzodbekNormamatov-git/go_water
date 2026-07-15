# Database migrations (Alembic)

## Foydalanish

```bash
# DB ni yangi modelga moslab migration yaratish
alembic revision --autogenerate -m "describe change"

# Migratsiyalarni qo'llash
alembic upgrade head

# Bitta qadam orqaga
alembic downgrade -1
```

## Mavjud DB uchun (legacy)

`Data/database.py` ichida hozircha **inline migratsiyalar** ham bor — ular eski
deploy'lardagi schema'ni yangi modelga moslab keladi. Yangi schema o'zgarishlari
endi to'liq **Alembic** orqali boshqariladi:

1. Modelni o'zgartiring
2. `alembic revision --autogenerate -m "..."` — script yaratiladi
3. Script'ni ko'rib chiqib (autogenerate hammasini ko'rmaydi)
4. `alembic upgrade head` — deploy

Eski inline migratsiyalar idempotent, shu sababli ikkala yo'lni parallel
ishlatish xavfsiz; lekin yangi o'zgarishlar uchun **alembic** yagona manba bo'lishi
kerak.

## Sxema baseline

Birinchi marta tugatish uchun:
```bash
alembic stamp head  # mavjud DB ni "fresh" deb belgilab qo'yish
```
