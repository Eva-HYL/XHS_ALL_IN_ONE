"""archive wechat mp characters

Revision ID: a4c7e9d2f1b0
Revises: df9e7f5d9f3a
"""

from alembic import op
import sqlalchemy as sa


revision = "a4c7e9d2f1b0"
down_revision = "df9e7f5d9f3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wechat_mp_illustration_characters",
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_wechat_mp_illustration_characters_archived_at",
        "wechat_mp_illustration_characters",
        ["archived_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wechat_mp_illustration_characters_archived_at",
        table_name="wechat_mp_illustration_characters",
    )
    op.drop_column("wechat_mp_illustration_characters", "archived_at")
