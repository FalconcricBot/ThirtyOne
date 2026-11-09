"""Runs live 31 Card Game matches: turns, timers, AI, reveal pauses, persistence and recovery.
Same concurrency model as the Briscola manager: one asyncio.Lock per game, state saved after every action."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from telegram.constants import ParseMode
from telegram.error import TelegramError

from config import settings
from game.thirty_one.ai import choose_action
from game.thirty_one.cards import label
from game.thirty_one.engine import (CardNotInHand, GameOver, IllegalAction, NotYourTurn, StaleMove, ThirtyOneGame,
                                    UnknownPlayer, WrongPhase)
from game.thirty_one.rules import DEFAULT_CONFIG, ThirtyOneConfig
from game.thirty_one.scoring import counting_cards, hand_score, is_31
from keyboards import thirty_one_keyboard as K
from services.game_manager import PlayerInfo
from services.messaging import MsgRef, Publisher
from utils.helpers import esc, mention
from ui import thirty_one_images as IMG
from ui import thirty_one_texts as T

log = logging.getLogger(__name__)
ACTIONS = {"dr": "draw", "tk": "take", "kn": "knock", "d31": "declare", "ds": "discard"}


def game_rewards_31(result: str, placement: int, players: int, rounds: int, times_31: int, kind: str,
                    forfeited: bool = False) -> tuple[int, int]:
    """-> (xp, coins). Practice pays 40%, tournaments 150%, a quitter earns nothing."""
    if forfeited:
        return 0, 0
    if result == "win":
        xp, coins = 60 + 6 * players + 3 * rounds, 40 + 5 * players
    elif result == "draw":
        xp, coins = 30 + 2 * rounds, 20
    else:
        xp, coins = max(10, 28 - 6 * (placement - 1)) + rounds, max(5, 14 - 3 * (placement - 1))
    xp += 8 * times_31
    if kind == "practice":
        xp, coins = round(xp * 0.4), round(coins * 0.4)
    elif kind == "tournament":
        xp, coins = round(xp * 1.5), round(coins * 1.5)
    return xp, coins


@dataclass
class Session31:
    game_id: int
    game: ThirtyOneGame
    names: list[str]
    ai: dict[int, str]
    kind: str
    room_code: str
    group_chat_id: int | None = None
    tournament_id: int | None = None
    tournament_match: str | None = None
    group_msg: MsgRef | None = None
    group_ping: int | None = None                    # the 'it's your turn @name' message in the group
    dm_msgs: dict[int, MsgRef] = field(default_factory=dict)
    pings: dict[int, int] = field(default_factory=dict)
    hand_img: dict[int, bool] = field(default_factory=dict)
    notify: dict[int, bool] = field(default_factory=dict)
    table_img: bool = True
    strikes: dict[int, int] = field(default_factory=dict)
    last_action: str = ""
    deadline: float | None = None
    next_round_at: float | None = None
    reveal: dict | None = None
    left: set[int] = field(default_factory=set)      # humans who quit / were removed (no more updates for them)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ai_running: bool = False
    last_group_edit: float = 0.0

    @property
    def cfg(self) -> ThirtyOneConfig:
        return self.game.cfg

    @property
    def humans(self) -> dict[int, int]:
        return {i: u for i, u in enumerate(self.game.state.players) if i not in self.ai}

    def seconds_left(self) -> int | None:
        return max(0, int(self.deadline - time.time())) if self.deadline else None


class ThirtyOneManager:
    def __init__(self, application, repo, lobby, rewards, notifier):
        self.app, self.bot = application, application.bot
        self.repo, self.lobby, self.rewards, self.notifier = repo, lobby, rewards, notifier
        self.pub = Publisher(self.bot, notifier)
        self.tournaments = None
        self.sessions: dict[int, Session31] = {}
        self.by_user: dict[int, int] = {}
        self.rematch_votes: dict[int, set[int]] = {}
        self._tasks: set[asyncio.Task] = set()

    # ================================================================ configuration
    async def config(self, **overrides) -> ThirtyOneConfig:
        """Admin-configured defaults (+ per-game overrides such as mode). Invalid saved values fall back safely."""
        saved = await self.repo.t31_get_config()
        try:
            cfg = ThirtyOneConfig.from_dict(saved)
        except (ValueError, TypeError):
            cfg = DEFAULT_CONFIG
        try:
            return cfg.replace(**overrides) if overrides else cfg
        except ValueError:
            return cfg

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # ================================================================ lifecycle
    async def start_game(self, players: list[PlayerInfo], *, kind: str, cfg: ThirtyOneConfig | None = None,
                         group_chat_id: int | None = None, room_code: str | None = None,
                         tournament_id: int | None = None, tournament_match: str | None = None) -> Session31:
        cfg = cfg or await self.config()
        game = ThirtyOneGame.new([p.user_id for p in players], cfg)
        code = room_code or f"31-{random.randint(10000, 99999)}"
        gid = await self.repo.t31_create_game(
            kind=kind, mode=cfg.mode, seed=game.state.seed, config=cfg.to_dict(), state=game.to_dict(),
            room_code=code, group_chat_id=group_chat_id, tournament_id=tournament_id, tournament_match=tournament_match,
            players=[{"seat": i, "user_id": None if p.ai_level else p.user_id, "name": p.name, "ai_level": p.ai_level}
                     for i, p in enumerate(players)])
        s = Session31(game_id=gid, game=game, names=[p.name for p in players],
                      ai={i: p.ai_level for i, p in enumerate(players) if p.ai_level}, kind=kind, room_code=code,
                      group_chat_id=group_chat_id, tournament_id=tournament_id, tournament_match=tournament_match)
        await self._register(s)
        if game.state.turn not in s.ai:
            s.deadline = time.time() + cfg.turn_timeout
        await self.publish(s)
        await self._ping_turn(s)
        self._after_state_change(s)
        return s

    async def _register(self, s: Session31) -> None:
        self.sessions[s.game_id] = s
        for seat, uid in s.humans.items():
            self.by_user[uid] = s.game_id
            self.lobby.set_playing([uid])
            p = await self.repo.get_player(uid)
            s.hand_img[uid] = p["hand_images"] if p else settings.default_images
            s.notify[uid] = p["notify"] if p else True
            s.strikes[seat] = 0
            if s.group_chat_id is not None and seat == min(s.humans):
                s.table_img = p["table_images"] if p else settings.default_images

    async def restore(self) -> int:
        n = 0
        for g in await self.repo.t31_load_active_games():
            try:
                game = ThirtyOneGame.from_dict(g["state"])
                ps = g["players"]
                s = Session31(game_id=g["id"], game=game, names=[p["name"] for p in ps],
                              ai={p["seat"]: p["ai_level"] for p in ps if p["ai_level"]}, kind=g["kind"],
                              room_code=g["room_code"] or "31-?????", group_chat_id=g["group_chat_id"],
                              tournament_id=g["tournament_id"], tournament_match=g["tournament_match"])
                await self._register(s)
                if game.state.phase == "between":
                    s.reveal = game.state.last_round
                    self._schedule_next_round(s, 3)
                await self.publish(s, note="♻️ The bot restarted — your match continues!")
                self._after_state_change(s)
                n += 1
            except Exception:
                log.exception("could not restore 31 game %s", g.get("id"))
        return n

    # ================================================================ actions
    async def handle_action(self, uid: int, gid: int, version: int, code: str, arg: str | None) -> str | None:
        """Returns a short alert for the user, or None when the action was accepted."""
        s = self.sessions.get(gid)
        if s is None:
            return "This match has ended or expired."
        action = ACTIONS.get(code)
        if action is None:
            return "Unknown button."
        async with s.lock:
            try:
                seat = s.game.seat_of(uid)
                if s.game.finished:
                    return "This match is over."
                if version != s.game.state.version:
                    self._spawn(self._publish_hand(s, seat, uid))
                    return "↻ That button was outdated — your cards were refreshed."
                s.strikes[seat] = 0
                await self._apply(s, seat, action, arg)
            except NotYourTurn:
                return "⏳ Not your turn yet."
            except WrongPhase as e:
                return str(e)
            except CardNotInHand:
                return "That card is not in your hand."
            except IllegalAction as e:
                return str(e)
            except UnknownPlayer:
                return "You are not a player in this match."
            except StaleMove:
                return "↻ Outdated button."
            except GameOver:
                return "This match is over."
        self._after_state_change(s)
        return None

    def _describe(self, s: Session31, seat: int, action: str, card: str | None) -> str:
        n = s.names[seat]
        return {"draw": f"{n} drew from the deck", "take": f"{n} took {label(card) if card else '?'} from the discard pile",
                "discard": f"{n} discarded {label(card) if card else '?'}", "knock": f"{n} knocked! ✊",
                "declare": f"{n} declared 31! 🎯", "skip": f"⏭ {n} didn't move in time — turn skipped"}[action]

    async def _apply(self, s: Session31, seat: int, action: str, arg: str | None, note: str | None = None) -> None:
        """Apply + persist + publish one action. Caller holds s.lock."""
        g = s.game
        res = g.apply(seat, action, arg)
        public_card = res.card if action in ("take", "discard") else None      # a drawn card stays private
        round_no = g.state.moves[-1][0]
        await self.repo.t31_record_move(s.game_id, res.version, round_no, seat, action, public_card, g.to_dict())
        s.last_action = self._describe(s, seat, action, res.card)
        if res.round_ended:
            await self.repo.t31_record_round(s.game_id, res.round)
            s.reveal, s.deadline = res.round, None
            if res.finished:
                await self._finalize(s)
            else:
                self._schedule_next_round(s, s.cfg.round_pause)
                await self.publish(s)
            return
        s.deadline = time.time() + s.cfg.turn_timeout if g.state.turn not in s.ai else None
        await self.publish(s, note=note)
        if action in ("discard", "knock", "skip"):
            await self._ping_turn(s)

    def _after_state_change(self, s: Session31) -> None:
        if s.game.finished:
            return
        if s.game.state.phase == "between":
            return
        self._arm_timers(s)
        self._kick_ai(s)

    # ================================================================ rounds
    def _schedule_next_round(self, s: Session31, delay: float) -> None:
        s.next_round_at = time.time() + delay
        for j in self.app.job_queue.get_jobs_by_name(f"t31next:{s.game_id}"):
            j.schedule_removal()
        self.app.job_queue.run_once(self._next_round_job, delay, data=(s.game_id, s.game.state.version),
                                    name=f"t31next:{s.game_id}")

    async def _next_round_job(self, context) -> None:
        gid, ver = context.job.data
        s = self.sessions.get(gid)
        if s is not None:
            await self._start_next_round(s, ver)

    async def _start_next_round(self, s: Session31, expect_version: int | None = None) -> None:
        async with s.lock:
            g = s.game
            if g.finished or g.state.phase != "between" or (expect_version is not None and g.state.version != expect_version):
                return
            g.start_next_round()
            s.reveal, s.next_round_at = None, None
            s.last_action = f"Round {g.state.round_no} — new cards dealt"
            await self.repo.t31_save_state(s.game_id, g.to_dict())
            s.deadline = time.time() + s.cfg.turn_timeout if g.state.turn not in s.ai else None
            await self.publish(s)
            await self._ping_turn(s)
        self._after_state_change(s)

    # ================================================================ AI
    def _kick_ai(self, s: Session31) -> None:
        st = s.game.state
        if s.ai_running or s.game.finished or st.phase not in ("draw", "discard") or st.turn not in s.ai:
            return
        s.ai_running = True
        self._spawn(self._ai_loop(s))

    async def _ai_loop(self, s: Session31) -> None:
        try:
            while True:
                async with s.lock:
                    st = s.game.state
                    if s.game.finished or st.phase not in ("draw", "discard") or st.turn not in s.ai:
                        s.ai_running = False
                        self._arm_timers(s)
                        return
                    seat, ver, level = st.turn, st.version, s.ai[st.turn]
                    obs = s.game.observation(seat)
                await asyncio.sleep(random.uniform(1.0, 1.8))
                act, arg = await asyncio.to_thread(choose_action, obs, level)
                async with s.lock:
                    if s.game.finished or s.game.state.version != ver:
                        continue
                    try:
                        await self._apply(s, seat, act, arg)
                    except (IllegalAction, WrongPhase):          # never let a bad AI choice stall the match
                        await self._apply(s, seat, "draw" if s.game.state.phase == "draw" else "discard",
                                          None if s.game.state.phase == "draw" else
                                          next(c for c in s.game.state.hands[seat] if c != s.game.state.taken_from_discard))
        except Exception:
            log.exception("AI loop crashed for 31 game %s", s.game_id)
            s.ai_running = False
        finally:
            if s.game.finished:
                s.ai_running = False

    # ================================================================ timers / AFK
    def _arm_timers(self, s: Session31) -> None:
        jq = self.app.job_queue
        for name in (f"t31turn:{s.game_id}", f"t31warn:{s.game_id}"):
            for j in jq.get_jobs_by_name(name):
                j.schedule_removal()
        st = s.game.state
        if s.game.finished or st.phase not in ("draw", "discard") or st.turn in s.ai:
            return
        t = s.cfg.turn_timeout
        data = (s.game_id, st.version)
        if s.deadline is None:
            s.deadline = time.time() + t
        jq.run_once(self._timeout_job, max(1, s.deadline - time.time()), data=data, name=f"t31turn:{s.game_id}")
        if t > 25:
            jq.run_once(self._warn_job, max(1, s.deadline - time.time() - 15), data=data, name=f"t31warn:{s.game_id}")

    async def _warn_job(self, context) -> None:
        gid, ver = context.job.data
        s = self.sessions.get(gid)
        if s and not s.game.finished and s.game.state.version == ver:
            await self.notifier.dm(s.game.current_user, "⏰ <b>15 seconds left</b> — otherwise your turn is skipped!")

    async def _timeout_job(self, context) -> None:
        gid, ver = context.job.data
        s = self.sessions.get(gid)
        if s is None:
            return
        try:
            async with s.lock:
                g = s.game
                if g.finished or g.state.version != ver or g.state.phase not in ("draw", "discard"):
                    return
                seat = g.state.turn
                uid = g.state.players[seat]
                s.strikes[seat] = s.strikes.get(seat, 0) + 1
                limit = max(1, settings.afk_strikes_limit)
                if settings.timeout_policy == "forfeit" or s.strikes[seat] >= limit:
                    await self.notifier.dm(uid, "🚫 You didn't play again, so you were <b>removed</b> from the match.")
                    await self._forfeit_locked(s, seat, "inactive")
                    return
                # no auto-play: the turn is skipped and the cards stay exactly as they were
                await self.notifier.dm(uid, f"⏰ You didn't play in time — your turn was <b>skipped</b>.\n"
                                            f"Miss {limit - s.strikes[seat]} more in a row and you'll be removed from the match.")
                await self._apply(s, seat, "skip", None)
            self._after_state_change(s)
        except Exception:
            log.exception("timeout handler failed for 31 game %s", gid)

    # ================================================================ finishing
    async def forfeit(self, uid: int) -> bool:
        s = self.sessions.get(self.by_user.get(uid, -1))
        if not s:
            return False
        async with s.lock:
            if s.game.finished:
                return False
            await self._forfeit_locked(s, s.game.seat_of(uid))
        self._after_state_change(s)
        return True

    async def _forfeit_locked(self, s: Session31, seat: int, reason: str = "left") -> None:
        g = s.game
        before_round = g.state.round_no
        uid = g.state.players[seat]
        if seat not in s.ai:                                   # free the player right away (they may join another match)
            s.left.add(uid)
            self.by_user.pop(uid, None)
            self.lobby.set_playing([uid], False)
        g.eliminate(seat)
        s.last_action = (f"{s.names[seat]} was removed (inactive)" if reason == "inactive"
                         else f"{s.names[seat]} left the match")
        await self.repo.t31_save_state(s.game_id, g.to_dict())
        if g.finished:
            await self._finalize(s)
            return
        if g.state.phase == "between" and g.state.last_round and g.state.last_round["no"] == before_round:
            await self.repo.t31_record_round(s.game_id, g.state.last_round)
            s.reveal = g.state.last_round
            self._schedule_next_round(s, s.cfg.round_pause)
        else:
            s.deadline = time.time() + s.cfg.turn_timeout if g.state.turn not in s.ai else None
        await self.publish(s)

    async def _finalize(self, s: Session31) -> None:
        g = s.game
        res = g.result()
        st = g.state
        await self.repo.t31_finish_game(s.game_id, g.to_dict(), res["winner_sides"], res["placements"])
        for name in (f"t31turn:{s.game_id}", f"t31warn:{s.game_id}", f"t31next:{s.game_id}"):
            for j in self.app.job_queue.get_jobs_by_name(name):
                j.schedule_removal()
        humans = s.humans
        summaries: dict[int, dict] = {}
        for seat, uid in humans.items():
            try:
                summaries[uid] = await self._record_result(s, seat, uid, res)
            except Exception:
                log.exception("recording 31 result failed for %s in game %s", uid, s.game_id)
        for uid in humans.values():
            self.by_user.pop(uid, None)
            self.lobby.set_playing([uid], False)
            await self.notifier.delete(uid, s.pings.pop(uid, None))
        if s.group_chat_id is not None:
            await self.notifier.delete(s.group_chat_id, s.group_ping)
            s.group_ping = None
        self.sessions.pop(s.game_id, None)
        s.deadline = None
        forfeit_names = [s.names[x] for x in st.forfeit_seats]
        await self.publish(s, final=(res, summaries, forfeit_names))
        if s.tournament_id is not None and self.tournaments:
            self._spawn(self.tournaments.on_game_finished(s.tournament_id, s.tournament_match, g, humans))

    async def _record_result(self, s: Session31, seat: int, uid: int, res: dict) -> dict:
        st = s.game.state
        place = res["placements"][seat]
        won = seat in res["winner_sides"]
        result = ("draw" if res["draw"] else "win") if won else "loss"
        ps = st.pstats[seat]
        forfeited = seat in st.forfeit_seats
        xp, coins = game_rewards_31(result, place, len(s.names), ps["rounds"], ps["times_31"], s.kind, forfeited)
        opp = ", ".join(s.names[i] for i in range(len(s.names)) if i != seat)[:190]
        info = await self.repo.t31_apply_result(
            uid, game_id=s.game_id, result=result, placement=place, players=len(s.names), mode=s.cfg.mode, kind=s.kind,
            rounds=ps["rounds"], best_score=ps["best"], times_31=ps["times_31"], knock_wins=ps["knock_wins"],
            knock_losses=ps["knock_losses"], xp=xp, coins=coins, opponents=opp)
        if info is None:
            return {"result": result, "xp": 0, "coins": 0}
        extra = await self.rewards.after_game_31(uid, result=result, kind=s.kind, info=info, times_31=ps["times_31"])
        return {**info, **extra, "result": result, "xp": xp, "coins": coins}

    async def _abort(self, s: Session31, text: str) -> None:
        self.sessions.pop(s.game_id, None)
        for name in (f"t31turn:{s.game_id}", f"t31warn:{s.game_id}", f"t31next:{s.game_id}"):
            for j in self.app.job_queue.get_jobs_by_name(name):
                j.schedule_removal()
        await self.repo.t31_cancel_game(s.game_id)
        if s.group_chat_id is not None:
            await self.notifier.delete(s.group_chat_id, s.group_ping)
        for uid in s.humans.values():
            self.by_user.pop(uid, None)
            self.lobby.set_playing([uid], False)
            await self.notifier.dm(uid, text)

    async def cancel_game_silently(self, gid: int) -> None:
        s = self.sessions.get(gid)
        if s:
            async with s.lock:
                await self._abort(s, "🛑 Your tournament match was cancelled by an admin.")

    async def cancel_tournament_games(self, tid: int) -> None:
        for s in [x for x in self.sessions.values() if x.tournament_id == tid]:
            await self.cancel_game_silently(s.game_id)

    async def stop_all(self) -> None:
        for t in list(self._tasks):
            t.cancel()

    async def tick(self) -> None:
        """Safety net (every 30 s): un-stall AI turns, re-arm timers, start overdue rounds."""
        for s in list(self.sessions.values()):
            st = s.game.state
            if s.game.finished:
                continue
            if st.phase == "between":
                if s.next_round_at is None or time.time() > s.next_round_at + 5:
                    await self._start_next_round(s)
            elif st.turn in s.ai:
                self._kick_ai(s)
            elif not self.app.job_queue.get_jobs_by_name(f"t31turn:{s.game_id}"):
                s.deadline = None
                self._arm_timers(s)

    # ================================================================ publishing
    async def publish(self, s: Session31, *, note: str | None = None, final=None) -> None:
        jobs = [self._publish_hand(s, seat, uid, note, final) for seat, uid in s.humans.items()
                if final or uid not in s.left]
        if s.group_chat_id is not None:
            jobs.append(self._publish_group(s, final))
        for r in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(r, Exception):
                log.error("31 publish failed: %r", r)

    def _winner_text(self, s: Session31, res: dict) -> str:
        if res["draw"]:
            return "🤝 It's a draw!"
        return f"{s.names[res['winner_sides'][0]]} wins the match!"

    async def _reveal_photo(self, s: Session31, final=None):
        info = s.reveal
        if info is None:                      # e.g. the match ended because someone left mid-round
            return await self._table_photo(s, winner=self._winner_text(s, final[0])) if final else None
        pm = s.cfg.mode == "points"
        names = [n for n in s.names]
        if final:
            footer, headline = "🏆 " + self._winner_text(s, final[0]), IMG_headline(s, info)
        else:
            footer, headline = f"Next round starts in {s.cfg.round_pause}s", IMG_headline(s, info)
        return await asyncio.to_thread(IMG.render_reveal, room=s.room_code, names=names, round_info=info, points_mode=pm,
                                       total_lives=s.cfg.lives_at_start, headline=headline, footer=footer,
                                       match_over=bool(final))

    async def _table_photo(self, s: Session31, winner: str | None = None):
        v = s.game.public_view()
        return await asyncio.to_thread(
            IMG.render_table, room=s.room_code, mode_label=T.MODE_NAME[v["mode"]].upper(), names=s.names, lives=v["lives"],
            total_lives=s.cfg.lives_at_start, totals=v["totals"], points_mode=v["mode"] == "points", active=v["active"],
            turn=v["turn"], knocker=v["knocker"], final_left=v["final_left"], draw_count=v["draw_count"],
            discard_top=v["discard_top"], discard_count=v["discard_count"], round_no=v["round_no"],
            last_action=s.last_action, status=self._status_line(s, v), winner_text=winner)

    def _status_line(self, s: Session31, v: dict) -> str:
        if v["knocker"] is not None:
            left = ", ".join(s.names[x] for x in v["final_left"])
            return f"✊ {s.names[v['knocker']]} knocked — final turns: {left or '—'}"
        left = s.seconds_left()
        return f"Current turn: {s.names[v['turn']]}" + (f"  •  {left}s" if left else "")

    async def _publish_hand(self, s: Session31, seat: int, uid: int, note: str | None = None, final=None) -> None:
        g, cfg = s.game, s.cfg
        v = g.public_view()
        use_img = s.hand_img.get(uid, True)
        if final:
            res, summaries, forfeits = final
            text = T.final_text(names=s.names, res=res, cfg_mode=cfg.mode, summary=summaries.get(uid), forfeit_names=forfeits)
            photo = await self._reveal_photo(s, final) if use_img else None
            kb = K.result_kb(s.game_id, rematch=s.kind != "tournament")
        elif s.reveal is not None and g.state.phase == "between":
            photo = await self._reveal_photo(s) if use_img else None
            text = (T.round_caption if photo is not None else T.reveal_text)(s.reveal, s.names, cfg, cfg.round_pause)
            kb = K.action_kb(s.game_id, g.state.version, my_turn=False, phase="between", hand=[], top=None,
                             can_knock=False, can_declare=False, taken=None)
        else:
            st = g.state
            hand = list(st.hands[seat])
            score = hand_score(hand, cfg) if hand else 0.0
            my_turn = st.turn == seat and st.phase in ("draw", "discard") and st.active[seat]
            can_decl = my_turn and st.phase == "draw" and is_31(hand)
            can_knock = my_turn and st.phase == "draw" and cfg.knock_enabled and st.knocker is None
            text = T.hand_text(room=s.room_code, names=s.names, seat=seat, view=v, hand=hand, score=score,
                               last_action=s.last_action, deadline=s.seconds_left(), show_table=s.group_chat_id is None,
                               taken=st.taken_from_discard, can_declare_manual=can_decl)
            if note:
                text = f"<i>{T.esc(note)}</i>\n" + text
            if not st.active[seat]:
                text = "💀 <b>You are out of this match.</b> You can keep watching the table.\n" + text
            kb = K.action_kb(s.game_id, st.version, my_turn=my_turn, phase=st.phase, hand=hand, top=v["discard_top"],
                             can_knock=can_knock, can_declare=can_decl, taken=st.taken_from_discard)
            photo = None
            if use_img and hand:
                if my_turn:
                    status = "YOUR TURN — discard one card" if st.phase == "discard" else "YOUR TURN — draw, take or knock"
                    if can_decl:
                        status = "YOUR TURN — declare 31!"
                else:
                    status = f"Waiting for {s.names[st.turn]}"
                photo = await asyncio.to_thread(
                    IMG.render_hand, hand=hand, counting=counting_cards(hand, cfg) if len(hand) == 3 else [], score=score,
                    new_card=st.drawn_card if st.turn == seat else None, lives=st.lives[seat],
                    total_lives=cfg.lives_at_start, top_discard=v["discard_top"], draw_count=v["draw_count"],
                    status=status, round_no=st.round_no, points_mode=cfg.mode == "points", total_points=st.totals[seat],
                    taken=st.taken_from_discard)
        ref, blocked = await self.pub.upsert(uid, s.dm_msgs.get(uid), text, photo, kb)
        if blocked:
            s.dm_msgs.pop(uid, None)
        elif ref:
            s.dm_msgs[uid] = ref

    async def _publish_group(self, s: Session31, final=None) -> None:
        wait = 1.3 - (time.time() - s.last_group_edit)
        if wait > 0 and not final:
            await asyncio.sleep(wait)
        s.last_group_edit = time.time()
        g, v = s.game, s.game.public_view()
        res = final[0] if final else None
        text = T.table_text(room=s.room_code, names=s.names, view=v, last_action=s.last_action,
                            deadline=s.seconds_left(), winner=self._winner_text(s, res) if res else None)
        photo = None
        if s.table_img:
            if final or (s.reveal is not None and g.state.phase == "between"):
                photo = await self._reveal_photo(s, final)
            else:
                photo = await self._table_photo(s)
        if not final and s.reveal is not None and g.state.phase == "between":
            # the group sees the round result (who lost a life, everybody's lives left) - picture caption or full text
            text = (T.round_caption if photo is not None else T.reveal_text)(s.reveal, s.names, s.cfg, s.cfg.round_pause)
        if photo is not None and len(text) > 1000:
            text = text[:999] + "…"
        ref, _blocked = await self.pub.upsert(s.group_chat_id, s.group_msg, text, photo, None if final else K.group_kb())
        if ref and (s.group_msg is None or s.group_msg.message_id != ref.message_id):
            await self.repo.t31_set_group_message(s.game_id, s.group_chat_id, ref.message_id)
        if ref:
            s.group_msg = ref

    async def _ping_turn(self, s: Session31) -> None:
        """Tell the player whose turn it is. Group games: a message that TAGS them plus a button that opens the bot
        chat (the previous ping is deleted, so the group never fills up). Without a group (or if the group message
        fails) a DM ping is used instead; practice games need no ping."""
        st = s.game.state
        if s.game.finished or st.phase != "draw":
            return
        seat = st.turn
        uid = st.players[seat]
        if seat in s.ai:
            return
        notify = s.notify.get(uid, True)
        if s.group_chat_id is not None:
            await self.notifier.delete(s.group_chat_id, s.group_ping)
            s.group_ping = None
            who = mention(uid, s.names[seat]) if notify else esc(s.names[seat])
            what = ("✊ <b>final turn</b>" if st.knocker is not None else "it's <b>your turn</b>")
            left = s.seconds_left()
            try:
                m = await self.bot.send_message(
                    s.group_chat_id, f"🎯 {who} — {what} in room <code>{s.room_code}</code>"
                    + (f"  (⏱ {left}s)" if left else "") + "\n👇 Your cards are in the bot chat.",
                    parse_mode=ParseMode.HTML, reply_markup=K.open_cards_kb(), disable_web_page_preview=True)
                s.group_ping = m.message_id
                return
            except TelegramError as e:
                log.info("group turn ping failed (%s) - falling back to DM", e)
        elif s.kind == "practice":
            return
        if notify:
            await self.notifier.delete(uid, s.pings.pop(uid, None))
            mid = await self.notifier.dm(uid, f"🎯 <b>Your turn</b> in room <code>{s.room_code}</code>")
            if mid:
                s.pings[uid] = mid

    # ================================================================ user actions
    async def resend_hand(self, uid: int) -> bool:
        s = self.sessions.get(self.by_user.get(uid, -1))
        if not s:
            return False
        old = s.dm_msgs.pop(uid, None)
        if old:
            await self.notifier.delete(uid, old.message_id)
        await self._publish_hand(s, s.game.seat_of(uid), uid)
        return True

    def score_text(self, uid: int) -> str | None:
        s = self.sessions.get(self.by_user.get(uid, -1))
        if not s:
            return None
        seat = s.game.seat_of(uid)
        hand = s.game.state.hands[seat]
        sc = hand_score(hand, s.cfg) if hand else 0
        return f"Your score: {sc:g}  •  " + ("  ".join(label(c) for c in hand) or "no cards")

    def ask_leave(self, uid: int):
        gid = self.by_user.get(uid)
        return K.confirm_leave_kb(gid) if gid else None

    async def rematch_vote(self, uid: int, old_gid: int) -> str:
        g = await self.repo.t31_get_game(old_gid)
        if not g or g["status"] != "finished" or g["kind"] == "tournament":
            return "Rematch is not available for this match."
        humans = [p["user_id"] for p in g["players"] if p["user_id"]]
        if uid not in humans:
            return "You were not in this match."
        votes = self.rematch_votes.setdefault(old_gid, set())
        votes.add(uid)
        if votes >= set(humans):
            if any(self.lobby.busy_reason(u) for u in humans):
                return "Someone is already in another match — try again shortly."
            self.rematch_votes.pop(old_gid, None)
            players = [PlayerInfo(p["user_id"] or -(p["seat"] + 1), p["name"], p["ai_level"]) for p in g["players"]]
            await self.start_game(players, kind=g["kind"], cfg=ThirtyOneConfig.from_dict(g["config"]),
                                  group_chat_id=g["group_chat_id"])
            return "🔁 Rematch starting!"
        name = next(p["name"] for p in g["players"] if p["user_id"] == uid)
        for other in humans:
            if other != uid:
                await self.notifier.dm(other, f"🔁 <b>{T.esc(name)}</b> wants a rematch! Tap Rematch to accept "
                                              f"({len(votes)}/{len(humans)}).")
        return f"Waiting for the others ({len(votes)}/{len(humans)})."

    async def start_tournament_match(self, tid: int, rnd: int, idx: int, a: int, b: int, label_: str) -> int:
        na, nb = await self.repo.display_name(a), await self.repo.display_name(b)
        for uid in (a, b):
            await self.notifier.dm(uid, f"🏟 <b>{label_}</b> — your 31 match is starting now!")
        cfg = (await self.config()).replace(mode="lives")
        s = await self.start_game([PlayerInfo(a, na), PlayerInfo(b, nb)], kind="tournament", cfg=cfg, tournament_id=tid,
                                  tournament_match=f"{rnd}:{idx}", room_code=f"T{tid}-{rnd + 1}.{idx + 1}")
        return s.game_id


def IMG_headline(s: Session31, info: dict) -> str:
    return T.reveal_headline(info, s.names, s.cfg)
