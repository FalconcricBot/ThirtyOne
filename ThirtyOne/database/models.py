"""SQLAlchemy 2.0 models. User.id is the Telegram user id."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from utils.helpers import utcnow


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)  # Telegram ID
    player_no: Mapped[int] = mapped_column(Integer, unique=True)                        # public Player ID
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class PlayerProfile(Base):
    __tablename__ = "player_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    xp: Mapped[int] = mapped_column(Integer, default=0, index=True)
    coins: Mapped[int] = mapped_column(Integer, default=100)
    win_streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0, index=True)
    daily_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_daily: Mapped[str | None] = mapped_column(String(10))       # YYYY-MM-DD
    tournament_wins: Mapped[int] = mapped_column(Integer, default=0, index=True)
    hand_images: Mapped[bool] = mapped_column(Boolean, default=True)
    table_images: Mapped[bool] = mapped_column(Boolean, default=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    profile_template: Mapped[str] = mapped_column(String(10), default="face", server_default="face")  # face|arena|vip


class PlayerStatistics(Base):
    __tablename__ = "player_statistics"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    matches: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    total_points: Mapped[int] = mapped_column(Integer, default=0)
    highest_score: Mapped[int] = mapped_column(Integer, default=0)
    practice_matches: Mapped[int] = mapped_column(Integer, default=0)


class Game(Base):
    __tablename__ = "games"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_code: Mapped[str | None] = mapped_column(String(12), index=True)
    mode: Mapped[int] = mapped_column(Integer)                       # 2 or 4 players
    kind: Mapped[str] = mapped_column(String(16))                    # quick|room|practice|tournament
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)  # active|finished|cancelled
    seed: Mapped[int] = mapped_column(BigInteger)
    state_json: Mapped[str] = mapped_column(Text)
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    group_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id"), index=True)
    tournament_match: Mapped[str | None] = mapped_column(String(16))  # "round:index"
    winner_sides: Mapped[str | None] = mapped_column(String(16))      # e.g. "0" or "0,1"
    scores_json: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class GamePlayer(Base):
    __tablename__ = "game_players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    seat: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)  # NULL for AI
    display_name: Mapped[str] = mapped_column(String(64))
    ai_level: Mapped[str | None] = mapped_column(String(10))
    __table_args__ = (UniqueConstraint("game_id", "seat"),)


class GameMove(Base):
    __tablename__ = "game_moves"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    move_no: Mapped[int] = mapped_column(Integer)
    seat: Mapped[int] = mapped_column(Integer)
    card: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("game_id", "move_no"),)   # blocks duplicate move writes


class GameCard(Base):
    """Cards each seat captured, written when the game ends (audit / replay verification)."""
    __tablename__ = "game_cards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    seat: Mapped[int] = mapped_column(Integer)
    card: Mapped[str] = mapped_column(String(3))


class GameHistory(Base):
    __tablename__ = "game_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("games.id"), index=True)
    result: Mapped[str] = mapped_column(String(5))                   # win|loss|draw
    points: Mapped[int] = mapped_column(Integer)
    mode: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    opponents: Mapped[str] = mapped_column(String(200), default="")
    xp_gained: Mapped[int] = mapped_column(Integer, default=0)
    coins_gained: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    __table_args__ = (UniqueConstraint("user_id", "game_id"),)       # a result is recorded once


class Tournament(Base):
    __tablename__ = "tournaments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(300), default="")
    capacity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="registration", index=True)
    register_until: Mapped[datetime] = mapped_column(DateTime)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    bracket_json: Mapped[str | None] = mapped_column(Text)
    winner_id: Mapped[int | None] = mapped_column(BigInteger)
    game: Mapped[str] = mapped_column(String(12), default="briscola", server_default="briscola")  # briscola | thirty_one


class TournamentPlayer(Base):
    __tablename__ = "tournament_players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournaments.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="registered")  # registered|eliminated|winner|removed
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("tournament_id", "user_id"),)


class Achievement(Base):
    __tablename__ = "achievements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code: Mapped[str] = mapped_column(String(32))
    unlocked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "code"),)


class PlayerReward(Base):
    """Mission progress and claim state, one row per (user, mission key, period)."""
    __tablename__ = "player_rewards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    key: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(10))                  # day (YYYY-MM-DD) or week (YYYY-Www)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("user_id", "key", "period"),)


class Friendship(Base):
    __tablename__ = "friendships"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)     # requester / blocker
    friend_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(10))                  # pending|accepted|blocked
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("user_id", "friend_id"),)


class BannedUser(Base):
    __tablename__ = "banned_users"
    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    reason: Mapped[str] = mapped_column(String(200), default="")
    banned_by: Mapped[int] = mapped_column(BigInteger)
    banned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdminLog(Base):
    __tablename__ = "admin_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[str] = mapped_column(String(400), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class BotSetting(Base):
    __tablename__ = "bot_settings"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")




# ====================================================================== 31 CARD GAME
class ThirtyOneGame(Base):
    __tablename__ = "thirty_one_games"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_code: Mapped[str | None] = mapped_column(String(12), index=True)
    kind: Mapped[str] = mapped_column(String(16))                    # quick|room|practice|tournament
    mode: Mapped[str] = mapped_column(String(10))                    # lives|knockout|points
    status: Mapped[str] = mapped_column(String(12), default="active", index=True)
    seed: Mapped[int] = mapped_column(BigInteger)
    config_json: Mapped[str] = mapped_column(Text)
    state_json: Mapped[str] = mapped_column(Text)                    # full state incl. hands - never sent to chats
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    group_msg_id: Mapped[int | None] = mapped_column(BigInteger)
    tournament_id: Mapped[int | None] = mapped_column(ForeignKey("tournaments.id"), index=True)
    tournament_match: Mapped[str | None] = mapped_column(String(16))
    winner_seats: Mapped[str | None] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class ThirtyOnePlayer(Base):
    __tablename__ = "thirty_one_players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("thirty_one_games.id"), index=True)
    seat: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)   # NULL for AI
    display_name: Mapped[str] = mapped_column(String(64))
    ai_level: Mapped[str | None] = mapped_column(String(10))
    placement: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("game_id", "seat"),)


class ThirtyOneMove(Base):
    __tablename__ = "thirty_one_moves"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("thirty_one_games.id"), index=True)
    move_no: Mapped[int] = mapped_column(Integer)
    round_no: Mapped[int] = mapped_column(Integer)
    seat: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(10))                  # draw|take|discard|knock|declare
    card: Mapped[str | None] = mapped_column(String(3))              # only public cards (taken / discarded)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("game_id", "move_no"),)


class ThirtyOneRound(Base):
    __tablename__ = "thirty_one_rounds"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("thirty_one_games.id"), index=True)
    round_no: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(12))
    knocker: Mapped[int | None] = mapped_column(Integer)
    info_json: Mapped[str] = mapped_column(Text)                     # revealed hands + scores (public after the round)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("game_id", "round_no"),)


class ThirtyOneStatistics(Base):
    __tablename__ = "thirty_one_statistics"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    matches: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    times_31: Mapped[int] = mapped_column(Integer, default=0)
    knock_wins: Mapped[int] = mapped_column(Integer, default=0)
    knock_losses: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[float] = mapped_column(Float, default=0.0)
    win_streak: Mapped[int] = mapped_column(Integer, default=0)
    best_streak: Mapped[int] = mapped_column(Integer, default=0, index=True)
    practice_matches: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0, index=True)   # 31-only ranking points


class ThirtyOneGameHistory(Base):
    __tablename__ = "thirty_one_game_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    game_id: Mapped[int] = mapped_column(ForeignKey("thirty_one_games.id"), index=True)
    result: Mapped[str] = mapped_column(String(5))
    placement: Mapped[int] = mapped_column(Integer)
    players: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(16))
    rounds: Mapped[int] = mapped_column(Integer, default=0)
    best_score: Mapped[float] = mapped_column(Float, default=0.0)
    xp_gained: Mapped[int] = mapped_column(Integer, default=0)
    coins_gained: Mapped[int] = mapped_column(Integer, default=0)
    opponents: Mapped[str] = mapped_column(String(200), default="")
    finished_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    __table_args__ = (UniqueConstraint("user_id", "game_id"),)
Index("ix_game_history_user_time", GameHistory.user_id, GameHistory.finished_at)
