"""add usage record resource metadata

Revision ID: 20260721_wmp002
Revises: 20260721_wmp001
Create Date: 2026-07-21 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_wmp002"
down_revision: Union[str, None] = "20260721_wmp001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usage_records", sa.Column("platform", sa.String(length=32), nullable=True))
    op.add_column("usage_records", sa.Column("resource_type", sa.String(length=64), nullable=True))
    op.add_column("usage_records", sa.Column("resource_id", sa.Integer(), nullable=True))
    op.create_index("ix_usage_records_platform", "usage_records", ["platform"])
    op.create_index("ix_usage_records_resource_type", "usage_records", ["resource_type"])
    op.create_index("ix_usage_records_resource_id", "usage_records", ["resource_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_records_resource_id", table_name="usage_records")
    op.drop_index("ix_usage_records_resource_type", table_name="usage_records")
    op.drop_index("ix_usage_records_platform", table_name="usage_records")
    op.drop_column("usage_records", "resource_id")
    op.drop_column("usage_records", "resource_type")
    op.drop_column("usage_records", "platform")
