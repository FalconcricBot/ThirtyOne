"""Flood protection, admin error alerts, 31 missions, group leaderboard."""
import asyncio
import logging
import unittest
from types import SimpleNamespace

from tests import fake_telegram

fake_telegram.install()

from services.notifications import alert_admins, format_error_alert            # noqa: E402
from services.rewards import DAILY_MISSIONS, MISSIONS, RewardsService, WEEKLY_MISSIONS, day_key, week_key  # noqa: E402
from tests.test_multiplayer import FakeBot, FakeNotifier, MemRepo               # noqa: E402
from utils import logger as L                                                    # noqa: E402
from utils.ratelimit import RateLimiter                                          # noqa: E402


class RateLimitTests(unittest.TestCase):
    def test_window_limit_and_recovery(self):
        r = RateLimiter(limit=3, window=5)
        self.assertEqual([r.allow(1, now=t) for t in (0, 1, 2, 3)], [True, True, True, False])
        self.assertTrue(r.allow(2, now=3))                           # other users unaffected
        self.assertTrue(r.allow(1, now=6))                           # the oldest hit expired
        r.cleanup(now=100)
        self.assertEqual(r.hits, {})

    def test_warning_is_sent_once_per_window(self):
        r = RateLimiter(limit=1, window=5)
        self.assertEqual([r.should_warn(1, now=t) for t in (0, 1, 2, 6)], [True, False, False, True])


class GuardFloodTests(unittest.IsolatedAsyncioTestCase):
    async def test_flooding_user_is_stopped_but_admins_are_not(self):
        from unittest import mock
        from utils import decorators as D
        calls, answers = [], []

        @D.guard()
        async def handler(update, context):
            calls.append(update.effective_user.id)

        class Repo:
            async def is_banned(self, uid): return False
            async def upsert_user(self, *a): return {}, False

        async def answer(*a, **k): answers.append(a)
        def upd(uid): return SimpleNamespace(effective_user=SimpleNamespace(id=uid, is_bot=False, username="u", full_name="U"),
                                             effective_chat=SimpleNamespace(type="private"), effective_message=None,
                                             callback_query=SimpleNamespace(answer=answer))
        ctx = SimpleNamespace(user_data={}, application=SimpleNamespace(bot_data={"c": SimpleNamespace(repo=Repo())}))
        lim = RateLimiter(limit=3, window=60)
        import dataclasses
        with mock.patch.object(D, "limiter", lim), mock.patch.object(D, "settings", dataclasses.replace(D.settings, admin_ids={99})):
            for _ in range(6):
                await handler(upd(1), ctx)
            for _ in range(6):
                await handler(upd(99), ctx)
        self.assertEqual(calls.count(1), 3)                          # only 3 got through
        self.assertEqual(calls.count(99), 6)                         # admin exempt
        self.assertEqual(len([a for a in answers if a and "Too fast" in str(a[0])]), 3)


class ErrorAlertTests(unittest.IsolatedAsyncioTestCase):
    def test_format_merges_duplicates_and_masks_tokens(self):
        token = "123456789:" + "A" * 35
        text = format_error_alert(["DB down <b>", "DB down <b>", f"bad url https://api.telegram.org/bot{token}/x"] + ["x"] * 2)
        self.assertIn("×2", text)
        self.assertNotIn(token, text)
        self.assertIn("***", text)
        self.assertIn("&lt;b&gt;", text)                              # HTML-escaped
        self.assertIn("5 error(s)", text)

    def test_logging_handler_collects_errors_only(self):
        lg = logging.getLogger("t_alert")
        lg.setLevel(logging.INFO)
        h = L.ErrorCounter()
        lg.addHandler(h)
        L.take_pending_errors()
        lg.info("fine"); lg.warning("meh"); lg.error("boom %s", 1)
        lg.removeHandler(h)
        self.assertEqual(L.take_pending_errors(), ["boom 1"])
        self.assertEqual(L.take_pending_errors(), [])                 # drained

    async def test_alert_reaches_every_admin(self):
        n = FakeNotifier(FakeBot())
        self.assertEqual(await alert_admins(n, {1, 2}, ["x"]), 2)
        self.assertEqual({u for u, _t in n.dms}, {1, 2})
        self.assertEqual(await alert_admins(n, {1, 2}, []), 0)


class MissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_31_missions_progress_and_exclude_practice_for_wins(self):
        repo = MemRepo()
        rw = RewardsService(repo)
        info = {"old_xp": 0, "new_xp": 10, "win_streak": 0, "coins_total": 100}
        r = await rw.after_game_31(7, result="win", kind="practice", info=info, times_31=2)
        prog = await repo.mission_progress(7, day_key(), week_key())
        self.assertEqual(prog["d_31play"][0], 1)                      # practice counts as 'played'
        self.assertNotIn("d_31hit", prog)                             # ...but not wins / reaching 31
        self.assertNotIn("w_31win", prog)
        r = await rw.after_game_31(7, result="win", kind="quick", info=info, times_31=1)
        prog = await repo.mission_progress(7, day_key(), week_key())
        self.assertEqual((prog["d_31play"][0], prog["d_31hit"][0], prog["w_31win"][0]), (2, 1, 1))
        self.assertIn("🔥 Play 2 matches of 31", r["missions_done"])
        self.assertIn("🔥 Reach 31 in a 31 match", r["missions_done"])

    def test_new_missions_are_registered_and_listed(self):
        for key in ("d_31play", "d_31hit", "w_31win"):
            self.assertIn(key, MISSIONS)
        from ui import texts
        t = texts.missions_text({}, True, 1)
        self.assertIn("Play 2 matches of 31", t)
        self.assertIn("Win 5 matches of 31", t)
        self.assertEqual(len({m[0] for m in DAILY_MISSIONS + WEEKLY_MISSIONS}), len(DAILY_MISSIONS + WEEKLY_MISSIONS))


class GroupBoardTests(unittest.TestCase):
    def test_text_and_buttons(self):
        from keyboards.misc_keyboard import group_board_kb
        from ui import texts
        rows = [{"id": 1, "name": "Asha", "xp": 340, "wins": 5, "games": 9}, {"id": 2, "name": "Raj <b>", "xp": 120, "wins": 1, "games": 4}]
        t = texts.group_board_text("Card Club", "thirty_one", rows, 2)
        self.assertIn("🥇 Asha — <b>340</b> XP • 5/9 wins", t)
        self.assertIn("Raj &lt;b&gt;", t)
        self.assertIn("← you", t)
        self.assertIn("No matches yet", texts.group_board_text(None, "briscola", [], 1))
        kb = group_board_kb("briscola")
        self.assertEqual([b.callback_data for b in kb.inline_keyboard[0]], ["gl:briscola", "gl:thirty_one"])

    def test_handlers_registered(self):
        from handlers import leaderboard
        app = SimpleNamespace(h=[], add_handler=lambda h, _a=None: app.h.append(h))
        leaderboard.register(app)
        self.assertIn("groupboard", {getattr(h, "command", None) for h in app.h})
        pats = [h.pattern for h in app.h if getattr(h, "pattern", None)]
        self.assertTrue(all(any(p.search(d) for p in pats) for d in ("gl:briscola", "gl:thirty_one", "lb:global:0")))


if __name__ == "__main__":
    unittest.main()
