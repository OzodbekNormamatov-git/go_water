from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Sequence

from sqlalchemy import and_, case as sa_case_when, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import selectinload

from Data.repositories.base import BaseRepository
from Domain.enums import OrderStatus
from Domain.models.daily_counter import DailyOrderCounter
from Domain.models.order import Order, OrderItem


class OrderRepository(BaseRepository[Order]):
    model = Order

    def _full_query(self):
        """Order + selectinload'lar. Soft-delete filter qo'shilmaydi — caller hal qiladi."""
        return select(Order).options(
            selectinload(Order.items),
            selectinload(Order.customer),
            selectinload(Order.courier),
        )

    async def next_daily_number(self, day: date) -> int:
        """Berilgan kun uchun navbatdagi kunlik buyurtma raqamini ATOMIK qaytaradi.

        PostgreSQL `INSERT ... ON CONFLICT DO UPDATE ... RETURNING` — bitta
        statement'da race-safe:
          * Kun uchun qator yo'q bo'lsa → yaratadi, 1 qaytaradi
          * Bor bo'lsa → atomik +1 qiladi, yangisini qaytaradi

        UoW tranzaksiyasi ichida chaqiriladi — order yaratish bilan birga
        commit/rollback bo'ladi (to'liq xatoda raqam isrof bo'lmaydi).
        Bir vaqtda kelgan ikki order hech qachon bir xil raqam olmaydi
        (ON CONFLICT row lock).
        """
        stmt = (
            pg_insert(DailyOrderCounter)
            .values(day=day, last_number=1)
            .on_conflict_do_update(
                index_elements=[DailyOrderCounter.day],
                set_={"last_number": DailyOrderCounter.last_number + 1},
            )
            .returning(DailyOrderCounter.last_number)
        )
        res = await self._session.execute(stmt)
        return int(res.scalar_one())

    async def get_full(self, order_id: int) -> Optional[Order]:
        """Soft-deleted bo'lsa ham qaytaradi — admin tarix va restore uchun zarur."""
        res = await self._session.execute(self._full_query().where(Order.id == order_id))
        return res.scalar_one_or_none()

    async def get_for_update(self, order_id: int) -> Optional[Order]:
        """Pessimistic row-level lock — claim/transition oqimida race oldini oladi.

        populate_existing — order (yoki selectinload'lari) shu sessiyada
        avvalroq LOCKsiz yuklangan bo'lsa, lock paytidagi haqiqiy qiymatlar
        bilan yangilanadi (stale o'qish oldini oladi).

        YOZISH-TO'SIG'I: avval flush — qayta o'qish sessiyadagi flush
        qilinmagan o'zgarishlarni eski qiymat bilan yo'q qilmasin."""
        await self._session.flush()
        res = await self._session.execute(
            self._active_only(self._full_query()).where(Order.id == order_id).with_for_update()
            .execution_options(populate_existing=True)
        )
        return res.scalar_one_or_none()

    async def get_by_idempotency_key(
        self, customer_id: int, idempotency_key: str,
    ) -> Optional[Order]:
        res = await self._session.execute(
            self._active_only(self._full_query()).where(
                Order.customer_id == customer_id,
                Order.idempotency_key == idempotency_key,
            )
        )
        return res.scalar_one_or_none()

    async def list_active_by_courier(self, courier_id: int) -> Sequence[Order]:
        """Kuryerning tugallanmagan buyurtmalari — ACCEPTED, DELIVERING va ARRIVED.

        ARRIVED ham kiradi: kuryer yetib kelgan, lekin hali bo'sh idishlarni
        kiritib buyurtmani yopmagan (web app'da "Menikim" tab'da ko'rinishi va
        yangi buyurtma claim'ini bloklashi shart — kuryer hali band)."""
        res = await self._session.execute(
            self._active_only(self._full_query())
            .where(
                Order.courier_id == courier_id,
                Order.status.in_([
                    OrderStatus.ACCEPTED,
                    OrderStatus.DELIVERING,
                    OrderStatus.ARRIVED,
                ]),
            )
            .order_by(Order.created_at.asc())
        )
        return res.scalars().all()

    async def list_by_status(self, status: OrderStatus, limit: int = 50) -> Sequence[Order]:
        res = await self._session.execute(
            self._active_only(self._full_query())
            .where(Order.status == status)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return res.scalars().all()

    async def list_recent(self, limit: int = 20) -> Sequence[Order]:
        res = await self._session.execute(
            self._active_only(self._full_query()).order_by(Order.created_at.desc()).limit(limit)
        )
        return res.scalars().all()

    async def all_delivered_for_cadence(self) -> list[tuple[int, int, datetime, int]]:
        """Barcha DELIVERED buyurtmalar: (customer_id, order_id, delivered_at,
        bottles_issued), customer + sana bo'yicha tartiblangan. Avto-eslatma
        kunlik job butun tarixni BITTA so'rovda oladi, keyin Python'da
        guruhlaydi (N+1 yo'q)."""
        stmt = self._active_only(
            select(Order.customer_id, Order.id, Order.delivered_at, Order.bottles_issued)
            .where(Order.status == OrderStatus.DELIVERED, Order.delivered_at.is_not(None))
            .order_by(Order.customer_id.asc(), Order.delivered_at.asc())
        )
        res = await self._session.execute(stmt)
        return [(int(c), int(oid), d, int(b or 0)) for c, oid, d, b in res.all()]

    async def customers_with_open_order(self) -> set[int]:
        """Hozir tugallanmagan buyurtmasi bor mijozlar — ularga eslatma yubormaymiz."""
        stmt = self._active_only(
            select(Order.customer_id).where(
                Order.status.in_([
                    OrderStatus.NEW, OrderStatus.ACCEPTED,
                    OrderStatus.DELIVERING, OrderStatus.ARRIVED,
                ])
            ).distinct()
        )
        res = await self._session.execute(stmt)
        return {int(c) for c in res.scalars().all()}

    # ---------------------- Admin analytics ----------------------

    async def count_by_status(self) -> dict[str, int]:
        """Hozir har bir holatda nechta buyurtma bor (arxivlanganlarsiz)."""
        res = await self._session.execute(
            self._active_only(
                select(Order.status, func.count(Order.id)).group_by(Order.status)
            )
        )
        return {row[0].name: int(row[1]) for row in res.all()}

    @staticmethod
    def _payment_sum(method: str):
        """Bitta to'lov usuli bo'yicha total_amount yig'indisi (SQL ifodasi)."""
        return func.coalesce(
            func.sum(
                sa_case_when(
                    (Order.payment_method == method, Order.total_amount),
                    else_=0,
                )
            ),
            0,
        )

    def _local_bucket(self, fmt: str, tz_name: Optional[str]):
        """delivered_at'ni MAHALLIY vaqtga o'girib formatlaydi (kun/oy bucket).

        Avval UTC kun ishlatilardi — 00:00-05:00 (Toshkent) oralig'idagi
        buyurtmalar oldingi kunga tushib, grafikdan yo'qolardi.
        """
        dialect = self._session.bind.dialect.name if self._session.bind else "postgresql"
        if dialect == "postgresql":
            ts = func.timezone(tz_name or "Asia/Tashkent", Order.delivered_at)
            return func.to_char(ts, fmt)
        # SQLite (test) fallback — tz'siz.
        sqlite_fmt = "%Y-%m-%d" if fmt == "YYYY-MM-DD" else "%Y-%m"
        return func.strftime(sqlite_fmt, Order.delivered_at)

    async def finance_in_window(
        self,
        since: datetime,
        until: datetime,
    ) -> dict:
        """Bir oraliqning moliyaviy breakdown'i — FAQAT DELIVERED buyurtmalar.

        Pul haqiqatda qo'lga tekkan paytda (delivered_at) hisoblanadi — hali
        yetkazilmagan/bekor bo'lishi mumkin buyurtmalar daromadga KIRMAYDI
        (avval created_at bo'yicha barcha noCANCELLED'lar sanalardi — xato).

            total_revenue   — jami tushum (barcha to'lov usullari)
            cash_revenue    — naqd (kuryer orqali)
            card_revenue    — karta orqali
            deposit_revenue — mijoz avans balansidan
            cashback_used   — keshbek bilan qoplangan qism
            cashback_earned — yangi yaratilgan liability
            gross_sale      — items_total (cashback'gacha to'liq summa)
            orders_count    — yetkazilgan buyurtmalar soni
        """
        stmt = self._active_only(select(
            func.coalesce(func.sum(Order.total_amount), 0).label("total"),
            self._payment_sum("cash").label("cash"),
            self._payment_sum("card").label("card"),
            self._payment_sum("deposit").label("deposit"),
            func.coalesce(func.sum(Order.cashback_used), 0).label("cb_used"),
            func.coalesce(func.sum(Order.cashback_earned), 0).label("cb_earned"),
            func.coalesce(func.sum(Order.items_total), 0).label("gross"),
            func.count(Order.id).label("c"),
        ).where(
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at >= since,
            Order.delivered_at < until,
        ))
        res = await self._session.execute(stmt)
        row = res.first()
        return {
            "total_revenue":   float(row.total or 0),
            "cash_revenue":    float(row.cash or 0),
            "card_revenue":    float(row.card or 0),
            "deposit_revenue": float(row.deposit or 0),
            "cashback_used":   float(row.cb_used or 0),
            "cashback_earned": float(row.cb_earned or 0),
            "gross_sale":      float(row.gross or 0),
            "orders_count":    int(row.c or 0),
        }

    async def _finance_grouped_since(
        self, since: datetime, *, fmt: str, key: str, tz_name: Optional[str],
    ) -> list[dict]:
        """finance_by_day/month_since'ning umumiy qismi (bucket format farq qiladi)."""
        bucket = self._local_bucket(fmt, tz_name)
        stmt = self._active_only(select(
            bucket.label("bucket"),
            func.coalesce(func.sum(Order.total_amount), 0).label("total"),
            self._payment_sum("cash").label("cash"),
            self._payment_sum("card").label("card"),
            self._payment_sum("deposit").label("deposit"),
            func.coalesce(func.sum(Order.cashback_used), 0).label("cb_used"),
            func.coalesce(func.sum(Order.cashback_earned), 0).label("cb_earned"),
            func.coalesce(func.sum(Order.items_total), 0).label("gross"),
            func.count(Order.id).label("c"),
        ).where(
            Order.status == OrderStatus.DELIVERED,
            Order.delivered_at >= since,
        ))
        stmt = stmt.group_by("bucket").order_by("bucket")
        res = await self._session.execute(stmt)
        return [
            {
                key: str(r.bucket),
                "total_revenue": float(r.total or 0),
                "cash_revenue": float(r.cash or 0),
                "card_revenue": float(r.card or 0),
                "deposit_revenue": float(r.deposit or 0),
                "cashback_used": float(r.cb_used or 0),
                "cashback_earned": float(r.cb_earned or 0),
                "gross_sale": float(r.gross or 0),
                "count": int(r.c or 0),
            }
            for r in res.all()
        ]

    async def finance_by_day_since(
        self, since: datetime, *, tz_name: Optional[str] = None,
    ) -> list[dict]:
        """Kunlik moliyaviy breakdown (DELIVERED, mahalliy kun) — finance UI uchun."""
        return await self._finance_grouped_since(
            since, fmt="YYYY-MM-DD", key="date", tz_name=tz_name,
        )

    async def finance_by_month_since(
        self, since: datetime, *, tz_name: Optional[str] = None,
    ) -> list[dict]:
        """Oylik moliyaviy breakdown (DELIVERED, mahalliy oy)."""
        return await self._finance_grouped_since(
            since, fmt="YYYY-MM", key="month", tz_name=tz_name,
        )

    async def cogs_in_window(
        self,
        since: datetime,
        until: datetime,
    ) -> float:
        """Davr COGS (tannarx yig'indisi) = Σ unit_cost × yetkazilgan dona.

        Daromad bilan bir xil asos: FAQAT DELIVERED buyurtmalar, delivered_at
        oynasi bo'yicha (tannarx mahsulot topshirilganda "sarflanadi").
        `order_items.unit_cost` — buyurtma paytidagi snapshot; eski (migration'
        gacha) qatorlarda 0, ya'ni "tannarx noma'lum" foydani oshirib ko'rsatadi —
        bu ma'lum cheklov, admin tannarxlarni kiritgach yangi buyurtmalarda aniq.
        """
        # Effective (yetkazilgan) dona — kuryer o'zgartirgan bo'lsa delivered_quantity.
        eff_qty = func.coalesce(OrderItem.delivered_quantity, OrderItem.quantity)
        stmt = (
            select(func.coalesce(func.sum(OrderItem.unit_cost * eff_qty), 0))
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.status == OrderStatus.DELIVERED,
                Order.delivered_at >= since,
                Order.delivered_at < until,
                Order.deleted_at.is_(None),
            )
        )
        res = await self._session.execute(stmt)
        return float(res.scalar_one() or 0)

    async def all_time_cashback_totals(self) -> dict:
        """Hech qachon sotilgan barcha cashback ko'lami (audit/admin xulosa).
        Arxivlangan va CANCELLED'lar hisobga kirmaydi."""
        stmt = self._active_only(select(
            func.coalesce(func.sum(Order.cashback_used), 0).label("used"),
            func.coalesce(func.sum(Order.cashback_earned), 0).label("earned"),
        ).where(Order.status != OrderStatus.CANCELLED))
        res = await self._session.execute(stmt)
        row = res.first()
        return {
            "cashback_used_total": float(row[0] or 0),
            "cashback_earned_total": float(row[1] or 0),
        }

    async def hourly_counts_for_day(self, day_start: datetime) -> list[tuple[int, int]]:
        """Bir kun ichida soatlik buyurtma soni."""
        from datetime import timedelta
        day_end = day_start + timedelta(days=1)
        dialect = self._session.bind.dialect.name if self._session.bind else "postgresql"
        if dialect == "postgresql":
            hour_expr = func.extract("hour", Order.created_at)
        else:
            hour_expr = func.strftime("%H", Order.created_at)
        stmt = self._active_only(select(
            hour_expr.label("hour"),
            func.count(Order.id).label("count"),
        ).where(
            and_(Order.created_at >= day_start, Order.created_at < day_end)
        )).group_by("hour").order_by("hour")
        res = await self._session.execute(stmt)
        return [(int(r.hour), int(r.count)) for r in res.all()]

    async def hourly_counts_in_window(
        self, since: datetime, until: datetime,
    ) -> list[tuple[int, int]]:
        """Bir oraliqdagi soatlik buyurtmalar yig'indisi — pik vaqtlarni topish uchun."""
        dialect = self._session.bind.dialect.name if self._session.bind else "postgresql"
        if dialect == "postgresql":
            hour_expr = func.extract("hour", Order.created_at)
        else:
            hour_expr = func.cast(func.strftime("%H", Order.created_at), type_=None)
        stmt = self._active_only(select(
            hour_expr.label("hour"),
            func.count(Order.id).label("count"),
        ).where(
            and_(Order.created_at >= since, Order.created_at < until),
            Order.status != OrderStatus.CANCELLED,
        )).group_by("hour").order_by("hour")
        res = await self._session.execute(stmt)
        return [(int(r.hour), int(r.count)) for r in res.all()]

    async def weekday_counts_in_window(
        self, since: datetime, until: datetime,
    ) -> list[tuple[int, int]]:
        """Hafta kunlari bo'yicha buyurtma soni (0=Yakshanba ... 6=Shanba)."""
        dialect = self._session.bind.dialect.name if self._session.bind else "postgresql"
        if dialect == "postgresql":
            dow_expr = func.extract("dow", Order.created_at)
        else:
            dow_expr = func.strftime("%w", Order.created_at)
        stmt = self._active_only(select(
            dow_expr.label("dow"),
            func.count(Order.id).label("count"),
        ).where(
            and_(Order.created_at >= since, Order.created_at < until),
            Order.status != OrderStatus.CANCELLED,
        )).group_by("dow").order_by("dow")
        res = await self._session.execute(stmt)
        return [(int(float(r.dow)), int(r.count)) for r in res.all()]

    async def top_products_since(
        self, since: datetime, limit: int = 5,
    ) -> list[tuple[int | None, str, int, float]]:
        """Ko'p sotilgan mahsulotlar — order_items darajasida JOIN bilan filter."""
        # Effective (yetkazilgan) dona — haqiqatda sotilgan miqdor.
        eff_qty = func.coalesce(OrderItem.delivered_quantity, OrderItem.quantity)
        stmt = select(
            OrderItem.food_id,
            OrderItem.food_name,
            func.sum(eff_qty).label("qty"),
            func.sum(OrderItem.unit_price * eff_qty).label("revenue"),
        ).join(Order, Order.id == OrderItem.order_id).where(
            Order.created_at >= since,
            Order.status != OrderStatus.CANCELLED,
            Order.deleted_at.is_(None),  # arxivlangan buyurtmalar hisobga olinmaydi
        ).group_by(OrderItem.food_id, OrderItem.food_name).order_by(
            func.sum(eff_qty).desc()
        ).limit(limit)
        res = await self._session.execute(stmt)
        return [(r[0], r[1], int(r[2] or 0), float(r[3] or 0)) for r in res.all()]

    def _apply_order_filters(
        self,
        stmt,
        *,
        status_filter: Optional[OrderStatus] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        courier_id: Optional[int] = None,
        created_by_operator_id: Optional[int] = None,
        include_archived: bool = False,
    ):
        if not include_archived:
            stmt = self._active_only(stmt)
        if status_filter is not None:
            stmt = stmt.where(Order.status == status_filter)
        if since is not None:
            stmt = stmt.where(Order.created_at >= since)
        if until is not None:
            stmt = stmt.where(Order.created_at <= until)
        if customer_id is not None:
            stmt = stmt.where(Order.customer_id == customer_id)
        if courier_id is not None:
            stmt = stmt.where(Order.courier_id == courier_id)
        if created_by_operator_id is not None:
            stmt = stmt.where(Order.created_by_operator_id == created_by_operator_id)
        return stmt

    async def list_filtered(
        self,
        *,
        status_filter: Optional[OrderStatus] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        courier_id: Optional[int] = None,
        created_by_operator_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Order]:
        stmt = self._apply_order_filters(
            self._full_query().order_by(Order.created_at.desc()),
            status_filter=status_filter, since=since, until=until,
            customer_id=customer_id, courier_id=courier_id,
            created_by_operator_id=created_by_operator_id,
        )
        stmt = stmt.offset(offset).limit(limit)
        res = await self._session.execute(stmt)
        return res.scalars().all()

    async def count_filtered(
        self,
        *,
        status_filter: Optional[OrderStatus] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        customer_id: Optional[int] = None,
        courier_id: Optional[int] = None,
        created_by_operator_id: Optional[int] = None,
    ) -> int:
        stmt = self._apply_order_filters(
            select(func.count(Order.id)),
            status_filter=status_filter, since=since, until=until,
            customer_id=customer_id, courier_id=courier_id,
            created_by_operator_id=created_by_operator_id,
        )
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def stats_per_customer(
        self, customer_ids: Sequence[int],
    ) -> dict[int, tuple[int, float]]:
        """Bitta query'da N ta mijozning (orders_count, total_spent) ni qaytaradi.

        N+1 muammosini bartaraf qiladi: `customer_ids` ro'yxati uchun bitta
        GROUP BY query ishga tushadi. CANCELLED buyurtmalar total_spent'dan
        chiqarib tashlanadi, lekin orders_count ga kiradi (UI'da "buyurtmalar
        soni" deganda hammasi nazarda tutiladi).
        """
        if not customer_ids:
            return {}
        # orders_count — barchasi; total_spent — CANCELLED'siz. Arxivlanganlar chetda.
        stmt = self._active_only(select(
            Order.customer_id,
            func.count(Order.id).label("c"),
            func.coalesce(
                func.sum(
                    sa_case_when(
                        (Order.status != OrderStatus.CANCELLED, Order.total_amount),
                        else_=0,
                    )
                ),
                0,
            ).label("s"),
        ).where(Order.customer_id.in_(list(customer_ids)))).group_by(Order.customer_id)
        res = await self._session.execute(stmt)
        return {
            int(row[0]): (int(row[1] or 0), float(row[2] or 0))
            for row in res.all()
        }

    async def list_by_customer_paginated(
        self, customer_id: int, *, limit: int = 20, offset: int = 0,
    ) -> Sequence[Order]:
        """Mijozning buyurtmalari — arxivlanganlar chetga (mijoz "Buyurtmalarim" uchun)."""
        res = await self._session.execute(
            self._active_only(self._full_query())
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc())
            .offset(offset).limit(limit)
        )
        return res.scalars().all()

    async def count_by_customer(self, customer_id: int) -> int:
        res = await self._session.execute(
            self._active_only(select(func.count(Order.id)))
            .where(Order.customer_id == customer_id)
        )
        return int(res.scalar_one() or 0)

    async def count_delivered_by_courier(
        self,
        courier_id: int,
        since: Optional[datetime] = None,
    ) -> int:
        """Kuryer yetkazib bergan (DELIVERED) zakazlar soni — arxivlanganlar chiqariladi."""
        stmt = self._active_only(select(func.count(Order.id)).where(
            Order.courier_id == courier_id,
            Order.status == OrderStatus.DELIVERED,
        ))
        if since is not None:
            stmt = stmt.where(Order.delivered_at >= since)
        res = await self._session.execute(stmt)
        return int(res.scalar_one() or 0)

    async def stats_per_courier(
        self,
        courier_ids: Sequence[int],
        *,
        today_start: datetime,
        month_start: datetime,
    ) -> dict[int, tuple[int, int, int]]:
        """Bitta query'da N ta kuryer uchun (today, month, total) DELIVERED sonini qaytaradi.

        N+1 muammosini bartaraf qiladi: har kuryerga 3 ta count emas, bitta
        GROUP BY + CASE WHEN orqali barchasi bir so'rovda. Faqat aktiv (arxiv emas)
        DELIVERED buyurtmalar.
        """
        if not courier_ids:
            return {}
        stmt = self._active_only(select(
            Order.courier_id,
            func.coalesce(func.sum(
                sa_case_when((Order.delivered_at >= today_start, 1), else_=0)
            ), 0).label("today"),
            func.coalesce(func.sum(
                sa_case_when((Order.delivered_at >= month_start, 1), else_=0)
            ), 0).label("month"),
            func.count(Order.id).label("total"),
        ).where(
            Order.courier_id.in_(list(courier_ids)),
            Order.status == OrderStatus.DELIVERED,
        )).group_by(Order.courier_id)
        res = await self._session.execute(stmt)
        return {
            int(row[0]): (int(row[1] or 0), int(row[2] or 0), int(row[3] or 0))
            for row in res.all()
        }

    # ---------------------- Soft delete admin helpers ----------------------

    async def list_archived(self, limit: int = 50, offset: int = 0) -> Sequence[Order]:
        """Admin "Arxiv" — soft-deleted buyurtmalar (faqat admin uchun)."""
        res = await self._session.execute(
            self._deleted_only(self._full_query())
            .order_by(Order.deleted_at.desc())
            .offset(offset).limit(limit)
        )
        return res.scalars().all()
