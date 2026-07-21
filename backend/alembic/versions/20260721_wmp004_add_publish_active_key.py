"""add active publish job key

Revision ID: 20260721_wmp004
Revises: 20260721_wmp003
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_wmp004"
down_revision: Union[str, None] = "20260721_wmp003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wechat_mp_publish_jobs",
        sa.Column("active_key", sa.String(length=160), nullable=True),
    )
    op.create_index(
        "ix_wechat_mp_publish_jobs_active_key",
        "wechat_mp_publish_jobs",
        ["active_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_wechat_mp_publish_jobs_active_key", table_name="wechat_mp_publish_jobs")
    op.drop_column("wechat_mp_publish_jobs", "active_key")
