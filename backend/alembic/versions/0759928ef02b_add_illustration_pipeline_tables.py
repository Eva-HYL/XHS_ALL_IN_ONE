"""add illustration pipeline tables

Revision ID: 0759928ef02b
Revises: 60cd5c95fde1
Create Date: 2026-07-17 23:30:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0759928ef02b'
down_revision: Union[str, None] = '60cd5c95fde1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'characters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('slug', sa.String(length=128), nullable=False),
        sa.Column('ip_definition', sa.Text(), nullable=False, server_default=''),
        sa.Column('reference_image_asset_ids', sa.JSON(), nullable=False),
        sa.Column('created_via', sa.String(length=32), nullable=False, server_default='text_only'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_characters_user_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_characters_user_id', 'characters', ['user_id'])
    op.create_index('ix_characters_slug', 'characters', ['slug'])

    op.create_table(
        'illustration_assets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=True),
        sa.Column('role', sa.String(length=32), nullable=False, server_default='illustration'),
        sa.Column('pipeline_run_id', sa.String(length=64), nullable=True),
        sa.Column('shot_seq', sa.Integer(), nullable=True),
        sa.Column('prompt', sa.Text(), nullable=False, server_default=''),
        sa.Column('model', sa.String(length=128), nullable=False, server_default=''),
        sa.Column('size', sa.String(length=32), nullable=False, server_default='1024x1024'),
        sa.Column('reference_asset_ids', sa.JSON(), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False, server_default=''),
        sa.Column('provider_raw', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_illustration_assets_user_id'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], name='fk_illustration_assets_character_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_illustration_assets_user_id', 'illustration_assets', ['user_id'])
    op.create_index('ix_illustration_assets_character_id', 'illustration_assets', ['character_id'])
    op.create_index('ix_illustration_assets_role', 'illustration_assets', ['role'])
    op.create_index('ix_illustration_assets_pipeline_run_id', 'illustration_assets', ['pipeline_run_id'])
    op.create_index('ix_illustration_assets_created_at', 'illustration_assets', ['created_at'])

    op.create_table(
        'usage_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('pipeline_run_id', sa.String(length=64), nullable=True),
        sa.Column('step', sa.String(length=32), nullable=False),
        sa.Column('model', sa.String(length=128), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('image_count', sa.Integer(), nullable=True),
        sa.Column('unit_price_snapshot', sa.JSON(), nullable=True),
        sa.Column('cost_yuan', sa.Numeric(10, 4), nullable=False, server_default='0.0000'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_usage_records_user_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_usage_records_user_id', 'usage_records', ['user_id'])
    op.create_index('ix_usage_records_pipeline_run_id', 'usage_records', ['pipeline_run_id'])
    op.create_index('ix_usage_records_created_at', 'usage_records', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_usage_records_created_at', table_name='usage_records')
    op.drop_index('ix_usage_records_pipeline_run_id', table_name='usage_records')
    op.drop_index('ix_usage_records_user_id', table_name='usage_records')
    op.drop_table('usage_records')

    op.drop_index('ix_illustration_assets_created_at', table_name='illustration_assets')
    op.drop_index('ix_illustration_assets_pipeline_run_id', table_name='illustration_assets')
    op.drop_index('ix_illustration_assets_role', table_name='illustration_assets')
    op.drop_index('ix_illustration_assets_character_id', table_name='illustration_assets')
    op.drop_index('ix_illustration_assets_user_id', table_name='illustration_assets')
    op.drop_table('illustration_assets')

    op.drop_index('ix_characters_slug', table_name='characters')
    op.drop_index('ix_characters_user_id', table_name='characters')
    op.drop_table('characters')
