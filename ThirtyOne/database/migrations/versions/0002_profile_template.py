"""profile card template setting

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("player_profiles")}
    if "profile_template" not in cols:          # fresh installs already get it from 0001's create_all
        with op.batch_alter_table("player_profiles") as b:
            b.add_column(sa.Column("profile_template", sa.String(10), nullable=False, server_default="face"))


def downgrade() -> None:
    with op.batch_alter_table("player_profiles") as b:
        b.drop_column("profile_template")
