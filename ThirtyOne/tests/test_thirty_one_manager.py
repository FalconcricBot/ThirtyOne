"""31 Card Game: live manager (fake Telegram bot + in-memory repo), images, keyboards, handler wiring."""
import asyncio
import json
import random
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from tests import fake_telegram

fake_telegram.install()

from game.thirty_one.ai import choose_action                                        # noqa: E402
from game.thirty_one.cards import label                                              # noqa: E402
from game.thirty_one.engine import ThirtyOneGame                                    # noqa: E402
from game.thirty_one.rules import DEFAULT_CONFIG, ThirtyOneConfig                   # noqa: E402
from keyboards import thirty_one_keyboard as K                                       # noqa: E402
from services import thirty_one_manager as tm                                       # noqa: E402
from services.game_manager import PlayerInfo                                        # noqa: E402
from services.matchmaking import Lobby                                              # noqa: E402
from services.rewards import RewardsService                                         # noqa: E402
from tests.test_multiplayer import FakeBot, FakeJobs, FakeNotifier, MemRepo         # noqa: E402
from ui import thirty_one_images as IMG                                              # noqa: E402


class MemRepo31(MemRepo):
    def __init__(self):
        super().__init__()
        self.g31, self.moves31, self.rounds31, self.cfg31, self.hist31, self.stats31, self.n31 = {}, {}, {}, {}, set(), {}, 0

    async def t31_get_config(self): return dict(self.cfg31)
    async def t31_set_config(self, c): self.cfg31 = dict(c)

    async def t31_create_game(self, *, kind, mode, seed, config, state, players, room_code, group_chat_id,
                              tournament_id=None, tournament_match=None):
        self.n31 += 1
        self.g31[self.n31] = dict(id=self.n31, kind=kind, mode=mode, status="active", seed=seed, config=config,
                                  state=json.loads(json.dumps(state)), room_code=room_code, group_chat_id=group_chat_id,
                                  tournament_id=tournament_id, tournament_match=tournament_match, players=players,
                                  winner_seats=[])
        self.moves31[self.n31], self.rounds31[self.n31] = [], []
        return self.n31

    async def t31_record_move(self, gid, no, round_no, seat, action, card, state):
        assert not self.moves31[gid] or no > self.moves31[gid][-1][0], "move numbers must strictly increase (unique per game)"
        self.moves31[gid].append((no, round_no, seat, action, card))
        self.g31[gid]["state"] = json.loads(json.dumps(state))

    async def t31_save_state(self, gid, state): self.g31[gid]["state"] = json.loads(json.dumps(state))
    async def t31_record_round(self, gid, info): self.rounds31[gid].append(info)
    async def t31_set_group_message(self, *a): pass

    async def t31_finish_game(self, gid, state, winner_seats, placements):
        self.g31[gid].update(state=state, status="finished", winner_seats=winner_seats, placements=placements)

    async def t31_cancel_game(self, gid): self.g31[gid]["status"] = "cancelled"

    async def t31_load_active_games(self):
        return [dict(g, players=[dict(p, seat=i) for i, p in enumerate(g["players"])]) for g in self.g31.values()
                if g["status"] == "active"]

    async def t31_get_game(self, gid):
        g = self.g31.get(gid)
        return dict(g, players=[dict(p, seat=i) for i, p in enumerate(g["players"])]) if g else None

    async def t31_apply_result(self, uid, *, game_id, result, placement, players, mode, kind, rounds, best_score,
                               times_31, knock_wins, knock_losses, xp, coins, opponents):
        if (uid, game_id) in self.hist31:
            return None
        self.hist31.add((uid, game_id))
        p = self.player(uid)
        old = p["xp"]
        st = self.stats31.setdefault(uid, dict(matches=0, wins=0, losses=0, draws=0, rounds=0, times_31=0, practice=0, xp=0))
        if kind == "practice":
            st["practice"] += 1
        else:
            st["matches"] += 1; st["rounds"] += rounds; st["times_31"] += times_31; st["xp"] += xp
            st["wins" if result == "win" else ("draws" if result == "draw" else "losses")] += 1
        p["xp"] += xp; p["coins"] += coins
        return dict(old_xp=old, new_xp=p["xp"], win_streak=0, coins_total=p["coins"])


