"""app_settings singleton — cashback toggle + percent.

Revision ID: 0004_settings
Revises: 0003_indexes
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_settings"
down_revision = "0003_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cashback_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cashback_percent", sa.Numeric(5, 2), nullable=False, server_default=sa.text("1.5")),
        sa.Column("max_cashback_usage_ratio", sa.Numeric(5, 2), nullable=False, server_default=sa.text("1.00")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Default singleton qator
    op.execute("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")


def downgrade() -> None:
    op.drop_table("app_settings")
