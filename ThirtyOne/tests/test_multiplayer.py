"""Lobby, brackets, rewards maths, image rendering and a full GameManager integration run
(with a fake Telegram bot and an in-memory repository - no network, no database)."""
import asyncio
import json
import random
import time
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

from tests import fake_telegram

fake_telegram.install()

from game.engine import BriscolaGame                                            # noqa: E402
from services import game_manager as gm                                         # noqa: E402
from services.matchmaking import Lobby, LobbyError                              # noqa: E402
from services.rewards import RewardsService, daily_bonus, earned_achievements   # noqa: E402
from services.statistics import game_rewards, level_for, rank_for               # noqa: E402
from services.tournament import (build_bracket, champion, ready_matches, round_name,  # noqa: E402
                                 set_winner)
from ui import images                                                           # noqa: E402
from utils.validators import parse_room_code, parse_tournament_args            # noqa: E402


# ------------------------------------------------------------------ pure services
class LobbyTests(unittest.TestCase):
    def test_room_lifecycle_and_guards(self):
        lb = Lobby()
        room = lb.create_room(1, "A", 2, chat_id=-100)
        with self.assertRaises(LobbyError):
            lb.join_room(room.code, 1, "A")                    # duplicate join
        with self.assertRaises(LobbyError):
            lb.create_room(1, "A", 2, -100)                    # already in a room
        lb.join_room(room.code, 2, "B")
        with self.assertRaises(LobbyError):
            lb.join_room(room.code, 3, "C")                    # full
        with self.assertRaises(LobbyError):
            lb.begin_start(room.code, 2)                       # not the owner
        lb.begin_start(room.code, 1)
        with self.assertRaises(LobbyError):
            lb.join_room(room.code, 3, "C")                    # already starting
        lb.finish_start(room.code)
        self.assertEqual(lb.playing, {1, 2})
        self.assertIn("running match", lb.busy_reason(1))

    def test_owner_leaves_transfers_ownership_and_empty_room_closes(self):
        lb = Lobby()
        r = lb.create_room(1, "A", 4, 5)
        lb.join_room(r.code, 2, "B")
        room, closed = lb.leave_room(1)
        self.assertFalse(closed)
        self.assertEqual(room.owner_id, 2)
        room, closed = lb.leave_room(2)
        self.assertTrue(closed)
        self.assertEqual(lb.rooms, {})

    def test_abandoned_rooms_expire(self):
        lb = Lobby()
        r = lb.create_room(1, "A", 2, 5)
        self.assertEqual(lb.expire_rooms(900, now=r.last_activity + 100), [])
        self.assertEqual([x.code for x in lb.expire_rooms(900, now=r.last_activity + 1000)], [r.code])
        self.assertIsNone(lb.busy_reason(1))

    def test_ai_fill(self):
        lb = Lobby()
        r = lb.create_room(1, "A", 4, 5)
        lb.fill_ai(r.code, 1)
        self.assertTrue(r.full)
        self.assertEqual(len({u for u, _ in r.players}), 4)
        with self.assertRaises(LobbyError):
            lb.fill_ai(r.code, 2)

    def test_quick_match_queue(self):
        lb = Lobby()
        self.assertIsNone(lb.queue_add(1, "A", 2))
        with self.assertRaises(LobbyError):
            lb.queue_add(1, "A", 2)                            # already searching
        self.assertEqual({u for u, _ in lb.queue_add(2, "B", 2)}, {1, 2})
        self.assertEqual(lb.queue_size(2), 0)
        lb.queue_add(3, "C", 4)
        self.assertTrue(lb.queue_remove(3))
        self.assertFalse(lb.queue_remove(3))


