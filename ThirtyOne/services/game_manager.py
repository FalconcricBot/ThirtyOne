"""Runs live matches: moves, timers, AI turns, message publishing, persistence and recovery.

Concurrency model: one asyncio.Lock per game; handlers run concurrently (PTB concurrent_updates).
Every accepted move is written to the DB immediately, so a restart loses nothing."""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

from telegram import InputMediaPhoto
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TelegramError, TimedOut

from config import settings
from game.ai import choose_card
from game.engine import (BriscolaGame, CardNotInHand, GameOver, NotYourTurn, StaleMove, UnknownPlayer)
from game.rules import RulesConfig
from keyboards.game_keyboard import (confirm_leave_kb, hand_kb, open_cards_kb, replay_kb, result_kb, spectator_kb,
                                     table_kb)
from services.statistics import record_game
from ui import images, texts
from utils.helpers import esc, mention

log = logging.getLogger(__name__)
RULES = RulesConfig(trump_mode=settings.trump_mode)


@dataclass
class PlayerInfo:
    user_id: int                  # Telegram id for humans, negative for AI
    name: str
    ai_level: str | None = None


@dataclass
class MsgRef:
    message_id: int
    kind: str                     # 'photo' | 'text'


@dataclass
class Session:
    game_id: int
    game: BriscolaGame
    names: list[str]
    ai: dict[int, str]                                  # seat -> difficulty
    kind: str
    room_code: str
    group_chat_id: int | None = None
    tournament_id: int | None = None
    tournament_match: str | None = None
    group_msg: MsgRef | None = None
    dm_msgs: dict[int, MsgRef] = field(default_factory=dict)
    pings: dict[int, int] = field(default_factory=dict)
    group_ping: int | None = None                    # the 'it's your turn @name' message in the group
    spectators: dict[int, MsgRef | None] = field(default_factory=dict)
    hand_img: dict[int, bool] = field(default_factory=dict)
    table_img: bool = True
    notify: dict[int, bool] = field(default_factory=dict)
    strikes: dict[int, int] = field(default_factory=dict)
    last_trick: dict | None = None
    deadline: float | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    ai_running: bool = False
    last_group_edit: float = 0.0
    started: float = field(default_factory=time.time)

    @property
    def humans(self) -> dict[int, int]:               # seat -> user id
        return {i: u for i, u in enumerate(self.game.state.seats) if i not in self.ai}

    def seconds_left(self) -> int | None:
        return max(0, int(self.deadline - time.time())) if self.deadline else None


