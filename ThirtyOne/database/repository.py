"""All database access. Every public method opens its own short transaction and returns plain
dicts/lists (never ORM objects), so handlers never touch a detached session."""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy import case, delete, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from config import settings
from database.models import (Achievement, AdminLog, BannedUser, BotSetting, Friendship, Game, GameCard,
                             GameHistory, GameMove, GamePlayer, PlayerProfile, PlayerReward,
                             PlayerStatistics, ThirtyOneGame, ThirtyOneGameHistory, Tournament, TournamentPlayer, User)
from database.repository_31 import ThirtyOneRepo
from utils.helpers import clean_name, utcnow

log = logging.getLogger(__name__)


class Repo(ThirtyOneRepo):
    def __init__(self, session_factory):
        self.sf = session_factory

    # ------------------------------------------------------------ users
    async def upsert_user(self, tg_id: int, username: str | None, display_name: str) -> tuple[dict, bool]:
        name = clean_name(display_name, "Player", 100)
        async with self.sf() as s:
            u = await s.get(User, tg_id)
            if u is not None:
                now = utcnow()
                if u.username != username or u.display_name != name or (now - u.last_seen).total_seconds() > 60:
                    u.username, u.display_name, u.last_seen = username, name, now
                    await s.commit()
                return {"id": u.id, "player_no": u.player_no}, False
            last_err = None
            for attempt in range(3):
                n = (await s.execute(select(func.coalesce(func.max(User.player_no), 10000)))).scalar_one() + 1
                try:
                    s.add(User(id=tg_id, player_no=n, username=username, display_name=name))
                    await s.flush()                      # parent row first, so the foreign keys below are valid
                    s.add(PlayerProfile(user_id=tg_id, hand_images=settings.default_images,
                                        table_images=settings.default_images))
                    s.add(PlayerStatistics(user_id=tg_id))
                    await s.commit()
                    return {"id": tg_id, "player_no": n}, True
                except IntegrityError as e:
                    last_err = getattr(e, "orig", e)
                    log.warning("creating user %s failed (attempt %s): %s", tg_id, attempt + 1, last_err)
                    await s.rollback()
                    u = await s.get(User, tg_id)         # someone else created it first (double /start)
                    if u:
                        return {"id": u.id, "player_no": u.player_no}, False
            raise RuntimeError(f"could not create user {tg_id}: {last_err}")

    async def get_player(self, uid: int) -> dict | None:
        async with self.sf() as s:
            r = (await s.execute(
                select(User, PlayerProfile, PlayerStatistics)
                .join(PlayerProfile, PlayerProfile.user_id == User.id)
                .join(PlayerStatistics, PlayerStatistics.user_id == User.id)
                .where(User.id == uid))).first()
        if not r:
            return None
        u, p, st = r
        return {"id": u.id, "player_no": u.player_no, "username": u.username, "display_name": u.display_name,
                "created_at": u.created_at, "xp": p.xp, "coins": p.coins, "win_streak": p.win_streak,
                "best_streak": p.best_streak, "daily_streak": p.daily_streak, "last_daily": p.last_daily,
                "tournament_wins": p.tournament_wins, "hand_images": p.hand_images,
                "table_images": p.table_images, "notify": p.notify, "profile_template": p.profile_template, "matches": st.matches, "wins": st.wins,
                "losses": st.losses, "draws": st.draws, "total_points": st.total_points,
                "highest_score": st.highest_score, "practice_matches": st.practice_matches}

    async def display_name(self, uid: int) -> str:
        async with self.sf() as s:
            u = await s.get(User, uid)
            return u.display_name if u else f"Player {uid}"

    async def find_users(self, query: str, limit: int = 8) -> list[dict]:
        q = query.strip().lstrip("@")
        if not q:
            return []
        async with self.sf() as s:
            rows = (await s.execute(
                select(User.id, User.display_name, User.username).where(
                    or_(func.lower(User.username) == q.lower(), User.display_name.ilike(f"%{q}%")))
                .order_by(User.last_seen.desc()).limit(limit))).all()
        return [{"id": r.id, "name": r.display_name, "username": r.username} for r in rows]

    async def update_settings(self, uid: int, **fields) -> None:
        allowed = {"hand_images", "table_images", "notify", "profile_template"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if fields.get("profile_template") not in (None, "face", "arena", "vip", "owner", "owner_card"):
            fields.pop("profile_template")
        if fields:
            async with self.sf() as s:
                await s.execute(update(PlayerProfile).where(PlayerProfile.user_id == uid).values(**fields))
                await s.commit()

    async def add_rewards(self, uid: int, coins: int = 0, xp: int = 0) -> None:
        async with self.sf() as s:
            await s.execute(update(PlayerProfile).where(PlayerProfile.user_id == uid)
                            .values(coins=PlayerProfile.coins + coins, xp=PlayerProfile.xp + xp))
            await s.commit()

    # ------------------------------------------------------------ bans / admin
    async def is_banned(self, uid: int) -> bool:
        async with self.sf() as s:
            return (await s.get(BannedUser, uid)) is not None

    async def ban(self, uid: int, reason: str, admin_id: int) -> None:
        async with self.sf() as s:
            if await s.get(BannedUser, uid) is None:
                s.add(BannedUser(user_id=uid, reason=reason[:200], banned_by=admin_id))
                await s.commit()

    async def unban(self, uid: int) -> bool:
        async with self.sf() as s:
            r = await s.execute(delete(BannedUser).where(BannedUser.user_id == uid))
            await s.commit()
            return r.rowcount > 0

    async def log_admin(self, admin_id: int, action: str, details: str = "") -> None:
        async with self.sf() as s:
            s.add(AdminLog(admin_id=admin_id, action=action[:40], details=details[:400]))
            await s.commit()

    async def admin_logs(self, n: int = 15) -> list[dict]:
        async with self.sf() as s:
            rows = (await s.execute(select(AdminLog).order_by(AdminLog.id.desc()).limit(n))).scalars().all()
        return [{"admin_id": r.admin_id, "action": r.action, "details": r.details, "at": r.created_at} for r in rows]

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self.sf() as s:
            r = await s.get(BotSetting, key)
            return r.value if r else default

    async def set_setting(self, key: str, value: str) -> None:
        async with self.sf() as s:
            r = await s.get(BotSetting, key)
            if r:
                r.value = value
            else:
                s.add(BotSetting(key=key, value=value))
            await s.commit()

    async def all_user_ids(self) -> list[int]:
        async with self.sf() as s:
            return list((await s.execute(select(User.id))).scalars().all())

    async def counts(self) -> dict:
        day = utcnow() - timedelta(days=1)
        async with self.sf() as s:
            def cnt(stmt):
                return s.execute(stmt)
            users = (await cnt(select(func.count()).select_from(User))).scalar_one()
            active = (await cnt(select(func.count()).select_from(User).where(User.last_seen >= day))).scalar_one()
            new = (await cnt(select(func.count()).select_from(User).where(User.created_at >= day))).scalar_one()
            live = (await cnt(select(func.count()).select_from(Game).where(Game.status == "active"))).scalar_one()
            done = (await cnt(select(func.count()).select_from(Game).where(Game.status == "finished"))).scalar_one()
            tours = (await cnt(select(func.count()).select_from(Tournament))).scalar_one()
            banned = (await cnt(select(func.count()).select_from(BannedUser))).scalar_one()
        return {"users": users, "active_24h": active, "new_24h": new, "games_active": live,
                "games_done": done, "tournaments": tours, "banned": banned}

    # ------------------------------------------------------------ games
    async def create_game(self, *, mode: int, kind: str, seed: int, state: dict, players: list[dict],
                          room_code: str | None, group_chat_id: int | None, tournament_id: int | None = None,
                          tournament_match: str | None = None) -> int:
        async with self.sf() as s:
            g = Game(mode=mode, kind=kind, seed=seed, state_json=json.dumps(state), room_code=room_code,
                     group_chat_id=group_chat_id, tournament_id=tournament_id, tournament_match=tournament_match)
            s.add(g)
            await s.flush()
            for p in players:
                s.add(GamePlayer(game_id=g.id, seat=p["seat"], user_id=p["user_id"], display_name=p["name"][:64],
                                 ai_level=p.get("ai_level")))
            await s.commit()
            return g.id

    async def record_move(self, game_id: int, move_no: int, seat: int, card: str, state: dict) -> None:
        async with self.sf() as s:
            s.add(GameMove(game_id=game_id, move_no=move_no, seat=seat, card=card))
            await s.execute(update(Game).where(Game.id == game_id).values(state_json=json.dumps(state)))
            await s.commit()

    async def save_state(self, game_id: int, state: dict) -> None:
        async with self.sf() as s:
            await s.execute(update(Game).where(Game.id == game_id).values(state_json=json.dumps(state)))
            await s.commit()

    async def set_group_message(self, game_id: int, chat_id: int | None, msg_id: int | None) -> None:
        async with self.sf() as s:
            await s.execute(update(Game).where(Game.id == game_id)
                            .values(group_chat_id=chat_id, group_msg_id=msg_id))
            await s.commit()

    async def finish_game(self, game_id: int, state: dict, winner_sides: list[int], scores: list[int],
                          captured: list[list[str]], status: str = "finished") -> None:
        async with self.sf() as s:
            await s.execute(update(Game).where(Game.id == game_id).values(
                state_json=json.dumps(state), status=status, finished_at=utcnow(),
                winner_sides=",".join(map(str, winner_sides)), scores_json=json.dumps(scores)))
            for seat, pile in enumerate(captured):
                for c in pile:
                    s.add(GameCard(game_id=game_id, seat=seat, card=c))
            await s.commit()

    async def cancel_game(self, game_id: int) -> None:
        async with self.sf() as s:
            await s.execute(update(Game).where(Game.id == game_id).values(status="cancelled", finished_at=utcnow()))
            await s.commit()

    def _game_dict(self, g: Game, players: list[GamePlayer]) -> dict:
        return {"id": g.id, "mode": g.mode, "kind": g.kind, "status": g.status, "room_code": g.room_code,
                "seed": g.seed, "state": json.loads(g.state_json), "group_chat_id": g.group_chat_id,
                "group_msg_id": g.group_msg_id, "tournament_id": g.tournament_id,
                "tournament_match": g.tournament_match, "scores": json.loads(g.scores_json) if g.scores_json else None,
                "winner_sides": [int(x) for x in g.winner_sides.split(",")] if g.winner_sides else [],
                "finished_at": g.finished_at,
                "players": [{"seat": p.seat, "user_id": p.user_id, "name": p.display_name, "ai_level": p.ai_level}
                            for p in sorted(players, key=lambda x: x.seat)]}

    async def get_game(self, game_id: int) -> dict | None:
        async with self.sf() as s:
            g = await s.get(Game, game_id)
            if not g:
                return None
            ps = (await s.execute(select(GamePlayer).where(GamePlayer.game_id == game_id))).scalars().all()
            d = self._game_dict(g, ps)
            moves = (await s.execute(select(GameMove).where(GameMove.game_id == game_id)
                                     .order_by(GameMove.move_no))).scalars().all()
            d["moves"] = [[m.seat, m.card] for m in moves]
            return d

    async def load_active_games(self) -> list[dict]:
        async with self.sf() as s:
            games = (await s.execute(select(Game).where(Game.status == "active"))).scalars().all()
            out = []
            for g in games:
                ps = (await s.execute(select(GamePlayer).where(GamePlayer.game_id == g.id))).scalars().all()
                out.append(self._game_dict(g, ps))
            return out

    async def apply_game_result(self, uid: int, *, game_id: int, result: str, points: int, mode: int,
                                kind: str, opponents: str, xp: int, coins: int) -> dict | None:
        """One transaction: history row + stats + streak + xp/coins. None if already recorded."""
        async with self.sf() as s:
            prof = await s.get(PlayerProfile, uid)
            st = await s.get(PlayerStatistics, uid)
            if prof is None or st is None:
                return None
            old_xp = prof.xp
            s.add(GameHistory(user_id=uid, game_id=game_id, result=result, points=points, mode=mode, kind=kind,
                              opponents=opponents, xp_gained=xp, coins_gained=coins))
            try:
                await s.flush()
            except IntegrityError:
                await s.rollback()
                return None
            if kind == "practice":
                st.practice_matches += 1
            else:
                st.matches += 1
                st.total_points += points
                st.highest_score = max(st.highest_score, points)
                if result == "win":
                    st.wins += 1
                    prof.win_streak += 1
                    prof.best_streak = max(prof.best_streak, prof.win_streak)
                elif result == "loss":
                    st.losses += 1
                    prof.win_streak = 0
                else:
                    st.draws += 1
            prof.xp += xp
            prof.coins += coins
            await s.commit()
            return {"old_xp": old_xp, "new_xp": prof.xp, "win_streak": prof.win_streak,
                    "best_streak": prof.best_streak, "coins_total": prof.coins}

    async def user_history(self, uid: int, limit: int = 8, offset: int = 0) -> tuple[list[dict], int]:
        async with self.sf() as s:
            total = (await s.execute(select(func.count()).select_from(GameHistory)
                                     .where(GameHistory.user_id == uid))).scalar_one()
            rows = (await s.execute(select(GameHistory).where(GameHistory.user_id == uid)
                                    .order_by(GameHistory.finished_at.desc(), GameHistory.id.desc())
                                    .limit(limit).offset(offset))).scalars().all()
        return [{"game_id": r.game_id, "result": r.result, "points": r.points, "mode": r.mode, "kind": r.kind,
                 "opponents": r.opponents, "xp": r.xp_gained, "at": r.finished_at} for r in rows], total

    async def recent_opponents(self, uid: int, limit: int = 8) -> list[dict]:
        t = func.max(GameHistory.finished_at).label("t")
        async with self.sf() as s:
            rows = (await s.execute(
                select(GamePlayer.user_id, User.display_name, User.username, t)
                .join(GameHistory, GameHistory.game_id == GamePlayer.game_id)
                .join(User, User.id == GamePlayer.user_id)
                .where(GameHistory.user_id == uid, GamePlayer.user_id.is_not(None), GamePlayer.user_id != uid)
                .group_by(GamePlayer.user_id, User.display_name, User.username)
                .order_by(desc("t")).limit(limit))).all()
        return [{"id": r[0], "name": r[1], "username": r[2]} for r in rows]

    # ------------------------------------------------------------ leaderboards
    def _lb_stmt(self, kind: str, user_ids: list[int] | None):
        if kind in ("week", "month"):
            since = utcnow() - timedelta(days=7 if kind == "week" else 30)
            val = func.sum(GameHistory.xp_gained).label("value")
            stmt = (select(User.id.label("uid"), User.display_name.label("name"), val)
                    .join(GameHistory, GameHistory.user_id == User.id)
                    .where(GameHistory.finished_at >= since, GameHistory.kind != "practice")
                    .group_by(User.id, User.display_name).having(val > 0))
            return stmt, val
        if kind == "winpct":
            val = (PlayerStatistics.wins * 100.0 / PlayerStatistics.matches).label("value")
            stmt = (select(User.id.label("uid"), User.display_name.label("name"), val)
                    .join(PlayerStatistics, PlayerStatistics.user_id == User.id)
                    .where(PlayerStatistics.matches >= 10))
            return stmt, val
        col = {"streak": PlayerProfile.best_streak, "tour": PlayerProfile.tournament_wins}.get(kind, PlayerProfile.xp)
        val = col.label("value")
        stmt = select(User.id.label("uid"), User.display_name.label("name"), val).join(
            PlayerProfile, PlayerProfile.user_id == User.id)
        if kind in ("streak", "tour"):
            stmt = stmt.where(col > 0)
        if kind == "friends" and user_ids is not None:
            stmt = stmt.where(User.id.in_(user_ids))
        return stmt, val

    async def leaderboard(self, kind: str, limit: int, offset: int,
                          user_ids: list[int] | None = None) -> tuple[list[dict], int]:
        stmt, val = self._lb_stmt(kind, user_ids)
        async with self.sf() as s:
            total = (await s.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
            rows = (await s.execute(stmt.order_by(desc("value"), User.id).limit(limit).offset(offset))).all()
        return [{"id": r.uid, "name": r.name, "value": r.value} for r in rows], total

    async def group_leaderboard(self, chat_id: int, game: str, limit: int = 10) -> list[dict]:
        """Ranking of the players who played matches *in this Telegram group* (practice games never count).
        game: 'briscola' | 'thirty_one'. Rows: id, name, xp, wins, games."""
        if game == "thirty_one":
            hist, g = ThirtyOneGameHistory, ThirtyOneGame
        else:
            hist, g = GameHistory, Game
        xp = func.sum(hist.xp_gained).label("xp")
        wins = func.sum(case((hist.result == "win", 1), else_=0)).label("wins")
        games = func.count(hist.id).label("games")
        stmt = (select(User.id.label("uid"), User.display_name.label("name"), xp, wins, games)
                .join(hist, hist.user_id == User.id).join(g, g.id == hist.game_id)
                .where(g.group_chat_id == chat_id, hist.kind != "practice")
                .group_by(User.id, User.display_name).order_by(desc("xp"), User.id).limit(limit))
        async with self.sf() as s:
            rows = (await s.execute(stmt)).all()
        return [{"id": r.uid, "name": r.name, "xp": int(r.xp or 0), "wins": int(r.wins or 0), "games": int(r.games)} for r in rows]

    # ------------------------------------------------------------ rewards
    async def mission_progress(self, uid: int, day: str, week: str) -> dict[str, tuple[int, bool]]:
        async with self.sf() as s:
            rows = (await s.execute(select(PlayerReward).where(
                PlayerReward.user_id == uid, PlayerReward.period.in_([day, week])))).scalars().all()
        return {r.key: (r.progress, r.claimed) for r in rows}

    async def add_progress(self, uid: int, key: str, period: str, value: int, mode: str = "add") -> None:
        async with self.sf() as s:
            r = (await s.execute(select(PlayerReward).where(
                PlayerReward.user_id == uid, PlayerReward.key == key, PlayerReward.period == period))).scalar_one_or_none()
            if r is None:
                s.add(PlayerReward(user_id=uid, key=key, period=period, progress=value))
            else:
                r.progress = r.progress + value if mode == "add" else max(r.progress, value)
            try:
                await s.commit()
            except IntegrityError:        # concurrent first insert - retry as update
                await s.rollback()
                await self.add_progress(uid, key, period, value, mode)

    async def claim_mission(self, uid: int, key: str, period: str, target: int) -> bool:
        async with self.sf() as s:
            r = (await s.execute(select(PlayerReward).where(
                PlayerReward.user_id == uid, PlayerReward.key == key, PlayerReward.period == period))).scalar_one_or_none()
            if r is None or r.claimed or r.progress < target:
                return False
            res = await s.execute(update(PlayerReward).where(PlayerReward.id == r.id, PlayerReward.claimed.is_(False))
                                  .values(claimed=True))
            await s.commit()
            return res.rowcount == 1          # atomic: only one concurrent claim succeeds

    async def set_daily(self, uid: int, today: str, streak: int, coins: int, xp: int) -> bool:
        async with self.sf() as s:
            res = await s.execute(update(PlayerProfile).where(
                PlayerProfile.user_id == uid, or_(PlayerProfile.last_daily.is_(None), PlayerProfile.last_daily != today))
                .values(last_daily=today, daily_streak=streak, coins=PlayerProfile.coins + coins,
                        xp=PlayerProfile.xp + xp))
            await s.commit()
            return res.rowcount == 1

    async def unlock(self, uid: int, code: str) -> bool:
        async with self.sf() as s:
            s.add(Achievement(user_id=uid, code=code))
            try:
                await s.commit()
                return True
            except IntegrityError:
                await s.rollback()
                return False

    async def achievements(self, uid: int) -> list[str]:
        async with self.sf() as s:
            return list((await s.execute(select(Achievement.code).where(Achievement.user_id == uid)
                                         .order_by(Achievement.unlocked_at))).scalars().all())

    # ------------------------------------------------------------ friends
    async def _pair(self, s, a: int, b: int):
        return (await s.execute(select(Friendship).where(
            or_((Friendship.user_id == a) & (Friendship.friend_id == b),
                (Friendship.user_id == b) & (Friendship.friend_id == a))))).scalars().all()

    async def is_blocked(self, a: int, b: int) -> bool:
        """True if either user blocked the other."""
        async with self.sf() as s:
            return any(r.status == "blocked" for r in await self._pair(s, a, b))

    async def friend_request(self, a: int, b: int) -> str:
        """-> 'sent' | 'accepted' (they had asked us first) | 'already' | 'blocked' | 'self'"""
        if a == b:
            return "self"
        async with self.sf() as s:
            rows = await self._pair(s, a, b)
            for r in rows:
                if r.status == "blocked":
                    return "blocked"
                if r.status == "accepted":
                    return "already"
                if r.status == "pending":
                    if r.user_id == b:           # they already asked us -> accept
                        r.status = "accepted"
                        await s.commit()
                        return "accepted"
                    return "already"
            s.add(Friendship(user_id=a, friend_id=b, status="pending"))
            await s.commit()
            return "sent"

    async def friend_accept(self, me: int, other: int) -> bool:
        async with self.sf() as s:
            r = (await s.execute(select(Friendship).where(
                Friendship.user_id == other, Friendship.friend_id == me, Friendship.status == "pending"))).scalar_one_or_none()
            if not r:
                return False
            r.status = "accepted"
            await s.commit()
            return True

    async def friend_remove(self, a: int, b: int) -> None:
        async with self.sf() as s:
            await s.execute(delete(Friendship).where(
                or_((Friendship.user_id == a) & (Friendship.friend_id == b),
                    (Friendship.user_id == b) & (Friendship.friend_id == a)),
                Friendship.status != "blocked"))
            await s.commit()

    async def block(self, me: int, other: int) -> None:
        async with self.sf() as s:
            await s.execute(delete(Friendship).where(
                or_((Friendship.user_id == me) & (Friendship.friend_id == other),
                    (Friendship.user_id == other) & (Friendship.friend_id == me))))
            s.add(Friendship(user_id=me, friend_id=other, status="blocked"))
            await s.commit()

    async def unblock(self, me: int, other: int) -> None:
        async with self.sf() as s:
            await s.execute(delete(Friendship).where(Friendship.user_id == me, Friendship.friend_id == other,
                                                     Friendship.status == "blocked"))
            await s.commit()

    async def friends(self, uid: int) -> list[dict]:
        async with self.sf() as s:
            rows = (await s.execute(select(Friendship).where(
                Friendship.status == "accepted", or_(Friendship.user_id == uid, Friendship.friend_id == uid)))).scalars().all()
            ids = [r.friend_id if r.user_id == uid else r.user_id for r in rows]
            if not ids:
                return []
            us = (await s.execute(select(User).where(User.id.in_(ids)).order_by(User.display_name))).scalars().all()
        return [{"id": u.id, "name": u.display_name, "username": u.username} for u in us]

    async def pending_requests(self, uid: int) -> list[dict]:
        async with self.sf() as s:
            rows = (await s.execute(select(User).join(Friendship, Friendship.user_id == User.id).where(
                Friendship.friend_id == uid, Friendship.status == "pending"))).scalars().all()
        return [{"id": u.id, "name": u.display_name, "username": u.username} for u in rows]

    async def blocked_list(self, uid: int) -> list[dict]:
        async with self.sf() as s:
            rows = (await s.execute(select(User).join(Friendship, Friendship.friend_id == User.id).where(
                Friendship.user_id == uid, Friendship.status == "blocked"))).scalars().all()
        return [{"id": u.id, "name": u.display_name} for u in rows]

    # ------------------------------------------------------------ tournaments
    def _t(self, t: Tournament, count: int | None = None) -> dict:
        return {"id": t.id, "name": t.name, "description": t.description, "capacity": t.capacity,
                "status": t.status, "register_until": t.register_until, "starts_at": t.starts_at,
                "created_by": t.created_by, "bracket": json.loads(t.bracket_json) if t.bracket_json else None,
                "winner_id": t.winner_id, "players": count, "game": t.game}

    async def create_tournament(self, *, name: str, description: str, capacity: int, register_until, starts_at,
                                created_by: int, game: str = "briscola") -> int:
        async with self.sf() as s:
            t = Tournament(name=name, description=description, capacity=capacity, register_until=register_until,
                           starts_at=starts_at, created_by=created_by, game=game)
            s.add(t)
            await s.commit()
            return t.id

    async def get_tournament(self, tid: int) -> dict | None:
        async with self.sf() as s:
            t = await s.get(Tournament, tid)
            if not t:
                return None
            n = (await s.execute(select(func.count()).select_from(TournamentPlayer).where(
                TournamentPlayer.tournament_id == tid, TournamentPlayer.status != "removed"))).scalar_one()
            return self._t(t, n)

    async def list_tournaments(self, statuses: list[str], limit: int = 10) -> list[dict]:
        async with self.sf() as s:
            ts = (await s.execute(select(Tournament).where(Tournament.status.in_(statuses))
                                  .order_by(Tournament.starts_at.desc()).limit(limit))).scalars().all()
            out = []
            for t in ts:
                n = (await s.execute(select(func.count()).select_from(TournamentPlayer).where(
                    TournamentPlayer.tournament_id == t.id, TournamentPlayer.status != "removed"))).scalar_one()
                out.append(self._t(t, n))
            return out

    async def set_tournament(self, tid: int, **fields) -> None:
        if "bracket" in fields:
            fields["bracket_json"] = json.dumps(fields.pop("bracket"))
        async with self.sf() as s:
            await s.execute(update(Tournament).where(Tournament.id == tid).values(**fields))
            await s.commit()

    async def tournament_players(self, tid: int, include_removed: bool = False) -> list[dict]:
        async with self.sf() as s:
            q = (select(TournamentPlayer.user_id, TournamentPlayer.status, User.display_name)
                 .join(User, User.id == TournamentPlayer.user_id).where(TournamentPlayer.tournament_id == tid)
                 .order_by(TournamentPlayer.joined_at))
            if not include_removed:
                q = q.where(TournamentPlayer.status != "removed")
            rows = (await s.execute(q)).all()
        return [{"user_id": r[0], "status": r[1], "name": r[2]} for r in rows]

    async def tournament_join(self, tid: int, uid: int) -> str:
        """-> 'ok' | 'full' | 'dup' | 'closed' | 'missing'"""
        async with self.sf() as s:
            t = await s.get(Tournament, tid)
            if not t:
                return "missing"
            if t.status != "registration" or utcnow() > t.register_until:
                return "closed"
            row = (await s.execute(select(TournamentPlayer).where(
                TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == uid))).scalar_one_or_none()
            if row and row.status != "removed":
                return "dup"
            n = (await s.execute(select(func.count()).select_from(TournamentPlayer).where(
                TournamentPlayer.tournament_id == tid, TournamentPlayer.status != "removed"))).scalar_one()
            if n >= t.capacity:
                return "full"
            if row:
                return "closed"            # an admin removed this player - they cannot rejoin
            s.add(TournamentPlayer(tournament_id=tid, user_id=uid))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                return "dup"
            return "ok"

    async def tournament_leave(self, tid: int, uid: int) -> bool:
        async with self.sf() as s:
            t = await s.get(Tournament, tid)
            if not t or t.status != "registration":
                return False
            res = await s.execute(delete(TournamentPlayer).where(
                TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == uid,
                TournamentPlayer.status == "registered"))
            await s.commit()
            return res.rowcount > 0

    async def set_tournament_player(self, tid: int, uid: int, status: str) -> bool:
        async with self.sf() as s:
            res = await s.execute(update(TournamentPlayer).where(
                TournamentPlayer.tournament_id == tid, TournamentPlayer.user_id == uid).values(status=status))
            await s.commit()
            return res.rowcount > 0

    async def add_tournament_win(self, uid: int) -> None:
        async with self.sf() as s:
            await s.execute(update(PlayerProfile).where(PlayerProfile.user_id == uid)
                            .values(tournament_wins=PlayerProfile.tournament_wins + 1))
            await s.commit()

    async def user_tournaments(self, uid: int, limit: int = 5) -> list[dict]:
        async with self.sf() as s:
            rows = (await s.execute(select(Tournament, TournamentPlayer.status).join(
                TournamentPlayer, TournamentPlayer.tournament_id == Tournament.id).where(
                TournamentPlayer.user_id == uid).order_by(Tournament.starts_at.desc()).limit(limit))).all()
        return [{**self._t(t), "my_status": st} for t, st in rows]
