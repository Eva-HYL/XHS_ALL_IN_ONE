"""add illustration runs

Revision ID: 17a6f0c5d2e1
Revises: 0759928ef02b
Create Date: 2026-07-20 11:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "17a6f0c5d2e1"
down_revision: Union[str, None] = "0759928ef02b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "illustration_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("essay", sa.Text(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="shotlist_ready"),
        sa.Column("core_thesis", sa.Text(), nullable=False, server_default=""),
        sa.Column("cognitive_anchors", sa.JSON(), nullable=False),
        sa.Column("shots", sa.JSON(), nullable=False),
        sa.Column("selected_shot_seqs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_illustration_runs_user_id"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], name="fk_illustration_runs_character_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_illustration_runs_user_id", "illustration_runs", ["user_id"])
    op.create_index("ix_illustration_runs_character_id", "illustration_runs", ["character_id"])
    op.create_index("ix_illustration_runs_status", "illustration_runs", ["status"])
    op.create_index("ix_illustration_runs_created_at", "illustration_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_illustration_runs_created_at", table_name="illustration_runs")
    op.drop_index("ix_illustration_runs_status", table_name="illustration_runs")
    op.drop_index("ix_illustration_runs_character_id", table_name="illustration_runs")
    op.drop_index("ix_illustration_runs_user_id", table_name="illustration_runs")
    op.drop_table("illustration_runs")
