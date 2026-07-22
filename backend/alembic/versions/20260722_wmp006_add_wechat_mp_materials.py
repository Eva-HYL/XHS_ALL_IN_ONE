"""add wechat mp materials

Revision ID: 20260722_wmp006
Revises: 20260721_wmp005
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_wmp006"
down_revision: Union[str, None] = "20260721_wmp005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wechat_mp_materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("material_type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_materials_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wechat_mp_materials_id", "wechat_mp_materials", ["id"], unique=False)
    op.create_index("ix_wechat_mp_materials_user_id", "wechat_mp_materials", ["user_id"], unique=False)
    op.create_index("ix_wechat_mp_materials_material_type", "wechat_mp_materials", ["material_type"], unique=False)
    op.create_index("ix_wechat_mp_materials_status", "wechat_mp_materials", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wechat_mp_materials_status", table_name="wechat_mp_materials")
    op.drop_index("ix_wechat_mp_materials_material_type", table_name="wechat_mp_materials")
    op.drop_index("ix_wechat_mp_materials_user_id", table_name="wechat_mp_materials")
    op.drop_index("ix_wechat_mp_materials_id", table_name="wechat_mp_materials")
    op.drop_table("wechat_mp_materials")