class BracketTests(unittest.TestCase):
    def test_power_of_two_bracket_plays_to_a_champion(self):
        br = build_bracket(list(range(1, 9)), random.Random(1))
        self.assertEqual([len(r) for r in br["rounds"]], [4, 2, 1])
        self.assertEqual(round_name(br, 2), "FINAL")
        while champion(br) is None:
            r, i = ready_matches(br)[0]
            set_winner(br, r, i, br["rounds"][r][i]["a"])
        self.assertIsNotNone(champion(br))

    def test_byes_for_odd_player_counts(self):
        for n in (2, 3, 5, 6, 7, 11):
            br = build_bracket(list(range(n)), random.Random(n))
            ids = [x for m in br["rounds"][0] for x in (m["a"], m["b"]) if x is not None]
            self.assertEqual(sorted(ids), list(range(n)))
            self.assertFalse(any(m["a"] is None and m["b"] is None for m in br["rounds"][0]))
            guard = 0
            while champion(br) is None and guard < 100:
                r, i = ready_matches(br)[0]
                set_winner(br, r, i, br["rounds"][r][i]["b"])
                guard += 1
            self.assertIsNotNone(champion(br), n)

    def test_bad_winner_rejected_and_json_safe(self):
        br = build_bracket([1, 2, 3, 4], random.Random(2))
        with self.assertRaises(ValueError):
            set_winner(br, 0, 0, 99)
        json.dumps(br)
        with self.assertRaises(ValueError):
            build_bracket([1])


