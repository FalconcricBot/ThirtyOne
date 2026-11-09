"""31 Card Game: tournaments.game column + the thirty_one_* tables

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

from database.models import Base

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # new tables (checkfirst: safe on fresh installs where 0001 already created everything)
    Base.metadata.create_all(bind=bind)
    cols = {c["name"] for c in sa.inspect(bind).get_columns("tournaments")}
    if "game" not in cols:
        with op.batch_alter_table("tournaments") as b:
            b.add_column(sa.Column("game", sa.String(12), nullable=False, server_default="briscola"))


def downgrade() -> None:
    for t in ("thirty_one_game_history", "thirty_one_statistics", "thirty_one_rounds", "thirty_one_moves",
              "thirty_one_players", "thirty_one_games"):
        op.drop_table(t)
    with op.batch_alter_table("tournaments") as b:
        b.drop_column("game")
