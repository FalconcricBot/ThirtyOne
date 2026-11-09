"""Pure Briscola engine. No Telegram, no DB - fully testable on its own."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .cards import ALL_CARDS, Suit, card
from .deck import shuffled_deck
from .rules import DEFAULT_RULES, RulesConfig, trick_winner
from .scoring import outcome, pile_points
from .state import GameState


class GameError(Exception):
    """Base class for all rule violations."""


class NotYourTurn(GameError): ...
class CardNotInHand(GameError): ...
class StaleMove(GameError): ...
class GameOver(GameError): ...
class UnknownPlayer(GameError): ...


@dataclass
class MoveResult:
    seat: int
    card: str
    version: int
    trick_complete: bool = False
    trick_winner: int | None = None
    trick_points: int = 0
    drawn: dict[int, str] = field(default_factory=dict)   # PRIVATE: seat -> drawn card
    finished: bool = False


@dataclass
class Observation:
    """Everything one seat is allowed to know. Used by the AI and the private hand view."""
    seat: int
    n: int
    hand: list[str]
    trump_suit: str
    trump_card: str | None
    trick: list[list]
    captured: list[list[str]]
    hand_sizes: list[int]
    stock_count: int
    leader: int


class BriscolaGame:
    def __init__(self, state: GameState, rules: RulesConfig = DEFAULT_RULES):
        self.state = state
        self.rules = rules

    # ---------- construction / persistence ----------
    @classmethod
    def new(cls, seats: list[int], rules: RulesConfig = DEFAULT_RULES,
            seed: int | None = None) -> "BriscolaGame":
        n = len(seats)
        if n not in (2, 4):
            raise ValueError("Briscola supports 2 or 4 players")
        if len(set(seats)) != n:
            raise ValueError("Duplicate players")
        seed = random.SystemRandom().randrange(2**63) if seed is None else seed
        rng = random.Random(seed)
        stock = shuffled_deck(rng)
        hands: list[list[str]] = [[] for _ in range(n)]
        for _ in range(rules.hand_size):
            for s in range(n):
                hands[s].append(stock.pop())
        if rules.trump_mode == "bottom_card":
            trump_card = stock[0]
            trump_suit = card(trump_card).suit.value
        else:
            trump_card = None
            trump_suit = rng.choice(list(Suit)).value
        first = rng.randrange(n)
        st = GameState(seats=list(seats), seed=seed, trump_suit=trump_suit,
                       trump_card=trump_card, hands=hands, stock=stock, trick=[],
                       leader=first, turn=first, captured=[[] for _ in range(n)])
        return cls(st, rules)

    @classmethod
    def replay(cls, seats: list[int], seed: int, moves: list[list],
               rules: RulesConfig = DEFAULT_RULES) -> "BriscolaGame":
        g = cls.new(seats, rules, seed)
        for seat, code in moves:
            g.apply_move(seat, code)
        return g

    def to_dict(self) -> dict:
        return self.state.to_dict()

    @classmethod
    def from_dict(cls, d: dict, rules: RulesConfig = DEFAULT_RULES) -> "BriscolaGame":
        return cls(GameState.from_dict(d), rules)

    @classmethod
    def determinize(cls, obs: Observation, other_hands: dict[int, list[str]],
                    stock: list[str], rules: RulesConfig = DEFAULT_RULES) -> "BriscolaGame":
        """Build a full-information game from one seat's view plus guessed hidden cards (AI)."""
        hands = [list(obs.hand) if s == obs.seat else list(other_hands[s]) for s in range(obs.n)]
        st = GameState(seats=list(range(obs.n)), seed=0, trump_suit=obs.trump_suit,
                       trump_card=obs.trump_card, hands=hands, stock=list(stock),
                       trick=[list(p) for p in obs.trick], leader=obs.leader,
                       turn=obs.seat, captured=[list(c) for c in obs.captured])
        return cls(st, rules)

    # ---------- queries ----------
    @property
    def n(self) -> int:
        return len(self.state.seats)

    @property
    def trump(self) -> Suit:
        return Suit(self.state.trump_suit)

    @property
    def finished(self) -> bool:
        return self.state.status == "finished"

    @property
    def current_user(self) -> int:
        return self.state.seats[self.state.turn]

    def seat_of(self, user_id: int) -> int:
        try:
            return self.state.seats.index(user_id)
        except ValueError:
            raise UnknownPlayer(user_id) from None

    def side_of(self, seat: int) -> int:
        """Team index in 4-player mode (seats 0&2 vs 1&3); the seat itself in 2-player."""
        return seat % 2 if self.n == 4 else seat

    def side_scores(self) -> list[int]:
        sides = 2 if self.n == 4 else self.n
        totals = [0] * sides
        for seat, pile in enumerate(self.state.captured):
            totals[self.side_of(seat)] += pile_points(pile, self.rules)
        return totals

    def result(self) -> dict:
        res = outcome(self.side_scores(), self.rules)
        f = self.state.forfeit_seat
        if f is not None:                       # quitter's side loses regardless of points
            bad = self.side_of(f)
            others = [i for i in range(len(res["scores"])) if i != bad]
            res.update(draw=False, decisive=True, forfeit=True,
                       winner_side=others[0] if len(others) == 1 else None,
                       winner_sides=others)
        else:
            res["winner_sides"] = [] if res["draw"] else [res["winner_side"]]
        return res

    def forfeit(self, seat: int) -> None:
        """Player quits or is removed for inactivity: game ends, their side loses."""
        if self.finished:
            raise GameOver()
        self.state.forfeit_seat = seat
        self.state.status = "finished"
        self.state.version += 1

    def observation(self, seat: int) -> Observation:
        st = self.state
        return Observation(seat=seat, n=self.n, hand=list(st.hands[seat]),
                           trump_suit=st.trump_suit, trump_card=st.trump_card,
                           trick=[list(p) for p in st.trick],
                           captured=[list(c) for c in st.captured],
                           hand_sizes=[len(h) for h in st.hands],
                           stock_count=len(st.stock), leader=st.leader)

    def public_view(self) -> dict:
        """Safe for the group chat: contains no private hand information."""
        st = self.state
        return {"seats": list(st.seats), "turn": st.turn, "trump_suit": st.trump_suit,
                "trump_card": st.trump_card, "stock_count": len(st.stock),
                "trick": [list(p) for p in st.trick], "scores": self.side_scores(),
                "version": st.version, "finished": self.finished}

    # ---------- moves ----------
    def play_card(self, user_id: int, code: str,
                  expected_version: int | None = None) -> MoveResult:
        """Entry point for handlers. Validates everything server-side."""
        if self.finished:
            raise GameOver()
        if expected_version is not None and expected_version != self.state.version:
            raise StaleMove()
        return self.apply_move(self.seat_of(user_id), code)

    def apply_move(self, seat: int, code: str) -> MoveResult:
        st = self.state
        if self.finished:
            raise GameOver()
        if seat != st.turn:
            raise NotYourTurn()
        if code not in st.hands[seat]:
            raise CardNotInHand(code)
        st.hands[seat].remove(code)
        st.trick.append([seat, code])
        st.moves.append([seat, code])
        st.version += 1
        res = MoveResult(seat=seat, card=code, version=st.version)
        if len(st.trick) < self.n:
            st.turn = (st.turn + 1) % self.n
            return res
        plays = [(s, card(c)) for s, c in st.trick]
        winner = trick_winner(plays, self.trump, self.rules)
        res.trick_complete = True
        res.trick_winner = winner
        res.trick_points = sum(self.rules.point_of(c) for _, c in plays)
        st.captured[winner].extend(c for _, c in st.trick)
        st.trick = []
        for i in range(self.n):                      # winner draws first
            s = (winner + i) % self.n
            if st.stock:
                res.drawn[s] = st.stock.pop()
                st.hands[s].append(res.drawn[s])
        st.leader = st.turn = winner
        if not any(st.hands):
            st.status = "finished"
            res.finished = True
        return res
