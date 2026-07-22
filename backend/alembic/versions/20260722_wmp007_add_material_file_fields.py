"""add wechat mp material file fields

Revision ID: 20260722_wmp007
Revises: 20260722_wmp006
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_wmp007"
down_revision: Union[str, None] = "20260722_wmp006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wechat_mp_materials", sa.Column("file_name", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("wechat_mp_materials", sa.Column("original_file_name", sa.String(length=255), nullable=False, server_default=""))
    op.add_column("wechat_mp_materials", sa.Column("file_path", sa.Text(), nullable=False, server_default=""))
    op.add_column("wechat_mp_materials", sa.Column("download_url", sa.Text(), nullable=False, server_default=""))
    op.add_column("wechat_mp_materials", sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("wechat_mp_materials", sa.Column("mime_type", sa.String(length=128), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("wechat_mp_materials", "mime_type")
    op.drop_column("wechat_mp_materials", "file_size")
    op.drop_column("wechat_mp_materials", "download_url")
    op.drop_column("wechat_mp_materials", "file_path")
    op.drop_column("wechat_mp_materials", "original_file_name")
    op.drop_column("wechat_mp_materials", "file_name")
