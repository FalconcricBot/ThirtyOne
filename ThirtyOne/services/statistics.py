"""Pure XP / rank / reward maths (no I/O) plus the end-of-game result recorder."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

RANKS = [(0, "🥉", "Bronze"), (500, "🥈", "Silver"), (1500, "🥇", "Gold"), (3500, "💎", "Platinum"),
         (7000, "💠", "Diamond"), (12000, "👑", "Master"), (20000, "🔥", "Grandmaster")]


def rank_for(xp: int) -> tuple[str, str, int, int | None]:
    """-> (emoji, name, floor_xp, next_rank_xp or None)"""
    idx = max(i for i, r in enumerate(RANKS) if xp >= r[0])
    nxt = RANKS[idx + 1][0] if idx + 1 < len(RANKS) else None
    return RANKS[idx][1], RANKS[idx][2], RANKS[idx][0], nxt


def level_for(xp: int) -> int:
    return 1 + int((max(xp, 0) / 40) ** 0.5)


def game_rewards(result: str, points: int, kind: str, forfeited: bool = False) -> tuple[int, int]:
    """-> (xp, coins) for one player. Practice pays 40%, a quitter earns nothing."""
    if forfeited:
        return 0, 0
    xp, coins = {"win": (50 + points // 10, 30 + points // 4),
                 "draw": (25, 15), "loss": (15, 5)}[result]
    if kind == "practice":
        xp, coins = round(xp * 0.4), round(coins * 0.4)
    elif kind == "tournament":
        xp, coins = round(xp * 1.5), round(coins * 1.5)
    return xp, coins


def result_for(game, seat: int) -> tuple[str, int]:
    """-> ('win'|'loss'|'draw', points of that player's side)"""
    res = game.result()
    side = game.side_of(seat)
    pts = res["scores"][side]
    if res["draw"]:
        return "draw", pts
    return ("win" if side in res["winner_sides"] else "loss"), pts


async def record_game(repo, rewards, *, game_id: int, game, kind: str, humans: dict[int, int],
                      names: list[str]) -> dict[int, dict]:
    """Persist results for every human. humans = {seat: user_id}. Returns per-user summaries."""
    summaries: dict[int, dict] = {}
    forfeit_seat = game.state.forfeit_seat
    for seat, uid in humans.items():
        result, pts = result_for(game, seat)
        forfeited = forfeit_seat is not None and game.side_of(seat) == game.side_of(forfeit_seat) \
            and seat == forfeit_seat
        xp, coins = game_rewards(result, pts, kind, forfeited)
        opp = [names[s] for s in range(game.n) if game.side_of(s) != game.side_of(seat)]
        info = await repo.apply_game_result(uid, game_id=game_id, result=result, points=pts,
                                            mode=game.n, kind=kind, opponents=", ".join(opp)[:190],
                                            xp=xp, coins=coins)
        if info is None:          # already recorded (duplicate finish) - never double-pay
            continue
        extra = await rewards.after_game(uid, result=result, points=pts, kind=kind, info=info)
        summaries[uid] = {**info, **extra, "result": result, "points": pts, "xp": xp, "coins": coins}
    return summaries