def make_manager():
    app = SimpleNamespace(bot=FakeBot(), job_queue=FakeJobs())
    repo = MemRepo31()
    mgr = tm.ThirtyOneManager(app, repo, Lobby(), RewardsService(repo), FakeNotifier(app.bot))
    return mgr, repo, app


class ManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        p = mock.patch("services.thirty_one_manager.random.uniform", return_value=0.0)
        p.start(); self.addCleanup(p.stop)

    async def drive(self, mgr, s, humans, timeout=40):
        """Play the human seats with the medium AI until the match is over (AI seats move by themselves)."""
        end = time.time() + timeout
        while not s.game.finished and time.time() < end:
            st = s.game.state
            if st.phase == "between":
                s.next_round_at = 0
                await mgr.tick()
            elif st.turn in s.ai:
                await asyncio.sleep(0.005)
            else:
                uid = st.players[st.turn]
                act, arg = choose_action(s.game.observation(st.turn), "medium")
                code = {"draw": "dr", "take": "tk", "knock": "kn", "declare": "d31", "discard": "ds"}[act]
                alert = await mgr.handle_action(uid, s.game_id, st.version, code, arg)
                self.assertIsNone(alert, alert)
        self.assertTrue(s.game.finished, "match did not finish in time")

    async def test_practice_match_to_the_end_with_persistence_and_rewards(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(5, "Me"), PlayerInfo(-2, "Bot", "easy")], kind="practice")
        await self.drive(mgr, s, {5})
        g = repo.g31[s.game_id]
        self.assertEqual(g["status"], "finished")
        self.assertEqual(len(g["winner_seats"]), 1)
        self.assertGreaterEqual(len(repo.rounds31[s.game_id]), 3)
        self.assertTrue(all(c is None for (_n, _r, _s, a, c) in repo.moves31[s.game_id] if a == "draw"))   # drawn cards stay private
        self.assertEqual(repo.stats31[5]["practice"], 1)
        self.assertGreater(repo.players[5]["xp"], 0)
        self.assertEqual((mgr.sessions, mgr.by_user), ({}, {}))
        self.assertNotIn(5, mgr.lobby.playing)
        self.assertGreater(len(app.bot.edits), 10)             # messages are edited in place
        self.assertLess(len(app.bot.sent), 8)

    async def test_security_phases_and_stale_buttons(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B")], kind="quick")
        cur = s.game.current_user
        other = 2 if cur == 1 else 1
        v = s.game.state.version
        hand = s.game.state.hands[s.game.seat_of(cur)]
        self.assertIn("Not your turn", await mgr.handle_action(other, s.game_id, v, "dr", None))
        self.assertIn("draw", (await mgr.handle_action(cur, s.game_id, v, "ds", hand[0])).lower())      # wrong phase
        self.assertIn("not a player", await mgr.handle_action(999, s.game_id, v, "dr", None))
        self.assertIn("expired", await mgr.handle_action(cur, 4242, v, "dr", None))
        self.assertIn("Unknown", await mgr.handle_action(cur, s.game_id, v, "zz", None))
        self.assertIsNone(await mgr.handle_action(cur, s.game_id, v, "dr", None))
        self.assertIn("outdated", await mgr.handle_action(cur, s.game_id, v, "dr", None))              # double tap
        v2 = s.game.state.version
        foreign = s.game.state.hands[s.game.seat_of(other)][0]
        self.assertIn("not in your hand", await mgr.handle_action(cur, s.game_id, v2, "ds", foreign))
        self.assertEqual(len(repo.moves31[s.game_id]), 1)

    async def test_cards_are_never_shown_in_the_group(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B"), PlayerInfo(3, "C")], kind="room",
                                 group_chat_id=-500)
        cur = s.game.current_user
        await mgr.handle_action(cur, s.game_id, s.game.state.version, "dr", None)
        seat = s.game.seat_of(cur)
        await mgr.handle_action(cur, s.game_id, s.game.state.version, "ds", s.game.state.hands[seat][0])
        group = [t for c, t in app.bot.sent if c == -500] + [t for c, _m, t in app.bot.edits if c == -500]
        self.assertTrue(group)
        for hand in s.game.state.hands:
            for card in hand:
                self.assertFalse(any(f"[ <b>{label(card)}</b> ]" in t for t in group))
        self.assertTrue(any("YOUR CARDS" in t for c, t in app.bot.sent if c in (1, 2, 3)))

    def group_pings(self, app, chat=-500):
        return [m for m in app.bot.markups if m[0] == chat and "Your cards are in the bot chat" in m[1]]

    async def full_turn(self, mgr, s):
        st = s.game.state
        uid, seat = st.players[st.turn], st.turn
        self.assertIsNone(await mgr.handle_action(uid, s.game_id, st.version, "dr", None))
        self.assertIsNone(await mgr.handle_action(uid, s.game_id, s.game.state.version, "ds", s.game.state.drawn_card))

    async def test_group_turn_ping_tags_the_player_with_an_open_cards_button(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "Asha"), PlayerInfo(2, "Rahul"), PlayerInfo(3, "Zoya")], kind="room",
                                 group_chat_id=-500)
        pings = self.group_pings(app)
        self.assertEqual(len(pings), 1)                                             # pinged when the match starts
        cur = s.game.current_user
        self.assertIn(f'<a href="tg://user?id={cur}">{s.names[s.game.seat_of(cur)]}</a>', pings[0][1])   # real @-style tag
        btn = pings[0][2].inline_keyboard[0][0]
        self.assertEqual(btn.url, f"https://t.me/{tm.settings.bot_username}?start=hand")
        self.assertIn("Open my cards", btn.text)
        first_id = pings[0][3]
        await self.full_turn(mgr, s)
        pings = self.group_pings(app)
        self.assertEqual(len(pings), 2)                                             # next player is tagged...
        self.assertIn((-500, first_id), app.bot.deleted)                            # ...and the old ping is removed
        nxt = s.game.current_user
        self.assertIn(f"tg://user?id={nxt}", pings[1][1])
        self.assertNotEqual(nxt, cur)
        # no hand information in any ping
        for _c, text, _k, _m in pings:
            self.assertNotIn("[ <b>", text)

    async def test_no_tag_when_notifications_are_off_and_dm_fallback_when_group_fails(self):
        mgr, repo, app = make_manager()
        repo.player(1)["notify"] = False; repo.player(2)["notify"] = False
        s = await mgr.start_game([PlayerInfo(1, "Asha"), PlayerInfo(2, "Rahul")], kind="room", group_chat_id=-500)
        ping = self.group_pings(app)[0][1]
        self.assertNotIn("tg://user", ping)                                         # plain name, no push-tag
        mgr2, repo2, app2 = make_manager()
        app2.bot.blocked.add(-500)                                                  # group message cannot be sent
        s2 = await mgr2.start_game([PlayerInfo(1, "Asha"), PlayerInfo(2, "Rahul")], kind="room", group_chat_id=-500)
        self.assertTrue(any("Your turn" in t for _u, t in mgr2.notifier.dms))       # falls back to a DM ping

    async def test_dm_only_matches_get_a_dm_ping_but_practice_does_not(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B")], kind="quick")
        n0 = len([1 for _u, t in mgr.notifier.dms if "Your turn" in t])
        await self.full_turn(mgr, s)
        self.assertGreater(len([1 for _u, t in mgr.notifier.dms if "Your turn" in t]), n0)
        mgr2, repo2, app2 = make_manager()
        p = await mgr2.start_game([PlayerInfo(5, "Me"), PlayerInfo(-2, "Bot", "easy")], kind="practice")
        await self.drive(mgr2, p, {5})
        self.assertFalse(any("Your turn" in t for _u, t in mgr2.notifier.dms))

    async def play_round_in_group(self, images: bool):
        mgr, repo, app = make_manager()
        for uid in (1, 2):
            repo.player(uid)["table_images"] = images
            repo.player(uid)["hand_images"] = images
        s = await mgr.start_game([PlayerInfo(1, "Asha"), PlayerInfo(2, "Rahul")], kind="room", group_chat_id=-500)
        g = s.game
        g.state.hands = [["AH", "KH", "9H"], ["2C", "3D", "5S"]]
        g.state.turn, g.state.phase = 0, "draw"
        v = g.state.version
        self.assertIsNone(await mgr.handle_action(1, s.game_id, v, "kn", None))
        st = g.state
        self.assertEqual(st.turn, 1)
        self.assertIsNone(await mgr.handle_action(2, s.game_id, st.version, "dr", None))
        self.assertIsNone(await mgr.handle_action(2, s.game_id, g.state.version, "ds", g.state.drawn_card))
        self.assertEqual((g.state.phase, g.state.lives), ("between", [3, 2]))
        group = [t for c, _m, t in app.bot.edits if c == -500 and t] + [t for c, t in app.bot.sent if c == -500]
        return group, app

    async def test_group_gets_the_round_result_with_everyones_lives_left_text_mode(self):
        group, app = await self.play_round_in_group(images=False)
        result = [t for t in group if "ROUND 1 RESULT" in t]
        self.assertTrue(result, "no round result reached the group")
        t = result[-1]
        self.assertIn("Lives left", t)
        self.assertIn("Asha 3 ❤️", t)
        self.assertIn("Rahul 2 ❤️", t)
        self.assertIn("Rahul −1❤️", t)                                      # who lost the life
        self.assertIn("A♥ K♥ 9♥ = <b>30</b>", t)                            # revealed cards + score (round is over)

    async def test_group_gets_the_round_result_as_a_caption_in_image_mode(self):
        group, app = await self.play_round_in_group(images=True)
        t = [t for t in group if "ROUND 1 RESULT" in t][-1]
        self.assertIn("Lives left", t)
        self.assertIn("Rahul 2 ❤️", t)
        self.assertLessEqual(len(t), 1024)

    def test_standings_text_for_every_mode(self):
        from ui import thirty_one_texts as T
        info = {"no": 4, "reason": "declare31", "trigger": 0, "knocker": None, "scores": [31, 20, None], "hands": [["AH", "KH", "QH"], ["2C", "3D", "5S"], []],
                "losers": [1], "life_loss": [0, 1, 0], "eliminated": [1], "void": False, "note": "", "lives": [3, 0, 0], "totals": [31.0, 20.0, 5.5]}
        lives = T.round_caption(info, ["A", "B", "C"], ThirtyOneConfig(), 8)
        self.assertIn("A 3 ❤️", lives); self.assertIn("B 💀", lives); self.assertIn("Next round in 8s", lives)
        pts = T.reveal_text(info, ["A", "B", "C"], ThirtyOneConfig(mode="points"))
        self.assertIn("Totals:", pts); self.assertIn("A 31", pts); self.assertIn("C — out", pts)

    async def test_last_group_ping_is_removed_when_the_match_ends(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B")], kind="room", group_chat_id=-500)
        last = self.group_pings(app)[-1][3]
        await mgr.forfeit(1)
        self.assertIn((-500, last), app.bot.deleted)

    async def timeout(self, mgr, s):
        await mgr._timeout_job(SimpleNamespace(job=SimpleNamespace(data=(s.game_id, s.game.state.version))))

    async def test_first_missed_turn_is_skipped_without_autoplay_second_removes(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(3, "C"), PlayerInfo(4, "D")], kind="quick")
        g = s.game
        seat = g.state.turn
        uid = g.state.players[seat]
        hand, v = list(g.state.hands[seat]), g.state.version
        await self.timeout(mgr, s)                                                    # 1st miss -> skipped
        self.assertFalse(g.finished)
        self.assertEqual((s.strikes[seat], g.state.version), (1, v + 1))              # one 'skip' move, nothing else
        self.assertEqual(g.state.hands[seat], hand)                                   # NO auto-play: cards untouched
        self.assertNotEqual(g.state.turn, seat)
        self.assertEqual(repo.moves31[s.game_id][-1][3], "skip")
        self.assertIn("skipped", s.last_action)
        self.assertTrue(any(u == uid and "skipped" in t for u, t in mgr.notifier.dms))
        await mgr._timeout_job(SimpleNamespace(job=SimpleNamespace(data=(s.game_id, v))))   # stale timer ignored
        self.assertEqual(g.state.version, v + 1)
        # the other player moves, then the first one misses AGAIN -> removed
        await self.full_turn(mgr, s)
        self.assertEqual(g.state.turn, seat)
        await self.timeout(mgr, s)
        self.assertTrue(g.finished)
        self.assertEqual(repo.g31[s.game_id]["status"], "finished")
        self.assertIn(uid, s.left)
        self.assertTrue(any(u == uid and "removed" in t for u, t in mgr.notifier.dms))
        self.assertEqual(repo.players[uid]["xp"], 0)                                  # removed player earns nothing

    async def test_playing_in_between_resets_the_miss_counter(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(3, "C"), PlayerInfo(4, "D")], kind="quick")
        g = s.game
        seat = g.state.turn
        await self.timeout(mgr, s)                                                    # miss #1
        await self.full_turn(mgr, s)                                                  # other player
        self.assertEqual(g.state.turn, seat)
        await self.full_turn(mgr, s)                                                  # this player plays normally
        self.assertEqual(s.strikes[seat], 0)
        await self.full_turn(mgr, s)                                                  # other again
        await self.timeout(mgr, s)                                                    # a miss again counts as the FIRST
        self.assertFalse(g.finished)
        self.assertEqual(s.strikes[seat], 1)

    async def test_missing_after_drawing_puts_the_card_back(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(3, "C"), PlayerInfo(4, "D")], kind="quick")
        g = s.game
        seat, uid = g.state.turn, g.state.players[g.state.turn]
        hand, deck_top = list(g.state.hands[seat]), g.state.draw_pile[-1]
        self.assertIsNone(await mgr.handle_action(uid, s.game_id, g.state.version, "dr", None))
        self.assertEqual(len(g.state.hands[seat]), 4)
        s.strikes[seat] = 0
        await self.timeout(mgr, s)                                                    # drew but never discarded
        self.assertEqual(g.state.hands[seat], hand)
        self.assertEqual(g.state.draw_pile[-1], deck_top)                             # drawn card is back on the deck
        self.assertEqual(g.state.phase, "draw")
        self.assertNotEqual(g.state.turn, seat)

    async def test_forfeit_policy_removes_on_the_first_miss(self):
        import dataclasses
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(3, "C"), PlayerInfo(4, "D")], kind="quick")
        with mock.patch.object(tm, "settings", dataclasses.replace(tm.settings, timeout_policy="forfeit")):
            await self.timeout(mgr, s)
        self.assertTrue(s.game.finished)

    async def test_forfeit_in_a_three_player_match(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B"), PlayerInfo(3, "C")], kind="quick")
        self.assertTrue(await mgr.forfeit(2))
        self.assertFalse(s.game.finished)
        self.assertNotIn(2, mgr.by_user)
        self.assertTrue(await mgr.forfeit(3))
        self.assertTrue(s.game.finished)
        self.assertEqual(repo.g31[s.game_id]["winner_seats"], [0])
        self.assertEqual(repo.players[2]["xp"], 0)                                         # leavers earn nothing
        self.assertGreater(repo.players[1]["xp"], 0)
        self.assertEqual(mgr.sessions, {})

    async def test_restart_recovery_continues_the_same_match(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B"), PlayerInfo(3, "C")], kind="quick")
        for _ in range(8):
            st = s.game.state
            uid = st.players[st.turn]
            act, arg = choose_action(s.game.observation(st.turn), "medium")
            await mgr.handle_action(uid, s.game_id, st.version, {"draw": "dr", "take": "tk", "knock": "kn", "declare": "d31", "discard": "ds"}[act], arg)
        before = json.loads(json.dumps(s.game.to_dict()))
        mgr2, _, app2 = make_manager()
        mgr2.repo = repo
        self.assertEqual(await mgr2.restore(), 1)
        s2 = mgr2.sessions[s.game_id]
        self.assertEqual(s2.game.to_dict(), before)
        self.assertEqual({c for c, _ in app2.bot.sent}, {1, 2, 3})
        st = s2.game.state
        uid = st.players[st.turn]
        act, arg = choose_action(s2.game.observation(st.turn), "medium")
        self.assertIsNone(await mgr2.handle_action(uid, s.game_id, st.version, {"draw": "dr", "take": "tk", "knock": "kn", "declare": "d31", "discard": "ds"}[act], arg))

    async def test_restore_during_the_reveal_pause_starts_the_next_round(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B")], kind="quick")
        g = s.game
        g.state.hands = [["AH", "KH", "9H"], ["2C", "3D", "5S"]]
        g.state.turn, g.state.phase = 0, "draw"
        await mgr.handle_action(1 if g.current_user == 1 else 2, s.game_id, g.state.version, "kn", None) if False else None
        g.apply(0, "knock"); g.apply(1, "draw"); g.apply(1, "discard", g.state.drawn_card)
        self.assertEqual(g.state.phase, "between")
        await repo.t31_save_state(s.game_id, g.to_dict())
        mgr2, _, _ = make_manager(); mgr2.repo = repo
        await mgr2.restore()
        s2 = mgr2.sessions[s.game_id]
        s2.next_round_at = 0
        await mgr2.tick()
        self.assertEqual((s2.game.state.round_no, s2.game.state.phase), (2, "draw"))

    async def test_blocked_bot_does_not_crash_the_match(self):
        mgr, repo, app = make_manager()
        app.bot.blocked.add(2)
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(2, "B")], kind="quick")
        cur = s.game.current_user
        if cur == 1:
            self.assertIsNone(await mgr.handle_action(1, s.game_id, s.game.state.version, "dr", None))
        self.assertFalse(s.game.finished)

    async def test_many_simultaneous_matches(self):
        mgr, repo, app = make_manager()
        ss = [await mgr.start_game([PlayerInfo(100 + i, f"H{i}"), PlayerInfo(-2, "Bot", "medium")], kind="practice")
              for i in range(8)]
        await asyncio.gather(*(self.drive(mgr, s, {s.game.state.players[0]}, 80) for s in ss))
        self.assertTrue(all(repo.g31[s.game_id]["status"] == "finished" for s in ss))
        self.assertEqual(mgr.sessions, {})

    async def test_rematch(self):
        mgr, repo, app = make_manager()
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(-2, "Bot", "easy")], kind="practice")
        await mgr.forfeit(1)
        self.assertIn("starting", await mgr.rematch_vote(1, s.game_id))
        self.assertIn(1, mgr.by_user)

    async def test_points_mode_and_admin_config_reach_new_games(self):
        mgr, repo, app = make_manager()
        repo.cfg31 = {"start_lives": 5, "turn_timeout": 30, "knock_enabled": False}
        cfg = await mgr.config(mode="points")
        self.assertEqual((cfg.mode, cfg.start_lives, cfg.turn_timeout, cfg.knock_enabled), ("points", 5, 30, False))
        repo.cfg31 = {"min_players": 9}                                                   # corrupt config -> safe defaults
        self.assertEqual((await mgr.config()).min_players, DEFAULT_CONFIG.min_players)
        s = await mgr.start_game([PlayerInfo(1, "A"), PlayerInfo(-2, "Bot", "medium")], kind="practice", cfg=cfg)
        self.assertEqual(s.game.state.lives, [0, 0])

    def test_reward_formula(self):
        w, l = tm.game_rewards_31("win", 1, 4, 5, 1, "quick"), tm.game_rewards_31("loss", 3, 4, 5, 0, "quick")
        self.assertGreater(w[0], l[0])
        self.assertEqual(tm.game_rewards_31("win", 1, 2, 5, 0, "practice")[0], round(tm.game_rewards_31("win", 1, 2, 5, 0, "quick")[0] * .4))
        self.assertEqual(tm.game_rewards_31("loss", 2, 2, 3, 0, "quick", forfeited=True), (0, 0))


