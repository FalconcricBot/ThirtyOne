"""Pure Thirty-One engine (no Telegram, no DB). Deterministic from (seed, actions) so games can be
persisted, recovered after a restart and replayed."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import build_deck, value
from .rules import DEFAULT_CONFIG, ThirtyOneConfig
from .scoring import hand_score, is_31
from .state import ThirtyOneState


class GameError(Exception): ...
class NotYourTurn(GameError): ...
class WrongPhase(GameError): ...
class CardNotInHand(GameError): ...
class IllegalAction(GameError): ...
class StaleMove(GameError): ...
class GameOver(GameError): ...
class UnknownPlayer(GameError): ...


@dataclass
class ActionResult:
    seat: int
    action: str
    version: int
    card: str | None = None                # public card (taken / discarded)
    drawn: str | None = None               # PRIVATE: card drawn from the deck
    round_ended: bool = False
    round: dict | None = None
    finished: bool = False


@dataclass
class Observation:
    """Everything one seat may know. The AI and the private hand message use only this."""
    seat: int
    n: int
    hand: list[str]
    phase: str
    turn: int
    top_discard: str | None
    discard_pile: list[str]
    draw_count: int
    lives: list[int]
    totals: list[float]
    active: list[bool]
    knocker: int | None
    final_left: list[int]
    known: list[list[str]]
    drawn_card: str | None
    taken_from_discard: str | None
    round_no: int
    cfg: dict


class ThirtyOneGame:
    def __init__(self, state: ThirtyOneState):
        self.state = state
        self.cfg = ThirtyOneConfig.from_dict(state.config)

    # ------------------------------------------------------------ construction / persistence
    @classmethod
    def new(cls, players: list[int], cfg: ThirtyOneConfig | None = None, seed: int | None = None) -> "ThirtyOneGame":
        cfg = cfg or DEFAULT_CONFIG
        n = len(players)
        if not 2 <= n <= 7:
            raise ValueError("Thirty-One supports 2 to 7 players")
        if len(set(players)) != n:
            raise ValueError("Duplicate players")
        seed = random.SystemRandom().randrange(2**62) if seed is None else seed
        st = ThirtyOneState(
            config=cfg.to_dict(), seed=seed, players=list(players), lives=[cfg.lives_at_start] * n,
            totals=[0.0] * n, active=[True] * n, round_no=0,
            first=random.Random(f"{seed}:first").randrange(n), hands=[[] for _ in range(n)], draw_pile=[],
            discard=[], turn=0, phase="between", known=[[] for _ in range(n)],
            pstats=[{"rounds": 0, "times_31": 0, "knock_wins": 0, "knock_losses": 0, "best": 0.0} for _ in range(n)])
        g = cls(st)
        g._start_round()
        return g

    def to_dict(self) -> dict:
        return self.state.to_dict()

    @classmethod
    def from_dict(cls, d: dict) -> "ThirtyOneGame":
        return cls(ThirtyOneState.from_dict(d))

    # ------------------------------------------------------------ queries
    @property
    def n(self) -> int:
        return len(self.state.players)

    @property
    def finished(self) -> bool:
        return self.state.status == "finished"

    @property
    def current_user(self) -> int:
        return self.state.players[self.state.turn]

    def seat_of(self, user_id: int) -> int:
        try:
            return self.state.players.index(user_id)
        except ValueError:
            raise UnknownPlayer(user_id) from None

    def side_of(self, seat: int) -> int:        # no teams: lets the tournament code treat 31 like Briscola
        return seat

    def active_seats(self) -> list[int]:
        return [s for s in range(self.n) if self.state.active[s]]

    def score_of(self, seat: int) -> float:
        return hand_score(self.state.hands[seat], self.cfg) if self.state.hands[seat] else 0.0

    def _next_active(self, seat: int) -> int:
        for i in range(1, self.n + 1):
            s = (seat + i) % self.n
            if self.state.active[s]:
                return s
        return seat

    def observation(self, seat: int) -> Observation:
        st = self.state
        return Observation(seat=seat, n=self.n, hand=list(st.hands[seat]), phase=st.phase, turn=st.turn,
                           top_discard=st.discard[-1] if st.discard else None, discard_pile=list(st.discard),
                           draw_count=len(st.draw_pile), lives=list(st.lives), totals=list(st.totals),
                           active=list(st.active), knocker=st.knocker, final_left=list(st.final_left),
                           known=[list(k) for k in st.known], drawn_card=st.drawn_card,
                           taken_from_discard=st.taken_from_discard, round_no=st.round_no, cfg=dict(st.config))

    def public_view(self) -> dict:
        """Safe for group chats: no hidden hands, no draw-pile order."""
        st = self.state
        return {"players": list(st.players), "lives": list(st.lives), "totals": list(st.totals),
                "active": list(st.active), "turn": st.turn, "phase": st.phase, "round_no": st.round_no,
                "draw_count": len(st.draw_pile), "discard_top": st.discard[-1] if st.discard else None,
                "discard_count": len(st.discard), "knocker": st.knocker, "final_left": list(st.final_left),
                "mode": self.cfg.mode, "version": st.version, "finished": self.finished}

    # ------------------------------------------------------------ rounds
    def _start_round(self) -> None:
        st = self.state
        st.round_no += 1
        rng = random.Random(f"{st.seed}:{st.round_no}")
        deck = build_deck()
        rng.shuffle(deck)
        seats = self.active_seats()
        st.hands = [[] for _ in range(self.n)]
        for _ in range(3):
            for s in seats:
                st.hands[s].append(deck.pop())
        st.discard = [deck.pop()]
        st.draw_pile = deck
        if not st.active[st.first]:
            st.first = self._next_active(st.first)
        st.turn, st.phase = st.first, "draw"
        st.drawn_card = st.taken_from_discard = st.knocker = None
        st.final_left, st.reshuffles = [], 0
        st.known = [[] for _ in range(self.n)]

    def start_next_round(self) -> None:
        """Called by the manager after the reveal pause."""
        st = self.state
        if st.phase != "between":
            raise WrongPhase("round still running")
        st.first = self._next_active(st.first)
        self._start_round()
        st.version += 1

    # ------------------------------------------------------------ actions
    def play(self, user_id: int, action: str, arg: str | None = None,
             expected_version: int | None = None) -> ActionResult:
        if self.finished:
            raise GameOver()
        if expected_version is not None and expected_version != self.state.version:
            raise StaleMove()
        return self.apply(self.seat_of(user_id), action, arg)

    def apply(self, seat: int, action: str, arg: str | None = None) -> ActionResult:
        st = self.state
        if self.finished:
            raise GameOver()
        if st.phase == "between":
            raise WrongPhase("The round is over - the next one starts shortly.")
        if not st.active[seat] or seat != st.turn:
            raise NotYourTurn()
        fn = {"draw": self._draw, "take": self._take, "discard": self._discard,
              "knock": self._knock, "declare": self._declare, "skip": self._skip}.get(action)
        if fn is None:
            raise IllegalAction(f"unknown action {action!r}")
        res = fn(seat, arg)
        st.moves.append([st.round_no if not res.round_ended else res.round["no"], seat, action, res.card or arg])
        st.version += 1
        res.version = st.version
        res.finished = self.finished
        return res

    def _need_phase(self, phase: str) -> None:
        if self.state.phase != phase:
            raise WrongPhase(f"You must {'discard a card' if self.state.phase == 'discard' else 'draw, take or knock first'}.")

    def _draw(self, seat: int, _arg) -> ActionResult:
        st = self.state
        self._need_phase("draw")
        if not st.draw_pile:                        # reshuffle everything under the top discard
            if len(st.discard) < 2:
                raise IllegalAction("The deck is empty - take the discard instead.")
            top, rest = st.discard[-1], st.discard[:-1]
            random.Random(f"{st.seed}:{st.round_no}:r{st.reshuffles}").shuffle(rest)
            st.draw_pile, st.discard, st.reshuffles = rest, [top], st.reshuffles + 1
        card = st.draw_pile.pop()
        st.hands[seat].append(card)
        st.drawn_card, st.taken_from_discard, st.phase = card, None, "discard"
        return ActionResult(seat, "draw", st.version, drawn=card)

    def _take(self, seat: int, _arg) -> ActionResult:
        st = self.state
        self._need_phase("draw")
        if not st.discard:
            raise IllegalAction("The discard pile is empty.")
        card = st.discard.pop()
        st.hands[seat].append(card)
        st.known[seat].append(card)
        st.drawn_card = st.taken_from_discard = card
        st.phase = "discard"
        return ActionResult(seat, "take", st.version, card=card)

    def _discard(self, seat: int, code: str | None) -> ActionResult:
        st = self.state
        self._need_phase("discard")
        if code not in st.hands[seat]:
            raise CardNotInHand(code)
        if code == st.taken_from_discard:
            raise IllegalAction("You can't throw back the card you just took.")
        st.hands[seat].remove(code)
        st.discard.append(code)
        if code in st.known[seat]:
            st.known[seat].remove(code)
        st.drawn_card = st.taken_from_discard = None
        res = ActionResult(seat, "discard", st.version, card=code)
        if self.cfg.auto_declare_31 and is_31(st.hands[seat]):
            return self._end_round(res, "declare31", seat)
        if st.knocker is not None:
            if seat in st.final_left:
                st.final_left.remove(seat)
            if not st.final_left:
                return self._end_round(res, "knock", st.knocker)
            st.turn = st.final_left[0]
        else:
            st.turn = self._next_active(seat)
        st.phase = "draw"
        return res

    def _knock(self, seat: int, _arg) -> ActionResult:
        st = self.state
        if not self.cfg.knock_enabled:
            raise IllegalAction("Knocking is disabled in this game.")
        self._need_phase("draw")
        if st.knocker is not None:
            raise IllegalAction("Someone already knocked - this is your final turn.")
        st.knocker = seat
        st.final_left = []
        s = seat
        for _ in range(self.n - 1):
            s = self._next_active(s)
            if s != seat:
                st.final_left.append(s)
        st.turn, st.phase = st.final_left[0], "draw"
        return ActionResult(seat, "knock", st.version)

    def _declare(self, seat: int, _arg) -> ActionResult:
        self._need_phase("draw")
        if not is_31(self.state.hands[seat]):
            raise IllegalAction("You need exactly 31 points (three cards of one suit) to declare 31.")
        return self._end_round(ActionResult(seat, "declare", self.state.version), "declare31", seat)

    def _skip(self, seat: int, _arg) -> ActionResult:
        """The player did not move in time (only the manager's timer calls this, never a button). A card picked up
        this turn goes back where it came from, so nothing changes in the hand; the turn simply passes on."""
        st = self.state
        if st.phase == "discard" and st.drawn_card:
            card = st.drawn_card
            st.hands[seat].remove(card)
            if card == st.taken_from_discard:
                st.discard.append(card)
                if card in st.known[seat]:
                    st.known[seat].remove(card)
            else:
                st.draw_pile.append(card)
            st.drawn_card = st.taken_from_discard = None
        res = ActionResult(seat, "skip", st.version)
        if st.knocker is not None:                 # a skipped final turn still counts as that player's last turn
            if seat in st.final_left:
                st.final_left.remove(seat)
            if not st.final_left:
                return self._end_round(res, "knock", st.knocker)
            st.turn = st.final_left[0]
        else:
            st.turn = self._next_active(seat)
        st.phase = "draw"
        return res

    # ------------------------------------------------------------ scoring a round
    def _lowest(self, scores: dict[int, float], act: list[int]) -> list[int]:
        low = min(scores.values())
        lows = [s for s in act if scores[s] == low]
        if len(lows) == len(act):                   # everybody tied: nobody loses
            return []
        if len(lows) == 1:
            return lows
        rule = self.cfg.tie_rule
        if rule == "none_lose":
            return []
        if rule == "high_card":
            key = {s: sorted((value(c) for c in self.state.hands[s]), reverse=True) for s in lows}
            worst = min(key.values())
            return [s for s in lows if key[s] == worst]
        return lows

    def _end_round(self, res: ActionResult, reason: str, trigger: int) -> ActionResult:
        st, cfg = self.state, self.cfg
        act = self.active_seats()
        scores = {s: hand_score(st.hands[s], cfg) for s in act}
        if reason == "declare31" and cfg.instant_31_rule == "all_others_lose":
            losers = [s for s in act if not is_31(st.hands[s])]
        else:
            losers = self._lowest(scores, act)
        knocker = st.knocker
        note = ""
        loss = {s: 0 for s in act}
        eliminated: list[int] = []
        void = False
        if cfg.mode != "points":
            loss = {s: (1 if s in losers else 0) for s in act}
            if knocker is not None and knocker in losers:
                loss[knocker] += cfg.knock_penalty_extra
            if loss and all(st.lives[s] - loss[s] <= 0 for s in act):
                void, loss, note = True, {s: 0 for s in act}, "Everyone would have been eliminated - no lives lost."
            for s in act:
                st.lives[s] -= loss[s]
            eliminated = sorted((s for s in act if st.lives[s] <= 0), key=lambda s: scores[s])
            for s in eliminated:
                st.active[s] = False
                st.elim_order.append(s)
        else:
            for s in act:
                st.totals[s] += scores[s]
        for s in act:                               # statistics
            ps = st.pstats[s]
            ps["rounds"] += 1
            ps["times_31"] += 1 if is_31(st.hands[s]) else 0
            ps["best"] = max(ps["best"], scores[s])
        if knocker is not None:
            st.pstats[knocker]["knock_losses" if knocker in losers else "knock_wins"] += 1
        n = self.n
        info = {"no": st.round_no, "reason": reason, "trigger": trigger, "knocker": knocker,
                "scores": [scores.get(s) for s in range(n)], "hands": [list(st.hands[s]) if s in scores else [] for s in range(n)],
                "losers": losers, "life_loss": [loss.get(s, 0) for s in range(n)], "eliminated": eliminated,
                "void": void, "note": note, "lives": list(st.lives), "totals": list(st.totals)}
        st.last_round = info
        st.knocker, st.final_left = None, []
        res.round_ended, res.round = True, info
        remaining = self.active_seats()
        if cfg.mode != "points" and len(remaining) <= 1:
            self._finish(remaining)
        elif cfg.mode == "points" and st.round_no >= cfg.points_rounds:
            best = max(st.totals[s] for s in remaining)
            self._finish([s for s in remaining if st.totals[s] == best])
        else:
            st.phase = "between"
        return res

    def _finish(self, winners: list[int]) -> None:
        st = self.state
        st.winner_seats, st.status, st.phase = sorted(winners), "finished", "finished"

    # ------------------------------------------------------------ leaving
    def eliminate(self, seat: int) -> None:
        """A player quits or is removed for inactivity. Their cards go to the bottom of the deck."""
        st = self.state
        if self.finished:
            raise GameOver()
        if not st.active[seat]:
            return
        st.active[seat] = False
        if self.cfg.mode != "points":
            st.lives[seat] = 0
        st.forfeit_seats.append(seat)
        st.elim_order.append(seat)
        st.draw_pile[0:0] = st.hands[seat]
        st.hands[seat], st.known[seat] = [], []
        st.version += 1
        remaining = self.active_seats()
        if len(remaining) < 2:
            return self._finish(remaining)
        was_turn = st.turn == seat and st.phase in ("draw", "discard")
        if st.knocker == seat:                      # the knocker left: the knock is void
            st.knocker, st.final_left = None, []
        elif seat in st.final_left:
            st.final_left.remove(seat)
        if was_turn:
            st.drawn_card = st.taken_from_discard = None
            st.phase = "draw"
            if st.knocker is not None:
                if st.final_left:
                    st.turn = st.final_left[0]
                else:
                    self._end_round(ActionResult(seat, "forfeit", st.version), "knock", st.knocker)
            else:
                st.turn = self._next_active(seat)
        elif st.knocker is not None and not st.final_left and st.phase != "between":
            self._end_round(ActionResult(seat, "forfeit", st.version), "knock", st.knocker)

    # ------------------------------------------------------------ results
    def placements(self) -> list[int]:
        """1 = best. Lives modes: survivor first, then reverse elimination order. Points: by total."""
        st = self.state
        n = self.n
        if self.cfg.mode == "points":
            ranked = sorted((s for s in range(n) if s not in st.forfeit_seats), key=lambda s: -st.totals[s])
            out = [n] * n
            rank, prev, pos = 0, None, 0
            for s in ranked:
                pos += 1
                if st.totals[s] != prev:
                    rank, prev = pos, st.totals[s]
                out[s] = rank
            return out
        out = [0] * n
        for s in st.winner_seats:
            out[s] = 1
        nxt = len(st.winner_seats) + 1
        for s in reversed(st.elim_order):
            if out[s] == 0:
                out[s] = nxt
                nxt += 1
        return [p or n for p in out]

    def result(self) -> dict:
        """Compatible with the Briscola result dict, so tournaments can reuse it unchanged."""
        st = self.state
        scores = list(st.totals) if self.cfg.mode == "points" else list(st.lives)
        return {"scores": scores, "draw": len(st.winner_seats) != 1, "winner_sides": list(st.winner_seats),
                "decisive": True, "forfeit": bool(st.forfeit_seats), "placements": self.placements()}
