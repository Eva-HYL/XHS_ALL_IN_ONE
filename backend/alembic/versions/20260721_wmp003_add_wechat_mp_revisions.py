"""add wechat mp article revisions

Revision ID: 20260721_wmp003
Revises: 20260721_wmp002
Create Date: 2026-07-21 19:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_wmp003"
down_revision: Union[str, None] = "20260721_wmp002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wechat_mp_articles",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "wechat_mp_draft_syncs",
        sa.Column("article_revision", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("wechat_mp_draft_syncs", "article_revision")
    op.drop_column("wechat_mp_articles", "revision")
