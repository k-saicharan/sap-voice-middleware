"""Initial worker_profiles table with all columns

Revision ID: 0001
Revises:
Create Date: 2026-04-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_profiles",
        sa.Column("worker_id", sqlmodel.sql.sqltypes.AutoString(), primary_key=True),
        sa.Column("locale", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("mappings", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="{}"),
        sa.Column("gdpr_consent", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("gdpr_consent_at", sa.DateTime(), nullable=True),
        sa.Column("enrollment_status", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="none"),
        sa.Column("embedding", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("worker_profiles")
