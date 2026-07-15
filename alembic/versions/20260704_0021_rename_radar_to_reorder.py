"""Nomlash tozalashi: app_settings.radar_churn_after_days -> reorder_churn_after_days.

Revision ID: 0021_rename_radar_to_reorder
Revises: 0020_delivered_quantity
Create Date: 2026-07-04

"Radar" atamasi UI'da chalkash edi — hamma joyda "Aqlli eslatma" ga o'zgartirildi.
Ustun nomi ham moslashtiriladi (ma'lumot saqlanadi — oddiy RENAME).
Eslatma: migratsiya revision-id'lari (0019_reorder_radar) tarixiy — o'zgarmaydi.
"""
from __future__ import annotations

from alembic import op

revision = "0021_rename_radar_to_reorder"
down_revision = "0020_delivered_quantity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "app_settings", "radar_churn_after_days",
        new_column_name="reorder_churn_after_days",
    )


def downgrade() -> None:
    op.alter_column(
        "app_settings", "reorder_churn_after_days",
        new_column_name="radar_churn_after_days",
    )