class GameManager:
    def __init__(self, application, repo, lobby, rewards, notifier):
        self.app, self.bot = application, application.bot
        self.repo, self.lobby, self.rewards, self.notifier = repo, lobby, rewards, notifier
        self.tournaments = None                         # injected in main.py
        self.sessions: dict[int, Session] = {}
        self.by_user: dict[int, int] = {}
        self.watching: dict[int, int] = {}              # spectator uid -> game id
        self.rematch_votes: dict[int, set[int]] = {}
        self._tasks: set[asyncio.Task] = set()

    # ================================================================ lifecycle
    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def start_game(self, players: list[PlayerInfo], *, kind: str, group_chat_id: int | None = None,
                         room_code: str | None = None, tournament_id: int | None = None,
                         tournament_match: str | None = None) -> Session:
        seats = [p.user_id for p in players]
        game = BriscolaGame.new(seats, RULES)
        code = room_code or f"BA-{random.randint(10000, 99999)}"
        gid = await self.repo.create_game(
            mode=len(players), kind=kind, seed=game.state.seed, state=game.to_dict(), room_code=code,
            group_chat_id=group_chat_id, tournament_id=tournament_id, tournament_match=tournament_match,
            players=[{"seat": i, "user_id": None if p.ai_level else p.user_id, "name": p.name,
                      "ai_level": p.ai_level} for i, p in enumerate(players)])
        s = Session(game_id=gid, game=game, names=[p.name for p in players],
                    ai={i: p.ai_level for i, p in enumerate(players) if p.ai_level}, kind=kind, room_code=code,
                    group_chat_id=group_chat_id, tournament_id=tournament_id, tournament_match=tournament_match)
        await self._register(s)
        if game.state.turn not in s.ai:
            s.deadline = time.time() + settings.turn_timeout
        await self.publish(s)
        await self._ping_turn(s)
        self._after_state_change(s)
        return s

    async def _register(self, s: Session) -> None:
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
        """Reload unfinished matches after a restart and resend everyone's hand."""
        n = 0
        for g in await self.repo.load_active_games():
            try:
                game = BriscolaGame.from_dict(g["state"], RULES)
                ps = g["players"]
                s = Session(game_id=g["id"], game=game, names=[p["name"] for p in ps],
                            ai={p["seat"]: p["ai_level"] for p in ps if p["ai_level"]}, kind=g["kind"],
                            room_code=g["room_code"] or "BA-?????", group_chat_id=g["group_chat_id"],
                            tournament_id=g["tournament_id"], tournament_match=g["tournament_match"])
                await self._register(s)
                await self.publish(s, note="♻️ The bot restarted — your match continues!")
                self._after_state_change(s)
                n += 1
            except Exception:
                log.exception("could not restore game %s", g.get("id"))
        return n

    # ================================================================ moves
    async def handle_move(self, uid: int, gid: int, version: int, code: str) -> str | None:
        """Returns a short alert for the user, or None when the move was accepted."""
        s = self.sessions.get(gid)
        if s is None:
            return "This match has ended or expired."
        async with s.lock:
            try:
                seat = s.game.seat_of(uid)
                if s.game.finished:
                    return "This match is over."
                if version != s.game.state.version:
                    self._spawn(self._publish_hand(s, seat, uid))
                    return "↻ That button was outdated — your hand was refreshed."
                s.strikes[seat] = 0
                await self._apply(s, seat, code)
            except NotYourTurn:
                return "⏳ Not your turn yet."
            except CardNotInHand:
                return "That card is not in your hand."
            except UnknownPlayer:
                return "You are not a player in this match."
            except StaleMove:
                return "↻ Outdated button."
            except GameOver:
                return "This match is over."
        self._after_state_change(s)
        return None

    async def _apply(self, s: Session, seat: int, code: str, note: str | None = None) -> None:
        """Apply + persist + publish one move. Caller holds s.lock."""
        g = s.game
        plays_before = [list(p) for p in g.state.trick]
        res = g.apply_move(seat, code)
        await self.repo.record_move(s.game_id, res.version, seat, code, g.to_dict())
        if res.trick_complete:
            s.last_trick = {"plays": plays_before + [[seat, code]], "winner": res.trick_winner,
                            "points": res.trick_points}
        if res.finished:
            await self._finalize(s)
        else:
            s.deadline = time.time() + settings.turn_timeout if g.state.turn not in s.ai else None
            await self.publish(s, note=note)
            await self._ping_turn(s)

    def _after_state_change(self, s: Session) -> None:
        if s.game.finished:
            return
        self._arm_timers(s)
        self._kick_ai(s)

    # ================================================================ AI
    def _kick_ai(self, s: Session) -> None:
        if s.ai_running or s.game.finished or s.game.state.turn not in s.ai:
            return
        s.ai_running = True
        self._spawn(self._ai_loop(s))

    async def _ai_loop(self, s: Session) -> None:
        try:
            while True:
                async with s.lock:
                    if s.game.finished or s.game.state.turn not in s.ai:
                        s.ai_running = False
                        self._arm_timers(s)          # next up is a human: start their clock
                        return
                    seat, ver = s.game.state.turn, s.game.state.version
                    obs, level = s.game.observation(seat), s.ai[seat]
                await asyncio.sleep(random.uniform(1.0, 1.8))
                code = await asyncio.to_thread(choose_card, obs, level, RULES)
                async with s.lock:
                    if s.game.finished or s.game.state.version != ver:
                        continue
                    await self._apply(s, seat, code)
        except Exception:
            log.exception("AI loop crashed for game %s", s.game_id)
            s.ai_running = False
        finally:
            if s.game.finished:
                s.ai_running = False

    # ================================================================ timers / AFK
    def _arm_timers(self, s: Session) -> None:
        jq = self.app.job_queue
        for name in (f"turn:{s.game_id}", f"warn:{s.game_id}"):
            for j in jq.get_jobs_by_name(name):
                j.schedule_removal()
        if s.game.finished or s.game.state.turn in s.ai:
            return
        t = settings.turn_timeout
        data = (s.game_id, s.game.state.version)
        if s.deadline is None:
            s.deadline = time.time() + t
        jq.run_once(self._timeout_job, max(1, s.deadline - time.time()), data=data, name=f"turn:{s.game_id}")
        if t > 25:
            jq.run_once(self._warn_job, max(1, s.deadline - time.time() - 15), data=data, name=f"warn:{s.game_id}")

    async def _warn_job(self, context) -> None:
        gid, ver = context.job.data
        s = self.sessions.get(gid)
        if s and not s.game.finished and s.game.state.version == ver:
            uid = s.game.current_user
            await self.notifier.dm(uid, "⏰ <b>15 seconds left</b> to play your card!", silent=False)

    async def _timeout_job(self, context) -> None:
        gid, ver = context.job.data
        s = self.sessions.get(gid)
        if s is None:
            return
        try:
            async with s.lock:
                if s.game.finished or s.game.state.version != ver:
                    return
                seat = s.game.state.turn
                uid = s.game.state.seats[seat]
                s.strikes[seat] = s.strikes.get(seat, 0) + 1
                if settings.timeout_policy == "forfeit" or s.strikes[seat] >= settings.afk_strikes_limit:
                    await self._forfeit_locked(s, seat, "AFK")
                    return
                code = choose_card(s.game.observation(seat), "medium", RULES)
                await self.notifier.dm(uid, f"⏰ Time's up — auto-played <b>{texts._c(code)}</b>. "
                                            f"Strike {s.strikes[seat]}/{settings.afk_strikes_limit}.")
                await self._apply(s, seat, code, note=f"⏰ {s.names[seat]} timed out — card auto-played.")
            self._after_state_change(s)
        except Exception:
            log.exception("timeout handler failed for game %s", gid)

    # ================================================================ finishing
    async def forfeit(self, uid: int) -> bool:
        gid = self.by_user.get(uid)
        s = self.sessions.get(gid) if gid else None
        if not s:
            return False
        async with s.lock:
            if s.game.finished:
                return False
            await self._forfeit_locked(s, s.game.seat_of(uid), "left")
        return True

    async def _forfeit_locked(self, s: Session, seat: int, reason: str) -> None:
        s.game.forfeit(seat)
        await self._finalize(s, forfeit_seat=seat)

    async def _finalize(self, s: Session, forfeit_seat: int | None = None) -> None:
        g = s.game
        res = g.result()
        await self.repo.finish_game(s.game_id, g.to_dict(), res["winner_sides"], res["scores"], g.state.captured)
        for name in (f"turn:{s.game_id}", f"warn:{s.game_id}"):
            for j in self.app.job_queue.get_jobs_by_name(name):
                j.schedule_removal()
        humans = s.humans
        summaries: dict[int, dict] = {}
        try:
            summaries = await record_game(self.repo, self.rewards, game_id=s.game_id, game=g, kind=s.kind,
                                          humans=humans, names=s.names)
        except Exception:
            log.exception("recording results failed for game %s", s.game_id)
        for uid in humans.values():
            self.by_user.pop(uid, None)
            self.lobby.set_playing([uid], False)
            await self.notifier.delete(uid, s.pings.pop(uid, None))
        if s.group_chat_id is not None:
            await self.notifier.delete(s.group_chat_id, s.group_ping)
            s.group_ping = None
        self.sessions.pop(s.game_id, None)
        s.deadline = None
        await self.publish(s, final=(res, summaries, forfeit_seat))
        for uid in list(s.spectators):
            self.watching.pop(uid, None)
        if s.tournament_id is not None and self.tournaments:
            self._spawn(self.tournaments.on_game_finished(s.tournament_id, s.tournament_match, g, humans))

    async def _abort(self, s: Session, text: str) -> None:
        self.sessions.pop(s.game_id, None)
        for name in (f"turn:{s.game_id}", f"warn:{s.game_id}"):
            for j in self.app.job_queue.get_jobs_by_name(name):
                j.schedule_removal()
        await self.repo.cancel_game(s.game_id)
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
        """Graceful shutdown: state is already persisted after every move."""
        for t in list(self._tasks):
            t.cancel()

    # ================================================================ publishing
    async def publish(self, s: Session, *, note: str | None = None, final=None) -> None:
        jobs = [self._publish_hand(s, seat, uid, note, final) for seat, uid in s.humans.items()]
        if s.group_chat_id is not None:
            jobs.append(self._publish_group(s, final))
        jobs += [self._publish_spectator(s, uid, final) for uid in list(s.spectators)]
        for r in await asyncio.gather(*jobs, return_exceptions=True):
            if isinstance(r, Exception):
                log.error("publish failed: %r", r)

    def _view(self, s: Session) -> dict:
        v = s.game.public_view()
        return v

    def _winner_text(self, s: Session, res: dict) -> str:
        if res["draw"]:
            return "It's a draw!"
        ws = res["winner_sides"][0]
        if s.game.n == 4:
            return f"{s.names[ws]} & {s.names[ws + 2]} win!"
        return f"{s.names[ws]} wins!"

    async def _publish_hand(self, s: Session, seat: int, uid: int, note: str | None = None, final=None) -> None:
        g, view = s.game, self._view(s)
        show_table = s.group_chat_id is None
        if final:
            res, summaries, forfeit_seat = final
            text = texts.result_text(names=s.names, game_result=res, seat=seat, team_mode=g.n == 4,
                                     summary=summaries.get(uid),
                                     forfeit_name=s.names[forfeit_seat] if forfeit_seat is not None else None)
            kb = result_kb(s.game_id, rematch=s.kind not in ("tournament",))
            photo = await self._table_photo(s, res=res) if s.hand_img.get(uid, True) else None
        else:
            hand = list(g.state.hands[seat])
            text = texts.hand_text(room=s.room_code, names=s.names, seat=seat, view=view, hand=hand,
                                   last_trick=s.last_trick, deadline=s.seconds_left(), show_table=show_table)
            if note:
                text = f"<i>{texts.esc(note)}</i>\n" + text
            kb = hand_kb(s.game_id, g.state.version, hand)
            photo = None
            if s.hand_img.get(uid, True):
                photo = await asyncio.to_thread(
                    images.render_hand, hand, g.state.trump_suit, g.state.trump_card if view["stock_count"] else None,
                    view["stock_count"], view["scores"][g.side_of(seat)], g.state.turn == seat)
        ref = await self._upsert(uid, s.dm_msgs.get(uid), text, photo, kb, s, uid)
        if ref:
            s.dm_msgs[uid] = ref

    async def _table_photo(self, s: Session, res: dict | None = None):
        view = self._view(s)
        g = s.game
        trump_card = g.state.trump_card if view["stock_count"] > 0 else None
        return await asyncio.to_thread(
            images.render_table, room=s.room_code, mode_label="2 VS 2" if g.n == 4 else "1 VS 1", names=s.names,
            trick=[tuple(p) for p in view["trick"]], turn=None if res else view["turn"],
            trump_suit=g.state.trump_suit, trump_card=trump_card,
            stock=view["stock_count"], side_scores=view["scores"], team_mode=g.n == 4,
            last_trick={"plays": [tuple(p) for p in s.last_trick["plays"]], "winner": s.last_trick["winner"],
                        "points": s.last_trick["points"]} if s.last_trick else None,
            winner_text=self._winner_text(s, res) if res else None,
            deadline_text=f"{s.seconds_left()}s left" if s.seconds_left() else None)

    async def _publish_group(self, s: Session, final=None) -> None:
        wait = 1.3 - (time.time() - s.last_group_edit)
        if wait > 0 and not final:
            await asyncio.sleep(wait)
        s.last_group_edit = time.time()
        res = final[0] if final else None
        view = self._view(s)
        text = texts.table_text(room=s.room_code, names=s.names, view=view, last_trick=s.last_trick,
                                deadline=s.seconds_left(), winner=self._winner_text(s, res) if res else None)
        photo = None
        if s.table_img:
            photo = await self._table_photo(s, res)
            text = _short_caption(text)
        ref = await self._upsert(s.group_chat_id, s.group_msg, text, photo, None if final else table_kb(s.game_id), s, None)
        if ref and (s.group_msg is None or s.group_msg.message_id != ref.message_id):
            await self.repo.set_group_message(s.game_id, s.group_chat_id, ref.message_id)
        if ref:
            s.group_msg = ref

    async def _publish_spectator(self, s: Session, uid: int, final=None) -> None:
        res = final[0] if final else None
        view = self._view(s)
        text = texts.table_text(room=s.room_code, names=s.names, view=view, last_trick=s.last_trick,
                                deadline=s.seconds_left(), winner=self._winner_text(s, res) if res else None)
        photo = await self._table_photo(s, res)
        ref = await self._upsert(uid, s.spectators.get(uid), _short_caption(text), photo,
                                 None if final else spectator_kb(), s, None)
        if ref:
            s.spectators[uid] = ref

    async def _upsert(self, chat_id: int, ref: MsgRef | None, text: str, photo, kb, s: Session,
                      player_uid: int | None) -> MsgRef | None:
        """Edit the existing message in place; resend if it vanished or changed type."""
        kind = "photo" if photo is not None else "text"
        data = photo.getvalue() if photo is not None else None
        for attempt in range(2):
            try:
                if ref and ref.kind == kind:
                    if kind == "photo":
                        await self.bot.edit_message_media(
                            chat_id=chat_id, message_id=ref.message_id, reply_markup=kb,
                            media=InputMediaPhoto(data, caption=text, parse_mode=ParseMode.HTML))
                    else:
                        await self.bot.edit_message_text(text, chat_id=chat_id, message_id=ref.message_id,
                                                         parse_mode=ParseMode.HTML, reply_markup=kb)
                    return ref
                if ref:
                    await self.notifier.delete(chat_id, ref.message_id)
                return await self._send_new(chat_id, kind, text, data, kb)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 0.5)
            except BadRequest as e:
                if "not modified" in str(e).lower():
                    return ref
                log.info("edit failed (%s) - resending", e)
                ref = None                                   # message gone / not editable: send a new one
            except Forbidden:
                log.info("user %s blocked the bot or left the chat", chat_id)
                if player_uid is not None:
                    s.dm_msgs.pop(player_uid, None)
                return None
            except (TimedOut, NetworkError) as e:
                log.warning("network problem while publishing: %s", e)
                return ref
            except TelegramError as e:
                log.error("telegram error while publishing: %s", e)
                return ref
        return ref

    async def _send_new(self, chat_id: int, kind: str, text: str, data, kb) -> MsgRef:
        if kind == "photo":
            m = await self.bot.send_photo(chat_id, data, caption=text, parse_mode=ParseMode.HTML, reply_markup=kb)
        else:
            m = await self.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=kb,
                                            disable_web_page_preview=True)
        return MsgRef(m.message_id, kind)

    async def _ping_turn(self, s: Session) -> None:
        """Group games: a message that TAGS the player whose turn it is, with a button that opens the bot chat
        (the previous ping is deleted). DM ping only as a fallback if the group message cannot be sent."""
        if s.group_chat_id is None or s.game.finished:
            return
        seat = s.game.state.turn
        uid = s.game.state.seats[seat]
        if seat in s.ai:
            return
        notify = s.notify.get(uid, True)
        await self.notifier.delete(s.group_chat_id, s.group_ping)
        s.group_ping = None
        who = mention(uid, s.names[seat]) if notify else esc(s.names[seat])
        left = s.seconds_left()
        try:
            m = await self.bot.send_message(
                s.group_chat_id, f"🎯 {who} — it's <b>your turn</b> in room <code>{s.room_code}</code>"
                + (f"  (⏱ {left}s)" if left else "") + "\n👇 Your cards are in the bot chat.",
                parse_mode=ParseMode.HTML, reply_markup=open_cards_kb(), disable_web_page_preview=True)
            s.group_ping = m.message_id
            return
        except TelegramError as e:
            log.info("group turn ping failed (%s) - falling back to DM", e)
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
        seat = s.game.seat_of(uid)
        old = s.dm_msgs.pop(uid, None)
        if old:
            await self.notifier.delete(uid, old.message_id)
        await self._publish_hand(s, seat, uid)
        return True

    def score_text(self, uid: int) -> str | None:
        s = self.sessions.get(self.by_user.get(uid, -1))
        if not s:
            return None
        sc = s.game.side_scores()
        if s.game.n == 4:
            return f"🏆 Team A {sc[0]} – Team B {sc[1]} • 📦 deck {len(s.game.state.stock)}"
        return " – ".join(f"{s.names[i]} {sc[i]}" for i in range(2)) + f" • 📦 deck {len(s.game.state.stock)}"

    def ask_leave(self, uid: int):
        gid = self.by_user.get(uid)
        return confirm_leave_kb(gid) if gid else None

    def public_games(self) -> list[tuple[int, str]]:
        return [(s.game_id, f"#{s.game_id} • " + " vs ".join(n.split()[0][:10] for n in s.names))
                for s in self.sessions.values() if s.kind != "practice"][:12]

    async def spectate(self, uid: int, gid: int) -> str | None:
        s = self.sessions.get(gid)
        if not s or s.kind == "practice":
            return "That match is not available."
        if uid in s.humans.values():
            return "You are playing in this match."
        if self.lobby.busy_reason(uid) and uid not in self.watching:
            return self.lobby.busy_reason(uid)
        self.stop_watching(uid)
        s.spectators[uid] = None
        self.watching[uid] = gid
        await self._publish_spectator(s, uid)
        return None

    def stop_watching(self, uid: int) -> bool:
        gid = self.watching.pop(uid, None)
        s = self.sessions.get(gid) if gid else None
        if s:
            s.spectators.pop(uid, None)
        return gid is not None

    async def rematch_vote(self, uid: int, old_gid: int) -> str:
        g = await self.repo.get_game(old_gid)
        if not g or g["status"] != "finished" or g["kind"] == "tournament":
            return "Rematch is not available for this match."
        humans = [p["user_id"] for p in g["players"] if p["user_id"]]
        if uid not in humans:
            return "You were not in this match."
        votes = self.rematch_votes.setdefault(old_gid, set())
        votes.add(uid)
        if votes >= set(humans):
            busy = [u for u in humans if self.lobby.busy_reason(u)]
            if busy:
                return "Someone is already in another match — try again shortly."
            self.rematch_votes.pop(old_gid, None)
            players = [PlayerInfo(p["user_id"] or -(p["seat"] + 1), p["name"], p["ai_level"]) for p in g["players"]]
            await self.start_game(players, kind=g["kind"], group_chat_id=g["group_chat_id"])
            return "🔁 Rematch starting!"
        name = next(p["name"] for p in g["players"] if p["user_id"] == uid)
        for other in humans:
            if other != uid:
                await self.notifier.dm(other, f"🔁 <b>{texts.esc(name)}</b> wants a rematch! Tap Rematch to accept "
                                              f"({len(votes)}/{len(humans)}).")
        return f"Waiting for the others ({len(votes)}/{len(humans)})."

    async def start_tournament_match(self, tid: int, rnd: int, idx: int, a: int, b: int, label: str) -> int:
        na, nb = await self.repo.display_name(a), await self.repo.display_name(b)
        for uid in (a, b):
            await self.notifier.dm(uid, f"🏟 <b>{label}</b> — your match is starting now!")
        s = await self.start_game([PlayerInfo(a, na), PlayerInfo(b, nb)], kind="tournament", tournament_id=tid,
                                  tournament_match=f"{rnd}:{idx}", room_code=f"T{tid}-{rnd + 1}.{idx + 1}")
        return s.game_id

    async def tick(self) -> None:
        """Safety net run every 30 s: un-stall AI turns and re-arm lost timers."""
        for s in list(self.sessions.values()):
            if s.game.finished:
                continue
            if s.game.state.turn in s.ai:
                self._kick_ai(s)
            elif not self.app.job_queue.get_jobs_by_name(f"turn:{s.game_id}"):
                s.deadline = None
                self._arm_timers(s)

    # ================================================================ replay
    async def replay_page(self, gid: int, idx: int):
        g = await self.repo.get_game(gid)
        if not g or g["status"] != "finished":
            return None
        seats = [p["user_id"] if p["user_id"] else -(p["seat"] + 1) for p in g["players"]]
        names = [p["name"] for p in g["players"]]
        n = len(seats)
        tricks = [g["moves"][i:i + n] for i in range(0, len(g["moves"]) - len(g["moves"]) % n, n)]
        if not tricks:
            return "No moves were played.", replay_kb(gid, 0, 1)
        idx = max(0, min(idx, len(tricks) - 1))
        # re-simulate up to the requested trick to know the winner and running score
        sim = BriscolaGame.new(seats, RULES, g["seed"])
        winner = pts = None
        for t_i, trick in enumerate(tricks[: idx + 1]):
            for seat, code in trick:
                r = sim.apply_move(seat, code)
            winner, pts = r.trick_winner, r.trick_points
        sc = sim.side_scores()
        plays = "\n".join(f"{names[s]}: <b>{texts._c(c)}</b>" for s, c in tricks[idx])
        text = (f"📜 <b>REPLAY #{gid}</b> • trick {idx + 1}/{len(tricks)}\n"
                f"🃏 Briscola: {texts.SUIT_LABELS[sim.state.trump_suit]}\n{texts.DIV}\n{plays}\n{texts.DIV}\n"
                f"🏅 Winner: <b>{texts.esc(names[winner])}</b> (+{pts})\n"
                f"Score: {' – '.join(map(str, sc))}")
        return text, replay_kb(gid, idx, len(tricks))


def _short_caption(text: str, limit: int = 1000) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"

