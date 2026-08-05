"""add wechat prompt ignore rules and visual plans

Revision ID: c8f4a1d9e2b0
Revises: b7e2c4d6a8f0
"""

from alembic import op
import sqlalchemy as sa


revision = "c8f4a1d9e2b0"
down_revision = "b7e2c4d6a8f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("wechat_mp_image_prompts", sa.Column("visual_plan", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("wechat_mp_image_prompts", sa.Column("quality_report", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "wechat_mp_prompt_ignore_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_article_id", sa.Integer(), nullable=True),
        sa.Column("source_prompt_id", sa.Integer(), nullable=True),
        sa.Column("candidate_kind", sa.String(length=32), nullable=False, server_default="semantic"),
        sa.Column("source_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("concept_signature", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_article_id"], ["wechat_mp_articles.id"]),
        sa.ForeignKeyConstraint(["source_prompt_id"], ["wechat_mp_image_prompts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_wechat_mp_prompt_ignore_rules_id", "wechat_mp_prompt_ignore_rules", ["id"])
    op.create_index("ix_wechat_mp_prompt_ignore_rules_user_id", "wechat_mp_prompt_ignore_rules", ["user_id"])
    op.create_index("ix_wechat_mp_prompt_ignore_rules_source_article_id", "wechat_mp_prompt_ignore_rules", ["source_article_id"])
    op.create_index("ix_wechat_mp_prompt_ignore_rules_source_prompt_id", "wechat_mp_prompt_ignore_rules", ["source_prompt_id"])
    op.create_index("ix_wechat_mp_prompt_ignore_rules_status", "wechat_mp_prompt_ignore_rules", ["status"])


def downgrade() -> None:
    op.drop_index("ix_wechat_mp_prompt_ignore_rules_status", table_name="wechat_mp_prompt_ignore_rules")
    op.drop_index("ix_wechat_mp_prompt_ignore_rules_source_prompt_id", table_name="wechat_mp_prompt_ignore_rules")
    op.drop_index("ix_wechat_mp_prompt_ignore_rules_source_article_id", table_name="wechat_mp_prompt_ignore_rules")
    op.drop_index("ix_wechat_mp_prompt_ignore_rules_user_id", table_name="wechat_mp_prompt_ignore_rules")
    op.drop_index("ix_wechat_mp_prompt_ignore_rules_id", table_name="wechat_mp_prompt_ignore_rules")
    op.drop_table("wechat_mp_prompt_ignore_rules")
    op.drop_column("wechat_mp_image_prompts", "quality_report")
    op.drop_column("wechat_mp_image_prompts", "visual_plan")
