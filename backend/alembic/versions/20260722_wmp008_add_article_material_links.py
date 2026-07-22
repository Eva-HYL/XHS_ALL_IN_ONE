"""add wechat mp article material links

Revision ID: 20260722_wmp008
Revises: 20260722_wmp007
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_wmp008"
down_revision: Union[str, None] = "20260722_wmp007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wechat_mp_article_materials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["wechat_mp_articles.id"], name="fk_wechat_mp_article_materials_article_id"),
        sa.ForeignKeyConstraint(["material_id"], ["wechat_mp_materials.id"], name="fk_wechat_mp_article_materials_material_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_article_materials_user_id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("article_id", "material_id", name="uq_wechat_mp_article_materials_article_material"),
    )
    op.create_index("ix_wechat_mp_article_materials_id", "wechat_mp_article_materials", ["id"], unique=False)
    op.create_index("ix_wechat_mp_article_materials_user_id", "wechat_mp_article_materials", ["user_id"], unique=False)
    op.create_index("ix_wechat_mp_article_materials_article_id", "wechat_mp_article_materials", ["article_id"], unique=False)
    op.create_index("ix_wechat_mp_article_materials_material_id", "wechat_mp_article_materials", ["material_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_wechat_mp_article_materials_material_id", table_name="wechat_mp_article_materials")
    op.drop_index("ix_wechat_mp_article_materials_article_id", table_name="wechat_mp_article_materials")
    op.drop_index("ix_wechat_mp_article_materials_user_id", table_name="wechat_mp_article_materials")
    op.drop_index("ix_wechat_mp_article_materials_id", table_name="wechat_mp_article_materials")
    op.drop_table("wechat_mp_article_materials")
