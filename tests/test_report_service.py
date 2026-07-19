"""ReportService — Excel hisobot integratsiya testlari (SQLite).

Qoplanadi:
  * sana oralig'i filtri (ichida/tashqarida, chegara kunlari)
  * buyurtma/mijoz/ledger qatorlari mazmuni va davr statistikasi
  * xulosa ko'rsatkichlari (delivered bo'yicha savdo, to'lov taqsimoti)
  * .xlsx fayl yaroqliligi: 4 varaq, sharedStrings ichida kutilgan matnlar
  * validatsiya: teskari oraliq / juda uzun oraliq → ValidationError
  * bot orqali yuborish: muvaffaqiyat va xato yo'llari (stub bot)
"""
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

from Data.unit_of_work import UnitOfWork
from Domain.enums import OrderStatus
from Domain.models.expense import Expense, ExpenseCategory
from Domain.models.ledger import LedgerAccount, LedgerKind
from Domain.models.order import Order, OrderItem
from Domain.models.user import User
from Domain.models.user_phone import UserPhone
from Service.exceptions import ValidationError
from Service.expense_service import ExpenseService
from Service.ledger_posting import post_ledger
from Service.report_service import ReportService

from tests.dbutil import make_engine, seed_customer_courier, seed_settings

TODAY = date(2026, 7, 15)
IN_RANGE = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
OUT_RANGE = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)


class _StubBot:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    async def send_document(self, chat_id, document, caption=None):
        if self.fail:
            raise RuntimeError("bot blocked")
        self.sent.append((chat_id, document.filename, len(document.data), caption))


class ReportServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine, self.sf = await make_engine()
        await seed_settings(self.sf)
        self.bot = _StubBot()
        self.svc = ReportService(
            self.sf, admin_bot=self.bot, expense_service=ExpenseService(self.sf),
        )
        self.user_id, self.courier_id, _ = await seed_customer_courier(
            self.sf, tag=1, cashback_balance="7000", bottles_balance=3,
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _seed_order(
        self, *, created, status=OrderStatus.DELIVERED, delivered=None,
        total="44000", payment="cash", qty=2, deleted=False,
    ) -> int:
        async with self.sf() as s:
            o = Order(
                customer_id=self.user_id, courier_id=self.courier_id,
                status=status, items_total=Decimal(total),
                cashback_used=Decimal("0"), cashback_earned=Decimal("500"),
                total_amount=Decimal(total), payment_method=payment,
                bottles_issued=qty, bottles_returned=1,
                delivery_latitude=41.3, delivery_longitude=69.2,
                contact_phone="+998900001122", note="t",
                created_at=created,
                deleted_at=(created if deleted else None),
                delivered_at=delivered or (
                    created if status == OrderStatus.DELIVERED else None
                ),
            )
            o.items = [OrderItem(
                food_name="Suv 19L", unit_price=Decimal("22000"),
                quantity=qty, bottles_per_unit=1,
            )]
            s.add(o)
            await s.commit()
            return o.id

    async def test_date_range_filters_orders(self):
        await self._seed_order(created=IN_RANGE)
        await self._seed_order(created=OUT_RANGE)  # oraliqdan tashqarida
        _, data = await self.svc.build_excel(
            date_from=TODAY, date_to=TODAY,
        )
        self.assertEqual(len(data.orders), 1)
        self.assertEqual(data.orders_created, 1)
        row = data.orders[0]
        self.assertEqual(row.customer_name, "Test Mijoz")
        self.assertEqual(row.courier_name, "Test Kuryer")
        self.assertIn("Suv 19L ×2", row.items_text)
        self.assertEqual(row.payment_label, "Naqd")
        self.assertEqual(row.total_amount, Decimal("44000"))

    async def test_summary_uses_delivered_window(self):
        # Davr ichida yaratilgan, lekin YETKAZILMAGAN buyurtma savdoga kirmaydi.
        await self._seed_order(created=IN_RANGE, status=OrderStatus.NEW)
        await self._seed_order(created=IN_RANGE, total="60000", payment="card")
        _, data = await self.svc.build_excel(date_from=TODAY, date_to=TODAY)
        self.assertEqual(data.orders_created, 2)
        self.assertEqual(data.delivered_count, 1)
        self.assertEqual(data.delivered_total, Decimal("60000"))
        self.assertEqual(data.payment_breakdown["Karta"][0], 1)
        self.assertEqual(data.status_counts["Yangi"], 1)
        self.assertEqual(data.bottles_issued_sum, 2)
        self.assertEqual(data.bottles_returned_sum, 1)

    async def test_customer_rows_with_phones_and_period_stats(self):
        # Ikkinchi telefon qo'shamiz — "Telefonlar" ustunida ikkalasi chiqsin.
        async with self.sf() as s:
            s.add(UserPhone(user_id=self.user_id, phone="+998977776655", is_primary=False))
            await s.commit()
        await self._seed_order(created=IN_RANGE, total="44000")
        _, data = await self.svc.build_excel(date_from=TODAY, date_to=TODAY)
        self.assertEqual(len(data.customers), 1)
        c = data.customers[0]
        self.assertEqual(c.full_name, "Test Mijoz")
        self.assertIn("+998977776655", c.phones)
        self.assertEqual(c.cashback_balance, Decimal("7000"))
        self.assertEqual(c.bottles_balance, 3)
        self.assertEqual(c.period_orders, 1)
        self.assertEqual(c.period_spent, Decimal("44000"))

    async def test_ledger_rows_resolved_names(self):
        oid = await self._seed_order(created=IN_RANGE)
        async with UnitOfWork(self.sf) as uow:
            user = await uow.users.get_for_update(self.user_id)
            await post_ledger(
                uow, subject=user, account=LedgerAccount.CASHBACK,
                kind=LedgerKind.CASHBACK_EARN, delta=Decimal("500"),
                order_id=oid, reason="test earn",
            )
        # post_ledger created_at'ni real "hozir" bilan yozadi — hisobot
        # oynasiga (15.07) kirishi uchun sanani aniq belgilaymiz.
        async with self.sf() as s:
            from sqlalchemy import select as _select
            from Domain.models.ledger import LedgerEntry as _LE
            entry = (await s.execute(_select(_LE))).scalars().one()
            entry.created_at = IN_RANGE
            s.add(entry)
            await s.commit()
        _, data = await self.svc.build_excel(date_from=TODAY, date_to=TODAY)
        self.assertEqual(len(data.entries), 1)
        e = data.entries[0]
        self.assertEqual(e.subject_label, "Mijoz")
        self.assertEqual(e.subject_name, "Test Mijoz")
        self.assertEqual(e.account_label, "Keshbek")
        self.assertEqual(e.kind_label, "Keshbek berildi")
        self.assertEqual(e.delta, Decimal("500"))
        self.assertNotEqual(e.order_no, "")

    async def test_xlsx_file_is_valid_with_4_sheets(self):
        await self._seed_order(created=IN_RANGE)
        xlsx, _ = await self.svc.build_excel(date_from=TODAY, date_to=TODAY)
        self.assertGreater(len(xlsx), 2000)
        with zipfile.ZipFile(BytesIO(xlsx)) as z:
            self.assertIsNone(z.testzip())
            workbook_xml = z.read("xl/workbook.xml").decode("utf-8")
            for sheet in ("Xulosa", "Buyurtmalar", "Mijozlar", "Operatsiyalar"):
                self.assertIn(f'name="{sheet}"', workbook_xml)
            shared = z.read("xl/sharedStrings.xml").decode("utf-8")
            # Kutilgan mazmun faylning ichida haqiqatan bor.
            for text in ("Test Mijoz", "Test Kuryer", "Suv 19L", "Naqd"):
                self.assertIn(text, shared)

    async def test_archived_orders_excluded_everywhere(self):
        # Arxivlangan (soft-delete) buyurtma hisobotning HECH QAYERIGA kirmaydi —
        # Moliya dashboard raqamlari bilan aynan mos bo'lishi shart.
        await self._seed_order(created=IN_RANGE, total="44000")
        await self._seed_order(created=IN_RANGE, total="99000", deleted=True)
        _, data = await self.svc.build_excel(date_from=TODAY, date_to=TODAY)
        self.assertEqual(len(data.orders), 1)
        self.assertEqual(data.orders_created, 1)
        self.assertEqual(data.delivered_count, 1)
        self.assertEqual(data.delivered_total, Decimal("44000"))
        self.assertEqual(data.customers[0].period_orders, 1)
        self.assertEqual(data.customers[0].period_spent, Decimal("44000"))

    async def test_expenses_sheet_and_pnl(self):
        # Rasxodlar: davr ichidagi kiradi, tashqaridagi kirmaydi; sof foyda
        # = tushum − tannarx − rasxodlar (dashboard formulasi).
        await self._seed_order(created=IN_RANGE, total="44000")  # tushum 44000
        async with self.sf() as s:
            cat = ExpenseCategory(name="Benzin")
            s.add(cat)
            await s.flush()
            s.add(Expense(category_id=cat.id, amount=Decimal("15000"),
                          spent_on=TODAY, note="yo'l"))
            s.add(Expense(category_id=cat.id, amount=Decimal("99000"),
                          spent_on=TODAY - timedelta(days=40), note="eski"))
            await s.commit()
        xlsx, data = await self.svc.build_excel(date_from=TODAY, date_to=TODAY)
        self.assertEqual(len(data.expenses), 1)
        e = data.expenses[0]
        self.assertEqual(e.category, "Benzin")
        self.assertEqual(e.amount, Decimal("15000"))
        self.assertEqual(e.source_label, "Bir martalik")
        self.assertEqual(data.expenses_total, Decimal("15000"))
        self.assertEqual(data.expenses_by_cat, [("Benzin", Decimal("15000"))])
        # COGS testda 0 (unit_cost berilmagan) → sof foyda = 44000 − 0 − 15000.
        self.assertEqual(data.net_profit, Decimal("29000.00"))
        with zipfile.ZipFile(BytesIO(xlsx)) as z:
            workbook_xml = z.read("xl/workbook.xml").decode("utf-8")
            self.assertIn('name="Rasxodlar"', workbook_xml)
            shared = z.read("xl/sharedStrings.xml").decode("utf-8")
            self.assertIn("Benzin", shared)
            self.assertIn("SOF FOYDA", shared)

    async def test_cogs_from_unit_cost(self):
        # unit_cost=15000 × 2 dona = 30000 tannarx.
        oid = await self._seed_order(created=IN_RANGE, total="44000")
        async with self.sf() as s:
            from sqlalchemy import update
            await s.execute(update(OrderItem).where(OrderItem.order_id == oid)
                            .values(unit_cost=Decimal("15000")))
            await s.commit()
        _, data = await self.svc.build_excel(date_from=TODAY, date_to=TODAY)
        self.assertEqual(data.cogs, Decimal("30000"))
        self.assertEqual(data.net_profit, Decimal("14000.00"))  # 44000−30000−0

    async def test_validation_errors(self):
        with self.assertRaises(ValidationError):
            await self.svc.build_excel(
                date_from=TODAY, date_to=TODAY - timedelta(days=1),
            )
        with self.assertRaises(ValidationError):
            await self.svc.build_excel(
                date_from=TODAY - timedelta(days=500), date_to=TODAY,
            )

    async def test_build_and_send_success(self):
        await self._seed_order(created=IN_RANGE)
        result = await self.svc.build_and_send(
            date_from=TODAY, date_to=TODAY, admin_telegram_id=999,
        )
        self.assertTrue(result.sent)
        self.assertEqual(result.orders, 1)
        self.assertEqual(len(self.bot.sent), 1)
        chat_id, filename, size, caption = self.bot.sent[0]
        self.assertEqual(chat_id, 999)
        self.assertEqual(filename, "hisobot_2026-07-15_2026-07-15.xlsx")
        self.assertEqual(size, result.size_bytes)
        self.assertIn("Hisobot", caption)

    async def test_build_and_send_bot_failure_reported(self):
        self.bot.fail = True
        result = await self.svc.build_and_send(
            date_from=TODAY, date_to=TODAY, admin_telegram_id=999,
        )
        self.assertFalse(result.sent)
        self.assertIn("bot blocked", result.send_error)
        self.assertGreater(result.size_bytes, 0)  # fayl baribir qurilgan


if __name__ == "__main__":
    unittest.main()
