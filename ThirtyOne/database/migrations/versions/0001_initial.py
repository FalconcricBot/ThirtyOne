"""initial schema

Revision ID: 0001
Revises:
"""
from alembic import op

from database.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Baseline: creates every table from the models (checkfirst, so safe on an existing DB).
    # Future schema changes: `alembic revision --autogenerate -m "describe change"`.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
