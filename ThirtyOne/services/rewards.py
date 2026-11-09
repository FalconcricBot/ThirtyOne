"""Daily bonus, missions and achievements. Rewards are virtual coins + XP only."""
from __future__ import annotations

from datetime import timedelta

from services.statistics import level_for
from utils.helpers import utcnow

# key, title, target, metric, coins, xp
DAILY_MISSIONS = [
    ("d_play5", "Play 5 matches", 5, "matches", 100, 30),
    ("d_win2", "Win 2 matches", 2, "wins", 120, 40),
    ("d_points100", "Collect 100 points", 100, "points", 100, 30),
    ("d_streak3", "Win 3 games in a row", 3, "streak", 200, 60),
    ("d_31play", "🔥 Play 2 matches of 31", 2, "t31_matches", 80, 30),
    ("d_31hit", "🔥 Reach 31 in a 31 match", 1, "t31_hit", 100, 35),
]
WEEKLY_MISSIONS = [
    ("w_play20", "Play 20 matches", 20, "matches", 300, 100),
    ("w_win10", "Win 10 matches", 10, "wins", 400, 150),
    ("w_31win", "🔥 Win 5 matches of 31", 5, "t31_wins", 350, 120),
]
MISSIONS = {m[0]: m for m in DAILY_MISSIONS + WEEKLY_MISSIONS}

ACHIEVEMENTS = {
    "first_win": ("🎉", "First Blood", "Win your first match"),
    "wins_10": ("🏅", "Rising Star", "Win 10 matches"),
    "wins_50": ("🏆", "Arena Veteran", "Win 50 matches"),
    "play_25": ("🃏", "Regular", "Play 25 matches"),
    "play_100": ("🎴", "Card Addict", "Play 100 matches"),
    "streak_3": ("🔥", "Hot Hand", "Win 3 in a row"),
    "streak_5": ("⚡", "Unstoppable", "Win 5 in a row"),
    "big_score": ("💯", "Century", "Score 100+ points in a match"),
    "champion": ("👑", "Champion", "Win a tournament"),
    "gold_rank": ("🥇", "Going Gold", "Reach Gold rank"),
    "diamond_rank": ("💠", "Diamond Hands", "Reach Diamond rank"),
    "daily_7": ("📅", "Dedicated", "7-day login streak"),
}
ACHIEVEMENT_COINS = 50


def day_key(now=None) -> str:
    return (now or utcnow()).strftime("%Y-%m-%d")


def week_key(now=None) -> str:
    y, w, _ = (now or utcnow()).isocalendar()
    return f"{y}-W{w:02d}"


