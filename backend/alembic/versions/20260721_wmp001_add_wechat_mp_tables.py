"""add wechat mp tables

Revision ID: 20260721_wmp001
Revises: 17a6f0c5d2e1
Create Date: 2026-07-21 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_wmp001"
down_revision: Union[str, None] = "17a6f0c5d2e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_indexes(table_name: str, columns: list[str]) -> None:
    for column in columns:
        op.create_index(f"ix_{table_name}_{column}", table_name, [column])


def upgrade() -> None:
    op.create_table(
        "wechat_mp_accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("encrypted_app_secret", sa.Text(), nullable=False),
        sa.Column("token_cache", sa.JSON(), nullable=True),
        sa.Column("connection_status", sa.String(length=32), nullable=False, server_default="unchecked"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_accounts_user_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("wechat_mp_accounts", ["user_id"])

    op.create_table(
        "wechat_mp_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("markdown_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("html_body", sa.Text(), nullable=False, server_default=""),
        sa.Column("digest", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("cover_brief", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft_local"),
        sa.Column("illustration_skill", sa.String(length=80), nullable=False, server_default="xiaomao-illustrations"),
        sa.Column("cost_estimate", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_articles_user_id"),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_mp_accounts.id"], name="fk_wechat_mp_articles_account_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("wechat_mp_articles", ["user_id", "account_id", "status"])

    op.create_table(
        "wechat_mp_article_sections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("needs_image", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_article_sections_user_id"),
        sa.ForeignKeyConstraint(["article_id"], ["wechat_mp_articles.id"], name="fk_wechat_mp_article_sections_article_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("wechat_mp_article_sections", ["user_id", "article_id"])

    op.create_table(
        "wechat_mp_image_prompts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("section_id", sa.Integer(), nullable=False),
        sa.Column("skill_name", sa.String(length=80), nullable=False, server_default="xiaomao-illustrations"),
        sa.Column("skill_version", sa.String(length=32), nullable=False, server_default="v1.0.0"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("editable_prompt", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="prompt_ready"),
        sa.Column("cost_estimate", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_image_prompts_user_id"),
        sa.ForeignKeyConstraint(["article_id"], ["wechat_mp_articles.id"], name="fk_wechat_mp_image_prompts_article_id"),
        sa.ForeignKeyConstraint(["section_id"], ["wechat_mp_article_sections.id"], name="fk_wechat_mp_image_prompts_section_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("wechat_mp_image_prompts", ["user_id", "article_id", "status"])

    op.create_table(
        "wechat_mp_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("public_url", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("skill_name", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="generated"),
        sa.Column("provider_response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_assets_user_id"),
        sa.ForeignKeyConstraint(["article_id"], ["wechat_mp_articles.id"], name="fk_wechat_mp_assets_article_id"),
        sa.ForeignKeyConstraint(["prompt_id"], ["wechat_mp_image_prompts.id"], name="fk_wechat_mp_assets_prompt_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("wechat_mp_assets", ["user_id", "article_id", "prompt_id", "status"])

    op.create_table(
        "wechat_mp_draft_syncs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("wechat_media_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="synced"),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_draft_syncs_user_id"),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_mp_accounts.id"], name="fk_wechat_mp_draft_syncs_account_id"),
        sa.ForeignKeyConstraint(["article_id"], ["wechat_mp_articles.id"], name="fk_wechat_mp_draft_syncs_article_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("wechat_mp_draft_syncs", ["user_id", "account_id", "article_id", "status"])

    op.create_table(
        "wechat_mp_publish_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("draft_sync_id", sa.Integer(), nullable=False),
        sa.Column("publish_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="scheduled"),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_wechat_mp_publish_jobs_user_id"),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_mp_accounts.id"], name="fk_wechat_mp_publish_jobs_account_id"),
        sa.ForeignKeyConstraint(["article_id"], ["wechat_mp_articles.id"], name="fk_wechat_mp_publish_jobs_article_id"),
        sa.ForeignKeyConstraint(["draft_sync_id"], ["wechat_mp_draft_syncs.id"], name="fk_wechat_mp_publish_jobs_draft_sync_id"),
        sa.PrimaryKeyConstraint("id"),
    )
    _create_indexes("wechat_mp_publish_jobs", ["user_id", "account_id", "article_id", "draft_sync_id", "status"])


def downgrade() -> None:
    for table_name, columns in (
        ("wechat_mp_publish_jobs", ["status", "draft_sync_id", "article_id", "account_id", "user_id"]),
        ("wechat_mp_draft_syncs", ["status", "article_id", "account_id", "user_id"]),
        ("wechat_mp_assets", ["status", "prompt_id", "article_id", "user_id"]),
        ("wechat_mp_image_prompts", ["status", "article_id", "user_id"]),
        ("wechat_mp_article_sections", ["article_id", "user_id"]),
        ("wechat_mp_articles", ["status", "account_id", "user_id"]),
        ("wechat_mp_accounts", ["user_id"]),
    ):
        for column in columns:
            op.drop_index(f"ix_{table_name}_{column}", table_name=table_name)
        op.drop_table(table_name)
