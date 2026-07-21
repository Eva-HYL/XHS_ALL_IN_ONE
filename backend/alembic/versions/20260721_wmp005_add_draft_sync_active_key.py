"""scope active operation keys to account article revision

Revision ID: 20260721_wmp005
Revises: 20260721_wmp004
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260721_wmp005"
down_revision: Union[str, None] = "20260721_wmp004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "wechat_mp_draft_syncs",
        sa.Column("active_key", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_wechat_mp_draft_syncs_active_key",
        "wechat_mp_draft_syncs",
        ["active_key"],
        unique=True,
    )
    with op.batch_alter_table("wechat_mp_publish_jobs") as batch_op:
        batch_op.alter_column(
            "active_key",
            existing_type=sa.String(length=160),
            type_=sa.String(length=200),
            existing_nullable=True,
        )

    connection = op.get_bind()
    pending_drafts = connection.execute(sa.text("""
        SELECT id, account_id, article_id, article_revision
        FROM wechat_mp_draft_syncs
        WHERE status = 'pending'
        ORDER BY id
    """)).mappings().all()
    claimed_draft_keys: set[str] = set()
    for row in pending_drafts:
        active_key = (
            f"account:{row['account_id']}:article:{row['article_id']}:"
            f"revision:{row['article_revision']}"
        )
        if active_key in claimed_draft_keys:
            connection.execute(
                sa.text("""
                    UPDATE wechat_mp_draft_syncs
                    SET status = 'failed',
                        error_message = 'Duplicate pending draft sync removed during active-key migration'
                    WHERE id = :draft_sync_id
                """),
                {"draft_sync_id": row["id"]},
            )
            continue
        connection.execute(
            sa.text("UPDATE wechat_mp_draft_syncs SET active_key = :active_key WHERE id = :draft_sync_id"),
            {"active_key": active_key, "draft_sync_id": row["id"]},
        )
        claimed_draft_keys.add(active_key)

    active_rows = connection.execute(sa.text("""
        SELECT jobs.id, jobs.account_id, jobs.article_id, syncs.article_revision
        FROM wechat_mp_publish_jobs AS jobs
        JOIN wechat_mp_draft_syncs AS syncs ON syncs.id = jobs.draft_sync_id
        WHERE jobs.status IN ('scheduled', 'pending', 'submitted', 'publishing')
        ORDER BY jobs.id
    """)).mappings().all()
    claimed_keys: set[str] = set()
    connection.execute(sa.text("UPDATE wechat_mp_publish_jobs SET active_key = NULL"))
    for row in active_rows:
        active_key = (
            f"account:{row['account_id']}:article:{row['article_id']}:"
            f"revision:{row['article_revision']}"
        )
        if active_key in claimed_keys:
            connection.execute(
                sa.text("""
                    UPDATE wechat_mp_publish_jobs
                    SET status = 'cancelled',
                        error_message = 'Duplicate active publish job removed during active-key migration'
                    WHERE id = :job_id
                """),
                {"job_id": row["id"]},
            )
            continue
        connection.execute(
            sa.text("UPDATE wechat_mp_publish_jobs SET active_key = :active_key WHERE id = :job_id"),
            {"active_key": active_key, "job_id": row["id"]},
        )
        claimed_keys.add(active_key)


def downgrade() -> None:
    connection = op.get_bind()
    active_rows = connection.execute(sa.text("""
        SELECT id, draft_sync_id
        FROM wechat_mp_publish_jobs
        WHERE status IN ('scheduled', 'pending', 'submitted', 'publishing')
        ORDER BY id
    """)).mappings().all()
    connection.execute(sa.text("UPDATE wechat_mp_publish_jobs SET active_key = NULL"))
    for row in active_rows:
        connection.execute(
            sa.text("UPDATE wechat_mp_publish_jobs SET active_key = :active_key WHERE id = :job_id"),
            {"active_key": f"draft:{row['draft_sync_id']}", "job_id": row["id"]},
        )
    with op.batch_alter_table("wechat_mp_publish_jobs") as batch_op:
        batch_op.alter_column(
            "active_key",
            existing_type=sa.String(length=200),
            type_=sa.String(length=160),
            existing_nullable=True,
        )
    op.drop_index("ix_wechat_mp_draft_syncs_active_key", table_name="wechat_mp_draft_syncs")
    op.drop_column("wechat_mp_draft_syncs", "active_key")
