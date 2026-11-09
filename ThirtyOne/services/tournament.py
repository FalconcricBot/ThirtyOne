"""Knockout tournaments: pure bracket maths + the service that runs rounds on top of games."""
from __future__ import annotations

import logging
import math
import random
from datetime import timedelta

from utils.helpers import esc, utcnow

log = logging.getLogger(__name__)


# ============================================================ pure bracket logic
def build_bracket(player_ids: list[int], rng: random.Random | None = None) -> dict:
    """Single elimination. Byes (a player with b=None) auto-advance. Returns a JSON-able dict."""
    rng = rng or random.Random()
    ids = list(player_ids)
    if len(ids) < 2:
        raise ValueError("A tournament needs at least 2 players")
    rng.shuffle(ids)
    size = 1 << math.ceil(math.log2(len(ids)))
    byes = size - len(ids)
    slots: list[int | None] = []
    # spread byes so they never face each other: one bye per pair while byes remain
    for i in range(size // 2):
        a = ids.pop() if ids else None
        b = None if i < byes else (ids.pop() if ids else None)
        slots += [a, b]
    rounds = [[{"a": slots[i], "b": slots[i + 1], "winner": None, "game_id": None}
               for i in range(0, size, 2)]]
    n = size // 2
    while n > 1:
        n //= 2
        rounds.append([{"a": None, "b": None, "winner": None, "game_id": None} for _ in range(n)])
    br = {"rounds": rounds}
    for m in rounds[0]:
        if m["b"] is None:
            m["winner"] = m["a"]
    _propagate(br)
    return br


def _propagate(br: dict) -> None:
    """Copy winners forward; auto-resolve matches that only have one real player."""
    rounds = br["rounds"]
    for r in range(len(rounds) - 1):
        for i, m in enumerate(rounds[r]):
            if m["winner"] is not None:
                nxt = rounds[r + 1][i // 2]
                nxt["a" if i % 2 == 0 else "b"] = m["winner"]


def set_winner(br: dict, rnd: int, idx: int, winner: int) -> None:
    m = br["rounds"][rnd][idx]
    if winner not in (m["a"], m["b"]):
        raise ValueError("winner is not part of this match")
    m["winner"] = winner
    _propagate(br)


def ready_matches(br: dict) -> list[tuple[int, int]]:
    """Matches with two real players, no winner and no running game."""
    out = []
    for r, rnd in enumerate(br["rounds"]):
        for i, m in enumerate(rnd):
            if m["a"] is not None and m["b"] is not None and m["winner"] is None and m["game_id"] is None:
                out.append((r, i))
    return out


def champion(br: dict) -> int | None:
    return br["rounds"][-1][0]["winner"]


def round_name(br: dict, r: int) -> str:
    left = len(br["rounds"]) - r
    return {1: "FINAL", 2: "SEMI-FINAL", 3: "QUARTER-FINAL"}.get(left, f"ROUND {r + 1}")


# ============================================================ service
class TournamentService:
    def __init__(self, repo, games, lobby, bot, games31=None):
        self.repo, self.games, self.lobby, self.bot = repo, games, lobby, bot
        self.games31 = games31                           # 31 Card Game manager (tournaments can be either game)

    def _mgr(self, game: str):
        return self.games31 if game == "thirty_one" and self.games31 is not None else self.games

    async def create(self, admin_id: int, *, name, description, capacity, start_min, deadline_min,
                     game: str = "briscola") -> int:
        now = utcnow()
        tid = await self.repo.create_tournament(
            name=name, description=description, capacity=capacity, created_by=admin_id, game=game,
            register_until=now + timedelta(minutes=deadline_min), starts_at=now + timedelta(minutes=start_min))
        await self.repo.log_admin(admin_id, "create_tournament", f"#{tid} {game} {name} cap={capacity}")
        return tid

    async def start(self, tid: int, admin_id: int | None = None) -> str:
        t = await self.repo.get_tournament(tid)
        if not t or t["status"] != "registration":
            return "Tournament not found or already started."
        players = await self.repo.tournament_players(tid)
        if len(players) < 2:
            await self.repo.set_tournament(tid, status="cancelled")
            await self._notify([p["user_id"] for p in players],
                               f"❌ <b>{esc(t['name'])}</b> was cancelled: not enough players.")
            return "Cancelled: fewer than 2 players registered."
        br = build_bracket([p["user_id"] for p in players])
        await self.repo.set_tournament(tid, status="running", bracket=br)
        if admin_id:
            await self.repo.log_admin(admin_id, "start_tournament", f"#{tid}")
        await self._notify([p["user_id"] for p in players],
                           f"🏟 <b>{esc(t['name'])}</b> has started! Your first match will begin automatically.")
        await self._resolve_byes_and_launch(tid)
        return f"Started with {len(players)} players."

    async def cancel(self, tid: int, admin_id: int) -> str:
        t = await self.repo.get_tournament(tid)
        if not t or t["status"] in ("finished", "cancelled"):
            return "Nothing to cancel."
        await self.repo.set_tournament(tid, status="cancelled")
        await self.repo.log_admin(admin_id, "cancel_tournament", f"#{tid}")
        await self.games.cancel_tournament_games(tid)
        if self.games31 is not None:
            await self.games31.cancel_tournament_games(tid)
        await self._notify([p["user_id"] for p in await self.repo.tournament_players(tid)],
                           f"❌ <b>{esc(t['name'])}</b> was cancelled by an admin.")
        return "Cancelled."

    async def remove_player(self, tid: int, uid: int, admin_id: int) -> str:
        t = await self.repo.get_tournament(tid)
        if not t:
            return "Tournament not found."
        if t["status"] == "running" and t["bracket"]:
            br = t["bracket"]
            for r, rnd in enumerate(br["rounds"]):
                for i, m in enumerate(rnd):
                    if m["winner"] is None and uid in (m["a"], m["b"]) and m["a"] and m["b"]:
                        other = m["b"] if m["a"] == uid else m["a"]
                        if m["game_id"]:
                            await self._mgr(t.get("game", "briscola")).cancel_game_silently(m["game_id"])
                            m["game_id"] = None
                        set_winner(br, r, i, other)
            await self.repo.set_tournament(tid, bracket=br)
        ok = await self.repo.set_tournament_player(tid, uid, "removed")
        await self.repo.log_admin(admin_id, "tournament_remove", f"#{tid} user {uid}")
        if ok and t["status"] == "running":
            await self._resolve_byes_and_launch(tid)
        return "Player removed." if ok else "That player is not in this tournament."

    # ---- running rounds
    async def tick(self) -> None:
        """Called every ~30s: auto-start due tournaments, retry matches whose players were busy."""
        now = utcnow()
        for t in await self.repo.list_tournaments(["registration"], limit=50):
            if now >= t["starts_at"]:
                await self.start(t["id"])
        for t in await self.repo.list_tournaments(["running"], limit=50):
            await self._launch_ready(t["id"])

    async def _resolve_byes_and_launch(self, tid: int) -> None:
        await self._check_finished(tid)
        await self._launch_ready(tid)

    async def _launch_ready(self, tid: int) -> None:
        t = await self.repo.get_tournament(tid)
        if not t or t["status"] != "running":
            return
        br = t["bracket"]
        removed = {p["user_id"] for p in await self.repo.tournament_players(tid, include_removed=True)
                   if p["status"] == "removed"}
        for r, i in ready_matches(br):
            m = br["rounds"][r][i]
            if m["a"] in removed or m["b"] in removed:       # walkover for the remaining player
                set_winner(br, r, i, m["b"] if m["a"] in removed else m["a"])
                await self.repo.set_tournament(tid, bracket=br)
                await self._check_finished(tid)
                return await self._launch_ready(tid)
            if self.lobby.busy_reason(m["a"]) or self.lobby.busy_reason(m["b"]):
                continue                                   # try again on the next tick
            try:
                gid = await self._mgr(t.get("game", "briscola")).start_tournament_match(
                    tid, r, i, m["a"], m["b"], round_name(br, r))
            except Exception:
                log.exception("could not start tournament match %s %s:%s", tid, r, i)
                continue
            m["game_id"] = gid
            await self.repo.set_tournament(tid, bracket=br)

    async def on_game_finished(self, tid: int, match_key: str, game, user_ids: dict[int, int]) -> None:
        """user_ids = {seat: user_id}. A draw replays the match with a fresh deal."""
        t = await self.repo.get_tournament(tid)
        if not t or t["status"] != "running":
            return
        br = t["bracket"]
        r, i = (int(x) for x in match_key.split(":"))
        m = br["rounds"][r][i]
        res = game.result()
        if res["draw"]:
            m["game_id"] = None
            await self.repo.set_tournament(tid, bracket=br)
            await self._notify(list(user_ids.values()), "🤝 Draw! Your tournament match is replayed with a new deal.")
            await self._launch_ready(tid)
            return
        win_seat = next(s for s in user_ids if game.side_of(s) in res["winner_sides"])
        winner = user_ids[win_seat]
        loser = next(u for u in user_ids.values() if u != winner)
        set_winner(br, r, i, winner)
        await self.repo.set_tournament(tid, bracket=br)
        await self.repo.set_tournament_player(tid, loser, "eliminated")
        await self._notify([loser], f"💔 You were eliminated from <b>{esc(t['name'])}</b>. Well played!")
        await self._check_finished(tid)
        await self._launch_ready(tid)

    async def _check_finished(self, tid: int) -> None:
        t = await self.repo.get_tournament(tid)
        if not t or t["status"] != "running":
            return
        champ = champion(t["bracket"])
        if champ is None:
            return
        await self.repo.set_tournament(tid, status="finished", winner_id=champ)
        await self.repo.set_tournament_player(tid, champ, "winner")
        await self.repo.add_tournament_win(champ)
        await self.repo.add_rewards(champ, coins=500, xp=250)
        name = await self.repo.display_name(champ)
        players = [p["user_id"] for p in await self.repo.tournament_players(tid)]
        await self._notify(players, f"🏆 <b>{esc(t['name'])}</b> is over!\n👑 Champion: <b>{esc(name)}</b>")
        await self._notify([champ], "🎁 Champion reward: +500 coins, +250 XP")
        if await self.repo.unlock(champ, "champion"):       # achievement badge
            await self.repo.add_rewards(champ, coins=50)

    async def _notify(self, user_ids: list[int], text: str) -> None:
        for uid in user_ids:
            try:
                await self.bot.send_message(uid, text, parse_mode="HTML")
            except Exception:
                pass
