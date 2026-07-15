"""Avto-eslatma matematikasi — sof funksiyalar (yon ta'sirsiz, oson test).

Variant C — iste'mol tezligi:
  per_idish_kun = median(gap_i / bottles_i)   (gap = ketma-ket buyurtmalar orasidagi kun)
  cycle = clamp(oxirgi_idish_soni × per_idish_kun, MIN..MAX)
  due   = oxirgi_yetkazilgan_sana + (k+1) × cycle      (k = shu buyurtmadan keyingi eslatmalar)

Idish soni 0 bo'lgan buyurtmalar (faqat pumpa/kuller) iste'mol hisobiga kirmaydi.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import List, Optional, Sequence, Tuple

from Domain.constants import (
    DEFAULT_PER_BOTTLE_DAYS,
    REMINDER_MAX_CYCLE_DAYS,
    REMINDER_MIN_CYCLE_DAYS,
)

# history elementi: (delivered_at: datetime[UTC], bottles_issued: int)
History = Sequence[Tuple[datetime, int]]


def estimate_per_bottle_days(history: History) -> Optional[float]:
    """Bitta idish o'rtacha necha kun yetishi (median, robust). Yetarli ma'lumot
    bo'lmasa None."""
    rates: List[float] = []
    for i in range(len(history) - 1):
        t0, q0 = history[i]
        t1, _ = history[i + 1]
        gap_days = (t1 - t0).total_seconds() / 86400.0
        if q0 > 0 and gap_days > 0:
            rates.append(gap_days / q0)
    if not rates:
        return None
    return float(median(rates))


def cycle_days_for(
    history: History, *, fallback_per_bottle_days: float = DEFAULT_PER_BOTTLE_DAYS,
) -> Optional[float]:
    """Oxirgi buyurtma idishlari necha kunda tugashi (clamp qilingan).

    None qaytaradi, agar:
      * tarix bo'sh, yoki
      * oxirgi buyurtmada qaytariladigan idish yo'q (faqat pumpa/kuller).
    """
    if not history:
        return None
    last_q = history[-1][1]
    if last_q <= 0:
        return None
    pbd = estimate_per_bottle_days(history)
    if pbd is None or pbd <= 0:
        pbd = fallback_per_bottle_days
    cycle = last_q * pbd
    return max(REMINDER_MIN_CYCLE_DAYS, min(REMINDER_MAX_CYCLE_DAYS, cycle))


def due_datetime(history: History, *, reminders_since_order: int,
                 fallback_per_bottle_days: float = DEFAULT_PER_BOTTLE_DAYS) -> Optional[Tuple[datetime, float]]:
    """Keyingi eslatma "tugash" vaqti (UTC) + ishlatilgan sikl.

    `reminders_since_order` (k) — shu buyurtmadan keyin yuborilgan eslatmalar soni;
    har eslatma due'ni bitta sikl oldinga suradi (kunlik spam bo'lmasin).
    None — sikl hisoblanmadi (yetarli ma'lumot yo'q yoki oxirgi buyurtma idishsiz).
    """
    cycle = cycle_days_for(history, fallback_per_bottle_days=fallback_per_bottle_days)
    if cycle is None:
        return None
    last_delivered = history[-1][0]
    due = last_delivered + timedelta(days=(reminders_since_order + 1) * cycle)
    return due, cycle
