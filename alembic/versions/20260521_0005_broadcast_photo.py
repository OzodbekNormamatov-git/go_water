"""broadcast.photo_path — rasm bilan ommaviy xabarnoma.

Revision ID: 0005_bcast_photo
Revises: 0004_settings
Create Date: 2026-05-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_bcast_photo"
down_revision = "0004_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "broadcasts",
        sa.Column("photo_path", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("broadcasts", "photo_path")
