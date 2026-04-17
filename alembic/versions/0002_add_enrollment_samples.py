"""Add enrollment_samples table

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enrollment_samples",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("worker_id", sqlmodel.sql.sqltypes.AutoString(), sa.ForeignKey("worker_profiles.worker_id"), nullable=False, index=True),
        sa.Column("audio_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("transcribed_text", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("audio_deleted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("audio_deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("enrollment_samples")
