"""persist wechat prompt fingerprints

Revision ID: b7e2c4d6a8f0
Revises: a4c7e9d2f1b0
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e2c4d6a8f0"
down_revision = "a4c7e9d2f1b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "wechat_mp_article_sections",
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "wechat_mp_article_sections",
        sa.Column("analysis_version", sa.String(length=32), nullable=False, server_default=""),
    )
    op.add_column(
        "wechat_mp_image_prompts",
        sa.Column("generation_fingerprint", sa.String(length=64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("wechat_mp_image_prompts", "generation_fingerprint")
    op.drop_column("wechat_mp_article_sections", "analysis_version")
    op.drop_column("wechat_mp_article_sections", "source_fingerprint")
