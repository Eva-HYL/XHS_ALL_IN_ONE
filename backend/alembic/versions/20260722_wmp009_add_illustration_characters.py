"""add wechat mp illustration characters

Revision ID: 20260722_wmp009
Revises: 20260722_wmp008
Create Date: 2026-07-22 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_wmp009"
down_revision: Union[str, None] = "20260722_wmp008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wechat_mp_illustration_characters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("skill_name", sa.String(length=80), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_illustration_characters_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wechat_mp_illustration_characters_user_id", "wechat_mp_illustration_characters", ["user_id"])
    op.create_index("ix_wechat_mp_illustration_characters_skill_name", "wechat_mp_illustration_characters", ["skill_name"])
    op.create_index("ix_wechat_mp_illustration_characters_status", "wechat_mp_illustration_characters", ["status"])


def downgrade() -> None:
    op.drop_index("ix_wechat_mp_illustration_characters_status", table_name="wechat_mp_illustration_characters")
    op.drop_index("ix_wechat_mp_illustration_characters_skill_name", table_name="wechat_mp_illustration_characters")
    op.drop_index("ix_wechat_mp_illustration_characters_user_id", table_name="wechat_mp_illustration_characters")
    op.drop_table("wechat_mp_illustration_characters")
