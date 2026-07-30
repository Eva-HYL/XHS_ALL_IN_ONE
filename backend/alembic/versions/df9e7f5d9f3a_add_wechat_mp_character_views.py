"""add wechat mp character views

Revision ID: df9e7f5d9f3a
Revises: 20260722_wmp009
"""
from alembic import op
import sqlalchemy as sa

revision = "df9e7f5d9f3a"
down_revision = "20260722_wmp009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    character_columns = {column["name"] for column in inspector.get_columns("wechat_mp_illustration_characters")}
    if "anchor_version" not in character_columns:
        op.add_column("wechat_mp_illustration_characters", sa.Column("anchor_version", sa.Integer(), nullable=False, server_default="1"))
    op.execute("UPDATE wechat_mp_illustration_characters SET status = 'draft' WHERE status = 'active'")
    tables = set(inspector.get_table_names())
    if "wechat_mp_character_views" not in tables:
        op.create_table(
        "wechat_mp_character_views",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("wechat_mp_illustration_characters.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("view", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("file_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("public_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("model_name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("character_id", "view", name="uq_wechat_mp_character_view"),
        )
        op.create_index("ix_wechat_mp_character_views_character_id", "wechat_mp_character_views", ["character_id"])
        op.create_index("ix_wechat_mp_character_views_user_id", "wechat_mp_character_views", ["user_id"])
        op.create_index("ix_wechat_mp_character_views_status", "wechat_mp_character_views", ["status"])
    prompt_columns = {column["name"] for column in inspector.get_columns("wechat_mp_image_prompts")}
    if "character_id" not in prompt_columns:
        op.add_column("wechat_mp_image_prompts", sa.Column("character_id", sa.Integer(), sa.ForeignKey("wechat_mp_illustration_characters.id"), nullable=True))
        op.create_index("ix_wechat_mp_image_prompts_character_id", "wechat_mp_image_prompts", ["character_id"])


def downgrade() -> None:
    op.drop_index("ix_wechat_mp_image_prompts_character_id", table_name="wechat_mp_image_prompts")
    op.drop_column("wechat_mp_image_prompts", "character_id")
    op.drop_index("ix_wechat_mp_character_views_status", table_name="wechat_mp_character_views")
    op.drop_index("ix_wechat_mp_character_views_user_id", table_name="wechat_mp_character_views")
    op.drop_index("ix_wechat_mp_character_views_character_id", table_name="wechat_mp_character_views")
    op.drop_table("wechat_mp_character_views")
    op.drop_column("wechat_mp_illustration_characters", "anchor_version")
    op.execute("UPDATE wechat_mp_illustration_characters SET status = 'active' WHERE status = 'draft'")
