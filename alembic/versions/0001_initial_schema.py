"""Initial WeraqamBot V2 schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-04
"""
from alembic import op

from app.database.base import Base
from app.database import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Metadata-driven baseline keeps the initial schema exactly aligned with ORM models.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