class TournamentCompatibility(unittest.TestCase):
    def test_result_shape_matches_what_the_tournament_code_expects(self):
        g = ThirtyOneGame.new([10, 20], ThirtyOneConfig(start_lives=1), seed=1)
        g.eliminate(0)
        r = g.result()
        self.assertFalse(r["draw"])
        win_seat = next(s for s in (0, 1) if g.side_of(s) in r["winner_sides"])
        self.assertEqual(win_seat, 1)


class ImagesAndKeyboards(unittest.TestCase):
    def test_renderers(self):
        from PIL import Image
        info = {"no": 2, "reason": "knock", "trigger": 0, "knocker": 0, "scores": [30, 22, None], "hands": [["AH", "KH", "9H"], ["2C", "3D", "5S"], []],
                "losers": [1], "life_loss": [0, 1, 0], "eliminated": [], "void": False, "note": "", "lives": [3, 2, 0], "totals": [0, 0, 0]}
        shots = [
            IMG.render_hand(hand=["AH", "KH", "QH"], counting=["AH", "KH", "QH"], score=31, new_card="QH", lives=3, total_lives=3,
                            top_discard="7S", draw_count=20, status="YOUR TURN — declare 31!", round_no=1),
            IMG.render_hand(hand=["AS", "9S", "4D", "10S"], counting=["AS", "9S", "10S"], score=30, new_card="10S", lives=1, total_lives=5,
                            top_discard=None, draw_count=0, status="Waiting for राहुल 🔥", round_no=9, points_mode=True, total_points=44.5),
            IMG.render_hand(hand=["7C", "7D", "7H"], counting=["7C", "7D", "7H"], score=30.5, new_card=None, lives=2, total_lives=3,
                            top_discard="2C", draw_count=3, status="x", round_no=1),
            IMG.render_table(room="31-12345", mode_label="LIVES MODE", names=["A", "B", "C", "D", "E", "F", "G"], lives=[3, 2, 1, 0, 3, 3, 2],
                             total_lives=3, totals=[0] * 7, points_mode=False, active=[1, 1, 1, 0, 1, 1, 1], turn=2, knocker=1,
                             final_left=[2, 4], draw_count=20, discard_top="9D", discard_count=7, round_no=4, last_action="B knocked!",
                             status="final turns"),
            IMG.render_table(room="31-12345", mode_label="POINTS MODE", names=["निहार", "Bot 🤖"], lives=[0, 0], total_lives=0,
                             totals=[12.5, 40], points_mode=True, active=[1, 1], turn=None, knocker=None, final_left=[], draw_count=0,
                             discard_top=None, discard_count=0, round_no=5, winner_text="Bot wins the match!"),
            IMG.render_reveal(room="31-12345", names=["A", "B", "C"], round_info=info, points_mode=False, total_lives=3,
                              headline="A knocked — B loses a life", footer="Next round in 8s"),
            IMG.render_reveal(room="31-12345", names=["A"] * 7, round_info={**info, "scores": [30, 22, 10, 9, 8, 7, 6], "hands": [["AH", "KH", "9H"]] * 7,
                              "life_loss": [0] * 7, "losers": [], "eliminated": [], "totals": [10, 20, 30, 40, 50, 60, 70]}, points_mode=True, total_lives=0,
                              headline="x", footer="y", match_over=True),
        ]
        for buf in shots:
            self.assertEqual(buf.getvalue()[:8], b"\x89PNG\r\n\x1a\n")
            Image.open(buf)

    def test_action_keyboards_per_phase(self):
        def texts(kb): return [b.text for r in kb.inline_keyboard for b in r]
        draw = K.action_kb(5, 3, my_turn=True, phase="draw", hand=["AH", "KH", "QH"], top="7S", can_knock=True, can_declare=True, taken=None)
        t = texts(draw)
        self.assertTrue(any("Draw" in x for x in t) and any("Take 7♠" in x for x in t) and any("KNOCK" in x for x in t)
                        and any("DECLARE 31" in x for x in t))
        disc = K.action_kb(5, 4, my_turn=True, phase="discard", hand=["AH", "KH", "QH", "7S"], top="2C", can_knock=False, can_declare=False, taken="7S")
        self.assertEqual(sum("🗑" in x for x in texts(disc)), 3)                       # can't throw back the card just taken
        self.assertFalse(any("7♠" in x for x in texts(disc)))
        wait = K.action_kb(5, 4, my_turn=False, phase="draw", hand=["AH"], top="2C", can_knock=True, can_declare=True, taken=None)
        self.assertEqual(len(wait.inline_keyboard), 1)                                 # only score / rules / leave
        for kb in (draw, disc, wait):
            for r in kb.inline_keyboard:
                for b in r:
                    self.assertLessEqual(len(b.callback_data.encode()), 64)

    def test_admin_config_cycle_keeps_min_below_max(self):
        cfg = DEFAULT_CONFIG.to_dict()
        for key in K.CONFIG_CHOICES:
            seen = set()
            cur = dict(cfg)
            for _ in range(len(K.CONFIG_CHOICES[key]) + 1):
                cur = K.next_config_value(cur, key)
                ThirtyOneConfig.from_dict(cur)                                          # always valid
                seen.add(cur[key])
            self.assertEqual(seen, set(K.CONFIG_CHOICES[key]), key)
        c = K.next_config_value({**cfg, "min_players": 4, "max_players": 4}, "min_players")
        self.assertLessEqual(c["min_players"], c["max_players"])
        K.config_kb(cfg)

    def test_every_31_button_has_a_handler(self):
        import handlers.thirty_one as H
        from handlers import (admin, friends, game as game_h, leaderboard, matchmaking, menu as menu_h, profile,
                              rewards as rewards_h, room as room_h, start, tournament)
        from keyboards import main_menu
        app = SimpleNamespace(h=[], add_handler=lambda h, _a=None: app.h.append(h))
        for mod in (start, menu_h, room_h, matchmaking, game_h, H, profile, leaderboard, rewards_h, friends, tournament, admin):
            mod.register(app)
        pats = [h.pattern for h in app.h if getattr(h, "pattern", None)]
        cmds = {getattr(h, "command", None) for h in app.h}
        self.assertTrue({"thirtyone", "games", "t31config", "t31set", "create_tournament31"} <= cmds)
        cfg = ThirtyOneConfig()
        room = SimpleNamespace(code="31-12345", full=False, players=[(1, "a")], mode=4)
        kbs = [K.games_menu_kb(), K.menu_kb(), K.back_kb(), K.mode_pick_kb(cfg), K.size_kb("lives", cfg), K.quick_pick_kb(cfg),
               K.quick_cancel_kb(), K.ai_level_kb(), K.ai_opp_kb("hard"), K.room_kb(room), K.group_kb(), K.confirm_leave_kb(3),
               K.result_kb(3), K.lb_kb("week", 1, 3), K.history_kb(1, 3), K.config_kb(cfg.to_dict()),
               K.action_kb(5, 4, my_turn=True, phase="discard", hand=["AH", "10S", "KH", "QH"], top="2C", can_knock=False, can_declare=False, taken=None),
               K.action_kb(5, 4, my_turn=True, phase="draw", hand=["AH"], top="2C", can_knock=True, can_declare=True, taken=None),
               main_menu.main_menu_kb()]
        data = {b.callback_data for kb in kbs for r in kb.inline_keyboard for b in r if b.callback_data}
        data |= {f"t31:lb:{k}:0" for k, _ in K.LB_TABS}
        missing = sorted(d for d in data if not any(p.search(d) for p in pats))
        self.assertEqual(missing, [])
        self.assertTrue(any(d == "m:games" for d in data))
        self.assertTrue(any(d == "cg:31" for d in data))


if __name__ == "__main__":
    unittest.main()
