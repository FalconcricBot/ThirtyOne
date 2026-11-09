"""Database access for the 31 Card Game (mixed into Repo). Plain dicts in / out, short transactions."""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError

from database.models import (PlayerProfile, ThirtyOneGame, ThirtyOneGameHistory, ThirtyOneMove, ThirtyOnePlayer,
                             ThirtyOneRound, ThirtyOneStatistics, User)
from utils.helpers import utcnow

STAT_FIELDS = ("matches", "wins", "losses", "draws", "rounds", "times_31", "knock_wins", "knock_losses",
               "best_score", "win_streak", "best_streak", "practice_matches", "xp")


class ThirtyOneRepo:
    # ------------------------------------------------------------ games
    async def t31_create_game(self, *, kind: str, mode: str, seed: int, config: dict, state: dict, players: list[dict],
                              room_code: str | None, group_chat_id: int | None, tournament_id: int | None = None,
                              tournament_match: str | None = None) -> int:
        async with self.sf() as s:
            g = ThirtyOneGame(kind=kind, mode=mode, seed=seed, config_json=json.dumps(config),
                              state_json=json.dumps(state), room_code=room_code, group_chat_id=group_chat_id,
                              tournament_id=tournament_id, tournament_match=tournament_match)
            s.add(g)
            await s.flush()
            for p in players:
                s.add(ThirtyOnePlayer(game_id=g.id, seat=p["seat"], user_id=p["user_id"],
                                      display_name=p["name"][:64], ai_level=p.get("ai_level")))
            await s.commit()
            return g.id

    async def t31_record_move(self, game_id: int, move_no: int, round_no: int, seat: int, action: str,
                              card: str | None, state: dict) -> None:
        async with self.sf() as s:
            s.add(ThirtyOneMove(game_id=game_id, move_no=move_no, round_no=round_no, seat=seat, action=action, card=card))
            await s.execute(update(ThirtyOneGame).where(ThirtyOneGame.id == game_id).values(state_json=json.dumps(state)))
            await s.commit()

    async def t31_save_state(self, game_id: int, state: dict) -> None:
        async with self.sf() as s:
            await s.execute(update(ThirtyOneGame).where(ThirtyOneGame.id == game_id).values(state_json=json.dumps(state)))
            await s.commit()

    async def t31_record_round(self, game_id: int, info: dict) -> None:
        async with self.sf() as s:
            s.add(ThirtyOneRound(game_id=game_id, round_no=info["no"], reason=info["reason"], knocker=info["knocker"],
                                 info_json=json.dumps(info)))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()

    async def t31_set_group_message(self, game_id: int, chat_id: int | None, msg_id: int | None) -> None:
        async with self.sf() as s:
            await s.execute(update(ThirtyOneGame).where(ThirtyOneGame.id == game_id)
                            .values(group_chat_id=chat_id, group_msg_id=msg_id))
            await s.commit()

    async def t31_finish_game(self, game_id: int, state: dict, winner_seats: list[int], placements: list[int]) -> None:
        async with self.sf() as s:
            await s.execute(update(ThirtyOneGame).where(ThirtyOneGame.id == game_id).values(
                state_json=json.dumps(state), status="finished", finished_at=utcnow(),
                winner_seats=",".join(map(str, winner_seats))))
            for seat, pl in enumerate(placements):
                await s.execute(update(ThirtyOnePlayer).where(ThirtyOnePlayer.game_id == game_id,
                                                              ThirtyOnePlayer.seat == seat).values(placement=pl))
            await s.commit()

    async def t31_cancel_game(self, game_id: int) -> None:
        async with self.sf() as s:
            await s.execute(update(ThirtyOneGame).where(ThirtyOneGame.id == game_id)
                            .values(status="cancelled", finished_at=utcnow()))
            await s.commit()

    def _t31_dict(self, g: ThirtyOneGame, players) -> dict:
        return {"id": g.id, "kind": g.kind, "mode": g.mode, "status": g.status, "room_code": g.room_code, "seed": g.seed,
                "config": json.loads(g.config_json), "state": json.loads(g.state_json),
                "group_chat_id": g.group_chat_id, "group_msg_id": g.group_msg_id, "tournament_id": g.tournament_id,
                "tournament_match": g.tournament_match,
                "winner_seats": [int(x) for x in g.winner_seats.split(",")] if g.winner_seats else [],
                "players": [{"seat": p.seat, "user_id": p.user_id, "name": p.display_name, "ai_level": p.ai_level,
                             "placement": p.placement} for p in sorted(players, key=lambda x: x.seat)]}

    async def t31_get_game(self, game_id: int) -> dict | None:
        async with self.sf() as s:
            g = await s.get(ThirtyOneGame, game_id)
            if not g:
                return None
            ps = (await s.execute(select(ThirtyOnePlayer).where(ThirtyOnePlayer.game_id == game_id))).scalars().all()
            return self._t31_dict(g, ps)

    async def t31_load_active_games(self) -> list[dict]:
        async with self.sf() as s:
            games = (await s.execute(select(ThirtyOneGame).where(ThirtyOneGame.status == "active"))).scalars().all()
            out = []
            for g in games:
                ps = (await s.execute(select(ThirtyOnePlayer).where(ThirtyOnePlayer.game_id == g.id))).scalars().all()
                out.append(self._t31_dict(g, ps))
            return out

    # ------------------------------------------------------------ statistics
    async def t31_apply_result(self, uid: int, *, game_id: int, result: str, placement: int, players: int, mode: str,
                               kind: str, rounds: int, best_score: float, times_31: int, knock_wins: int,
                               knock_losses: int, xp: int, coins: int, opponents: str) -> dict | None:
        """One transaction: history row + 31 stats + shared xp/coins. None if this result was already recorded."""
        async with self.sf() as s:
            prof = await s.get(PlayerProfile, uid)
            if prof is None:
                return None
            st = await s.get(ThirtyOneStatistics, uid)
            if st is None:
                st = ThirtyOneStatistics(user_id=uid, matches=0, wins=0, losses=0, draws=0, rounds=0, times_31=0,
                                         knock_wins=0, knock_losses=0, best_score=0.0, win_streak=0, best_streak=0,
                                         practice_matches=0, xp=0)
                s.add(st)
                await s.flush()
            old_xp = prof.xp
            s.add(ThirtyOneGameHistory(user_id=uid, game_id=game_id, result=result, placement=placement, players=players,
                                       mode=mode, kind=kind, rounds=rounds, best_score=best_score, xp_gained=xp,
                                       coins_gained=coins, opponents=opponents))
            try:
                await s.flush()
            except IntegrityError:
                await s.rollback()
                return None
            if kind == "practice":
                st.practice_matches += 1
            else:
                st.matches += 1
                st.rounds += rounds
                st.times_31 += times_31
                st.knock_wins += knock_wins
                st.knock_losses += knock_losses
                st.best_score = max(st.best_score, best_score)
                st.xp += xp                                    # practice never feeds the rankings
                if result == "win":
                    st.wins += 1
                    st.win_streak += 1
                    st.best_streak = max(st.best_streak, st.win_streak)
                elif result == "loss":
                    st.losses += 1
                    st.win_streak = 0
                else:
                    st.draws += 1
            prof.xp += xp
            prof.coins += coins
            await s.commit()
            return {"old_xp": old_xp, "new_xp": prof.xp, "win_streak": st.win_streak, "coins_total": prof.coins}

    async def t31_get_stats(self, uid: int) -> dict:
        async with self.sf() as s:
            st = await s.get(ThirtyOneStatistics, uid)
        if st is None:
            return {k: 0 for k in STAT_FIELDS}
        return {k: getattr(st, k) for k in STAT_FIELDS}

    async def t31_history(self, uid: int, limit: int = 8, offset: int = 0) -> tuple[list[dict], int]:
        async with self.sf() as s:
            total = (await s.execute(select(func.count()).select_from(ThirtyOneGameHistory)
                                     .where(ThirtyOneGameHistory.user_id == uid))).scalar_one()
            rows = (await s.execute(select(ThirtyOneGameHistory).where(ThirtyOneGameHistory.user_id == uid)
                                    .order_by(ThirtyOneGameHistory.finished_at.desc(), ThirtyOneGameHistory.id.desc())
                                    .limit(limit).offset(offset))).scalars().all()
        return [{"game_id": r.game_id, "result": r.result, "placement": r.placement, "players": r.players, "mode": r.mode,
                 "kind": r.kind, "rounds": r.rounds, "xp": r.xp_gained, "at": r.finished_at,
                 "opponents": r.opponents} for r in rows], total

    async def t31_leaderboard(self, kind: str, limit: int, offset: int,
                              user_ids: list[int] | None = None) -> tuple[list[dict], int]:
        """kind: global | week | month | friends. 31 only - never mixes Briscola numbers."""
        if kind in ("week", "month"):
            since = utcnow() - timedelta(days=7 if kind == "week" else 30)
            val = func.sum(ThirtyOneGameHistory.xp_gained).label("value")
            stmt = (select(User.id.label("uid"), User.display_name.label("name"), val)
                    .join(ThirtyOneGameHistory, ThirtyOneGameHistory.user_id == User.id)
                    .where(ThirtyOneGameHistory.finished_at >= since, ThirtyOneGameHistory.kind != "practice")
                    .group_by(User.id, User.display_name).having(val > 0))
        else:
            val = ThirtyOneStatistics.xp.label("value")
            stmt = (select(User.id.label("uid"), User.display_name.label("name"), val)
                    .join(ThirtyOneStatistics, ThirtyOneStatistics.user_id == User.id)
                    .where(ThirtyOneStatistics.matches > 0))
            if kind == "friends" and user_ids is not None:
                stmt = stmt.where(User.id.in_(user_ids))
        async with self.sf() as s:
            total = (await s.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
            rows = (await s.execute(stmt.order_by(desc("value"), User.id).limit(limit).offset(offset))).all()
        return [{"id": r.uid, "name": r.name, "value": r.value} for r in rows], total

    # ------------------------------------------------------------ admin configuration
    async def t31_get_config(self) -> dict:
        raw = await self.get_setting("t31_config", "")
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}

    async def t31_set_config(self, cfg: dict) -> None:
        await self.set_setting("t31_config", json.dumps(cfg))