def daily_bonus(prev_last: str | None, prev_streak: int, today: str) -> tuple[int, int, int] | None:
    """-> (new_streak, coins, xp) or None if today's bonus was already taken."""
    if prev_last == today:
        return None
    yesterday = (utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    streak = prev_streak + 1 if prev_last == yesterday else 1
    s = min(streak, 7)
    return streak, 100 + 25 * (s - 1), 20 + 10 * (s - 1)


def earned_achievements(*, wins: int, matches: int, best_streak: int, highest: int,
                        tournament_wins: int, xp: int, daily_streak: int) -> set[str]:
    out = set()
    checks = {"first_win": wins >= 1, "wins_10": wins >= 10, "wins_50": wins >= 50,
              "play_25": matches >= 25, "play_100": matches >= 100, "streak_3": best_streak >= 3,
              "streak_5": best_streak >= 5, "big_score": highest >= 100,
              "champion": tournament_wins >= 1, "gold_rank": xp >= 1500,
              "diamond_rank": xp >= 7000, "daily_7": daily_streak >= 7}
    return {k for k, ok in checks.items() if ok}


class RewardsService:
    def __init__(self, repo):
        self.repo = repo

    async def after_game(self, uid: int, *, result: str, points: int, kind: str, info: dict) -> dict:
        """Update missions, grant level-up and achievement rewards. Returns notification extras."""
        out = {"level_up": None, "achievements": [], "missions_done": []}
        d, w = day_key(), week_key()
        practice = kind == "practice"
        updates = [("matches", "add", 1)]
        if not practice:
            updates += [("points", "add", points)]
            if result == "win":
                updates += [("wins", "add", 1)]
            updates += [("streak", "max", info["win_streak"])]
        before = await self.repo.mission_progress(uid, d, w)
        for metric, mode, val in updates:
            for key, _t, target, m, _c, _x in MISSIONS.values():
                if m != metric:
                    continue
                if key.startswith("w_") and metric == "streak":
                    continue
                await self.repo.add_progress(uid, key, w if key.startswith("w_") else d, val, mode)
        after = await self.repo.mission_progress(uid, d, w)
        for key, (_k, title, target, *_r) in MISSIONS.items():
            was = before.get(key, (0, False))[0] >= target
            now = after.get(key, (0, False))[0] >= target
            if now and not was:
                out["missions_done"].append(title)
        old_lvl, new_lvl = level_for(info["old_xp"]), level_for(info["new_xp"])
        if new_lvl > old_lvl:
            bonus = sum(50 * lv for lv in range(old_lvl + 1, new_lvl + 1))
            await self.repo.add_rewards(uid, coins=bonus, xp=0)
            out["level_up"] = (new_lvl, bonus)
        p = await self.repo.get_player(uid)
        if p:
            have = await self.repo.achievements(uid)
            for code in earned_achievements(wins=p["wins"], matches=p["matches"], best_streak=p["best_streak"],
                                            highest=p["highest_score"], tournament_wins=p["tournament_wins"],
                                            xp=p["xp"], daily_streak=p["daily_streak"]) - set(have):
                if await self.repo.unlock(uid, code):
                    await self.repo.add_rewards(uid, coins=ACHIEVEMENT_COINS, xp=0)
                    out["achievements"].append(code)
        return out

    async def after_game_31(self, uid: int, *, result: str, kind: str, info: dict, times_31: int = 0) -> dict:
        """31 Card Game: shared missions (matches / wins) and level-up bonus. Briscola streaks are not touched."""
        out = {"level_up": None, "missions_done": [], "achievements": []}
        d, w = day_key(), week_key()
        before = await self.repo.mission_progress(uid, d, w)
        ranked = kind != "practice"
        updates = [("matches", 1), ("t31_matches", 1)]
        if result == "win" and ranked:
            updates += [("wins", 1), ("t31_wins", 1)]
        if times_31 > 0 and ranked:
            updates.append(("t31_hit", 1))
        for metric, val in updates:
            for key, _t, _target, m, _c, _x in MISSIONS.values():
                if m == metric:
                    await self.repo.add_progress(uid, key, w if key.startswith("w_") else d, val, "add")
        after = await self.repo.mission_progress(uid, d, w)
        for key, (_k, title, target, *_r) in MISSIONS.items():
            if after.get(key, (0, False))[0] >= target > before.get(key, (0, False))[0]:
                out["missions_done"].append(title)
        old_lvl, new_lvl = level_for(info["old_xp"]), level_for(info["new_xp"])
        if new_lvl > old_lvl:
            bonus = sum(50 * lv for lv in range(old_lvl + 1, new_lvl + 1))
            await self.repo.add_rewards(uid, coins=bonus, xp=0)
            out["level_up"] = (new_lvl, bonus)
        return out

    async def claim_daily(self, uid: int):
        p = await self.repo.get_player(uid)
        res = daily_bonus(p["last_daily"], p["daily_streak"], day_key())
        if res is None:
            return None
        streak, coins, xp = res
        await self.repo.set_daily(uid, day_key(), streak, coins, xp)
        return {"streak": streak, "coins": coins, "xp": xp}

    async def claim_mission(self, uid: int, key: str):
        m = MISSIONS.get(key)
        if not m:
            return None
        period = week_key() if key.startswith("w_") else day_key()
        if not await self.repo.claim_mission(uid, key, period, m[2]):
            return None
        await self.repo.add_rewards(uid, coins=m[4], xp=m[5])
        return {"title": m[1], "coins": m[4], "xp": m[5]}