class RewardMathTests(unittest.TestCase):
    def test_ranks_levels_rewards(self):
        self.assertEqual(rank_for(0)[1], "Bronze")
        self.assertEqual(rank_for(1500)[1], "Gold")
        self.assertEqual(rank_for(25000)[1], "Grandmaster")
        self.assertIsNone(rank_for(25000)[3])
        self.assertEqual(level_for(0), 1)
        self.assertGreater(level_for(2450), level_for(100))
        w, l = game_rewards("win", 80, "quick"), game_rewards("loss", 40, "quick")
        self.assertGreater(w[0], l[0])
        self.assertEqual(game_rewards("win", 80, "practice")[0], round(w[0] * 0.4))
        self.assertEqual(game_rewards("loss", 0, "quick", forfeited=True), (0, 0))

    def test_daily_bonus_streak(self):
        from datetime import timedelta
        from utils.helpers import utcnow
        today = utcnow().strftime("%Y-%m-%d")
        yest = (utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertIsNone(daily_bonus(today, 3, today))
        self.assertEqual(daily_bonus(yest, 3, today)[0], 4)
        self.assertEqual(daily_bonus("2000-01-01", 9, today)[0], 1)
        self.assertGreater(daily_bonus(yest, 5, today)[1], daily_bonus(None, 0, today)[1])

    def test_achievements(self):
        a = earned_achievements(wins=10, matches=30, best_streak=3, highest=101, tournament_wins=0, xp=1600, daily_streak=0)
        self.assertTrue({"first_win", "wins_10", "play_25", "streak_3", "big_score", "gold_rank"} <= a)
        self.assertNotIn("champion", a)

    def test_validators(self):
        self.assertEqual(parse_room_code("ba-82941"), "BA-82941")
        self.assertEqual(parse_room_code(" 82941 "), "BA-82941")
        self.assertIsNone(parse_room_code("hello"))
        t = parse_tournament_args("Friday Cup | 8 | 30 | 20 | fun")
        self.assertEqual((t["capacity"], t["start_min"], t["deadline_min"]), (8, 30, 20))
        for bad in ("x | 1 | 30", "x | 8 | 30 | 99", "only name"):
            with self.assertRaises(ValueError):
                parse_tournament_args(bad)


class ImageTests(unittest.TestCase):
    def test_renderers_produce_png(self):
        from PIL import Image
        h = images.render_hand(["AH", "3S", "KD"], "H", "7H", 16, 24, True)
        t = images.render_table(room="BA-1", mode_label="1 VS 1", names=["A", "B"], trick=[(0, "AH")], turn=1,
                                trump_suit="H", trump_card="7H", stock=10, side_scores=[11, 0], team_mode=False)
        t4 = images.render_table(room="BA-2", mode_label="2 VS 2", names=["A", "B", "C", "D"], trick=[], turn=0,
                                 trump_suit="S", trump_card=None, stock=0, side_scores=[50, 70], team_mode=True,
                                 last_trick={"plays": [(0, "AS"), (1, "2D"), (2, "3S"), (3, "4C")], "winner": 0, "points": 21},
                                 winner_text="B & D win!")
        p = images.render_profile(name="Nihar ✨", username=None, player_no=10001, rank_name="Gold", level=5, xp=1600,
                                  xp_floor=1500, xp_next=3500, stats=dict(matches=0, wins=0, losses=0, draws=0, win_pct=0,
                                                                          streak=0, highest=0, points=0))
        for buf in (h, t, t4, p):
            self.assertEqual(buf.getvalue()[:8], b"\x89PNG\r\n\x1a\n")
            Image.open(buf)
        self.assertEqual(images.safe_text("राज"), "Player")
        self.assertEqual(images.safe_text("Ana ✨ Maria"), "Ana Maria")


# ------------------------------------------------------------------ integration (fake bot + repo)
class FakeBot:
    def __init__(self):
        self.n, self.sent, self.edits, self.deleted, self.blocked = 100, [], [], [], set()
        self.markups = []                       # (chat_id, text, reply_markup) of every new message

    def _id(self):
        self.n += 1
        return self.n

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.blocked:
            raise sys_forbidden()
        self.sent.append((chat_id, text))
        mid = self._id()
        self.markups.append((chat_id, text, kw.get("reply_markup"), mid))
        return SimpleNamespace(message_id=mid)

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        if chat_id in self.blocked:
            raise sys_forbidden()
        self.sent.append((chat_id, caption))
        return SimpleNamespace(message_id=self._id())

    async def edit_message_text(self, text, chat_id, message_id, **kw):
        self.edits.append((chat_id, message_id, text))

    async def edit_message_media(self, chat_id, message_id, media, **kw):
        self.edits.append((chat_id, message_id, media.caption))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def send_chat_action(self, chat_id, action):
        if chat_id in self.blocked:
            raise sys_forbidden()


def sys_forbidden():
    from telegram.error import Forbidden
    return Forbidden("blocked")


class FakeJobs:
    def __init__(self):
        self.jobs = []

    def run_once(self, cb, when, data=None, name=None):
        self.jobs.append((name, cb, when, data))

    def get_jobs_by_name(self, name):
        return []


class MemRepo:
    """Just enough of database.repository.Repo for the manager and rewards service."""
    def __init__(self):
        self.games, self.history, self.players, self.moves = {}, set(), {}, {}
        self.mission, self.ach, self.nid = {}, {}, 0

    def player(self, uid):
        return self.players.setdefault(uid, dict(
            id=uid, xp=0, coins=100, win_streak=0, best_streak=0, daily_streak=0, last_daily=None, tournament_wins=0,
            hand_images=False, table_images=False, notify=True, matches=0, wins=0, losses=0, draws=0,
            total_points=0, highest_score=0, practice_matches=0, display_name=f"P{uid}", username=None, player_no=uid))

    async def get_player(self, uid): return self.player(uid)
    async def display_name(self, uid): return f"P{uid}"

    async def create_game(self, *, mode, kind, seed, state, players, room_code, group_chat_id, tournament_id=None, tournament_match=None):
        self.nid += 1
        self.games[self.nid] = dict(id=self.nid, mode=mode, kind=kind, status="active", seed=seed, state=state, room_code=room_code,
                                    group_chat_id=group_chat_id, group_msg_id=None, tournament_id=tournament_id,
                                    tournament_match=tournament_match, players=players, scores=None, winner_sides=[])
        for p in players:
            p.setdefault("seat", 0)
        self.moves[self.nid] = []
        return self.nid

    async def record_move(self, gid, no, seat, card, state):
        assert no == len(self.moves[gid]) + 1, "move numbers must be sequential (no duplicates)"
        self.moves[gid].append([seat, card]); self.games[gid]["state"] = json.loads(json.dumps(state))

    async def finish_game(self, gid, state, winner_sides, scores, captured, status="finished"):
        self.games[gid].update(state=state, status=status, winner_sides=winner_sides, scores=scores)

    async def cancel_game(self, gid): self.games[gid]["status"] = "cancelled"
    async def set_group_message(self, *a): pass

    async def load_active_games(self):
        return [dict(g, players=[dict(p, seat=i) for i, p in enumerate(g["players"])]) for g in self.games.values() if g["status"] == "active"]

    async def get_game(self, gid):
        g = self.games.get(gid)
        return dict(g, moves=self.moves[gid], players=[dict(p, seat=i) for i, p in enumerate(g["players"])]) if g else None

    async def apply_game_result(self, uid, *, game_id, result, points, mode, kind, opponents, xp, coins):
        if (uid, game_id) in self.history:
            return None
        self.history.add((uid, game_id))
        p = self.player(uid); old = p["xp"]
        if kind != "practice":
            p["matches"] += 1; p["total_points"] += points; p["highest_score"] = max(p["highest_score"], points)
            if result == "win":
                p["wins"] += 1; p["win_streak"] += 1; p["best_streak"] = max(p["best_streak"], p["win_streak"])
            elif result == "loss":
                p["losses"] += 1; p["win_streak"] = 0
            else:
                p["draws"] += 1
        p["xp"] += xp; p["coins"] += coins
        return dict(old_xp=old, new_xp=p["xp"], win_streak=p["win_streak"], best_streak=p["best_streak"], coins_total=p["coins"])

    async def mission_progress(self, uid, day, week):
        return {k[1]: v for k, v in self.mission.items() if k[0] == uid and k[2] in (day, week)}

    async def add_progress(self, uid, key, period, value, mode="add"):
        cur = self.mission.get((uid, key, period), (0, False))
        self.mission[(uid, key, period)] = ((cur[0] + value) if mode == "add" else max(cur[0], value), cur[1])

    async def add_rewards(self, uid, coins=0, xp=0):
        p = self.player(uid); p["coins"] += coins; p["xp"] += xp

    async def achievements(self, uid): return list(self.ach.get(uid, []))

    async def unlock(self, uid, code):
        s = self.ach.setdefault(uid, [])
        if code in s:
            return False
        s.append(code); return True


class FakeNotifier:
    def __init__(self, bot): self.bot, self.dms = bot, []
    async def dm(self, uid, text, kb=None, silent=False):
        if uid in self.bot.blocked:
            return None
        self.dms.append((uid, text)); return 7
    async def delete(self, chat_id, mid):
        if mid is not None:
            self.bot.deleted.append((chat_id, mid))
    async def can_dm(self, uid): return uid not in self.bot.blocked


def make_manager():
    app = SimpleNamespace(bot=FakeBot(), job_queue=FakeJobs())
    repo = MemRepo()
    mgr = gm.GameManager(app, repo, Lobby(), RewardsService(repo), FakeNotifier(app.bot))
    return mgr, repo, app


def pick(s, seat):
    return random.Random(0).choice(s.game.state.hands[seat])


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._p = mock.patch("services.game_manager.random.uniform", return_value=0.0)
        self._p.start()
        self.addCleanup(self._p.stop)

    async def wait_ai(self, mgr, s, timeout=20):
        end = time.time() + timeout
        while time.time() < end and not s.game.finished and s.game.state.turn in s.ai:
            await asyncio.sleep(0.01)

    async def play_out_vs_ai(self, mgr, s, human):
        while not s.game.finished:
            await self.wait_ai(mgr, s)
            if s.game.finished:
                break
            seat = s.game.seat_of(human)
            alert = await mgr.handle_move(human, s.game_id, s.game.state.version, s.game.state.hands[seat][0])
            self.assertIsNone(alert)

    async def test_practice_game_runs_to_the_end_and_pays_out(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(5, "Me"), gm.PlayerInfo(-2, "Bot", "easy")], kind="practice")
        self.assertIn(5, mgr.by_user)
        await self.play_out_vs_ai(mgr, s, 5)
        self.assertEqual(repo.games[s.game_id]["status"], "finished")
        self.assertEqual(sum(repo.games[s.game_id]["scores"]), 120)
        self.assertEqual(len(repo.moves[s.game_id]), 40)
        p = repo.players[5]
        self.assertEqual((p["practice_matches"], p["matches"]), (0, 0))       # mock repo: practice not in ranked stats
        self.assertGreater(p["xp"], 0)
        self.assertNotIn(5, mgr.by_user)
        self.assertNotIn(5, mgr.lobby.playing)
        self.assertEqual(mgr.sessions, {})
        # hand message was edited in place, not re-sent for every move
        self.assertLess(len(app.bot.sent), 6)
        self.assertGreater(len(app.bot.edits), 10)

    async def test_security_and_duplicate_callbacks(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(1, "A"), gm.PlayerInfo(2, "B")], kind="quick")
        cur = s.game.current_user
        other = 2 if cur == 1 else 1
        v = s.game.state.version
        mine = s.game.state.hands[s.game.seat_of(cur)]
        theirs = s.game.state.hands[s.game.seat_of(other)]
        self.assertIn("Not your turn", await mgr.handle_move(other, s.game_id, v, theirs[0]))
        self.assertIn("not in your hand", await mgr.handle_move(cur, s.game_id, v, theirs[0]))
        self.assertIn("not a player", await mgr.handle_move(999, s.game_id, v, mine[0]))
        self.assertIn("expired", await mgr.handle_move(cur, 424242, v, mine[0]))
        self.assertIsNone(await mgr.handle_move(cur, s.game_id, v, mine[0]))
        self.assertIn("outdated", await mgr.handle_move(cur, s.game_id, v, mine[0]))     # double tap
        self.assertEqual(len(repo.moves[s.game_id]), 1)

    async def test_private_hands_never_reach_the_group_or_opponent(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(1, "A"), gm.PlayerInfo(2, "B")], kind="room", group_chat_id=-500)
        hands = {u: s.game.state.hands[i] for i, u in enumerate((1, 2))}
        group_texts = [t for c, t in app.bot.sent if c == -500] + [t for c, _m, t in app.bot.edits if c == -500]
        self.assertTrue(group_texts)
        for uid, hand in hands.items():
            others_view = [t for c, t in app.bot.sent if c in (-500, 2 if uid == 1 else 1)]
            for card in hand:
                if card != s.game.state.trump_card:
                    self.assertFalse(any(f"[ <b>{gm.texts._c(card)}</b> ]" in t for t in others_view), card)

    async def test_group_turn_ping_tags_the_player_and_links_to_the_bot(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(1, "Asha"), gm.PlayerInfo(2, "Rahul")], kind="room", group_chat_id=-500)
        pings = [m for m in app.bot.markups if m[0] == -500 and "Your cards are in the bot chat" in m[1]]
        self.assertEqual(len(pings), 1)
        cur = s.game.current_user
        self.assertIn(f"tg://user?id={cur}", pings[0][1])
        self.assertTrue(pings[0][2].inline_keyboard[0][0].url.endswith("?start=hand"))
        seat = s.game.seat_of(cur)
        await mgr.handle_move(cur, s.game_id, s.game.state.version, s.game.state.hands[seat][0])
        pings = [m for m in app.bot.markups if m[0] == -500 and "Your cards are in the bot chat" in m[1]]
        self.assertEqual(len(pings), 2)
        self.assertIn((-500, pings[0][3]), app.bot.deleted)                  # previous ping removed
        self.assertIn(f"tg://user?id={s.game.current_user}", pings[1][1])
        await mgr.forfeit(1)
        self.assertIn((-500, pings[1][3]), app.bot.deleted)                  # cleaned up at the end

    async def test_start_hand_deep_link_resends_the_cards(self):
        from handlers import start as start_h
        calls = []
        class Games:
            def __init__(self, ok): self.ok = ok
            async def resend_hand(self, uid): calls.append(uid); return self.ok
        c = SimpleNamespace(games31=Games(False), games=Games(True))
        replies = []
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42), effective_chat=SimpleNamespace(type="private"),
                                 message=SimpleNamespace(reply_text=lambda *a, **k: replies.append(a)))
        context = SimpleNamespace(args=["hand"], user_data={}, application=SimpleNamespace(bot_data={"c": c}))
        await start_h.start.__wrapped__(update, context)
        self.assertEqual(calls, [42, 42])                                    # tried 31 first, then Briscola
        self.assertEqual(replies, [])                                        # no menu / no error: just the hand

    async def test_forfeit_and_afk_timeout(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(1, "A"), gm.PlayerInfo(2, "B")], kind="quick")
        self.assertTrue(await mgr.forfeit(1))
        self.assertEqual(repo.games[s.game_id]["winner_sides"], [1])
        self.assertEqual(repo.players[1]["losses"], 1)
        self.assertEqual(repo.players[2]["wins"], 1)
        self.assertEqual(repo.players[1]["xp"], 0)                            # quitter earns nothing
        # AFK: first timeout auto-plays a card and records a strike...
        s2 = await mgr.start_game([gm.PlayerInfo(3, "C"), gm.PlayerInfo(4, "D")], kind="quick")
        seat, v = s2.game.state.turn, s2.game.state.version
        await mgr._timeout_job(SimpleNamespace(job=SimpleNamespace(data=(s2.game_id, v))))
        self.assertFalse(s2.game.finished)
        self.assertEqual((s2.strikes[seat], s2.game.state.version), (1, v + 1))
        # ...a stale timer (move already happened) is ignored...
        await mgr._timeout_job(SimpleNamespace(job=SimpleNamespace(data=(s2.game_id, v))))
        self.assertEqual(s2.game.state.version, v + 1)
        # ...and reaching the strike limit (or the 'forfeit' policy) removes the player.
        import dataclasses
        strict = dataclasses.replace(gm.settings, timeout_policy="forfeit")
        with mock.patch.object(gm, "settings", strict):
            await mgr._timeout_job(SimpleNamespace(job=SimpleNamespace(data=(s2.game_id, s2.game.state.version))))
        self.assertTrue(s2.game.finished)
        self.assertEqual(repo.games[s2.game_id]["status"], "finished")

    async def test_four_player_game_with_ai_partner_and_team_scoring(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(7, "Me"), gm.PlayerInfo(-2, "B1", "medium"),
                                  gm.PlayerInfo(-3, "Partner", "medium"), gm.PlayerInfo(-4, "B2", "medium")],
                                 kind="practice")
        await self.play_out_vs_ai(mgr, s, 7)
        self.assertEqual(sum(repo.games[s.game_id]["scores"]), 120)
        self.assertEqual(len(repo.games[s.game_id]["scores"]), 2)

    async def test_restart_recovery_continues_the_same_game(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(1, "A"), gm.PlayerInfo(2, "B")], kind="quick")
        for _ in range(5):
            cur = s.game.current_user
            seat = s.game.seat_of(cur)
            await mgr.handle_move(cur, s.game_id, s.game.state.version, s.game.state.hands[seat][0])
        before = json.loads(json.dumps(s.game.to_dict()))
        mgr2, _, app2 = make_manager()               # "restarted" process, same database
        mgr2.repo = repo
        self.assertEqual(await mgr2.restore(), 1)
        s2 = mgr2.sessions[s.game_id]
        self.assertEqual(s2.game.to_dict(), before)
        self.assertEqual({c for c, _ in app2.bot.sent}, {1, 2})        # both got their hand again
        cur = s2.game.current_user
        seat = s2.game.seat_of(cur)
        self.assertIsNone(await mgr2.handle_move(cur, s.game_id, s2.game.state.version, s2.game.state.hands[seat][0]))

    async def test_blocked_bot_does_not_crash_the_match(self):
        mgr, repo, app = make_manager()
        app.bot.blocked.add(2)
        s = await mgr.start_game([gm.PlayerInfo(1, "A"), gm.PlayerInfo(2, "B")], kind="quick")
        cur = s.game.current_user
        if cur == 1:
            self.assertIsNone(await mgr.handle_move(1, s.game_id, s.game.state.version, s.game.state.hands[0][0]))
        self.assertFalse(s.game.finished)

    async def test_many_simultaneous_matches(self):
        mgr, repo, app = make_manager()
        sessions = [await mgr.start_game([gm.PlayerInfo(100 + i, f"H{i}"), gm.PlayerInfo(-2, "Bot", "easy")], kind="practice")
                    for i in range(12)]
        await asyncio.gather(*(self.play_out_vs_ai(mgr, s, 100 + i) for i, s in enumerate(sessions)))
        self.assertTrue(all(repo.games[s.game_id]["status"] == "finished" for s in sessions))
        self.assertEqual(mgr.sessions, {})

    async def test_replay_page_and_rematch(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([gm.PlayerInfo(1, "A"), gm.PlayerInfo(2, "B")], kind="quick")
        await mgr.forfeit(1)
        s = await mgr.start_game([gm.PlayerInfo(1, "A"), gm.PlayerInfo(-2, "Bot", "easy")], kind="practice")
        await self.play_out_vs_ai(mgr, s, 1)
        text, kb = await mgr.replay_page(s.game_id, 3)
        self.assertIn("trick 4/20", text)
        msg = await mgr.rematch_vote(1, s.game_id)
        self.assertIn("starting", msg)
        self.assertIn(1, mgr.by_user)


if __name__ == "__main__":
    unittest.main()
