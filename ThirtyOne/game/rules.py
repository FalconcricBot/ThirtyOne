"""Configurable rules engine: points, strength order, trump selection, win threshold."""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import RANKS, Card, Suit

DEFAULT_POINTS = {"A": 11, "3": 10, "K": 4, "Q": 3, "J": 2,
                  "7": 0, "6": 0, "5": 0, "4": 0, "2": 0}


@dataclass(frozen=True)
class RulesConfig:
    points: tuple = tuple(DEFAULT_POINTS.items())
    strength: tuple = RANKS            # strongest first
    hand_size: int = 3
    win_threshold: int = 60            # strictly more than this wins
    # "bottom_card": traditional - last stock card is shown, last drawer takes it
    # "random_suit": trump suit is picked at random, no trump card is shown
    trump_mode: str = "bottom_card"
    _pts: dict = field(init=False, repr=False, compare=False, default_factory=dict)
    _pow: dict = field(init=False, repr=False, compare=False, default_factory=dict)

    def __post_init__(self):
        if self.trump_mode not in ("bottom_card", "random_suit"):
            raise ValueError("trump_mode must be 'bottom_card' or 'random_suit'")
        object.__setattr__(self, "_pts", dict(self.points))
        n = len(self.strength)
        object.__setattr__(self, "_pow", {r: n - i for i, r in enumerate(self.strength)})

    def point_of(self, c: Card) -> int:
        return self._pts[c.rank]

    def power_of(self, c: Card) -> int:
        return self._pow[c.rank]

    @property
    def total_points(self) -> int:
        return sum(self._pts[r] for r in RANKS) * len(Suit)


DEFAULT_RULES = RulesConfig()


def trick_winner(plays: list[tuple[int, Card]], trump: Suit,
                 rules: RulesConfig = DEFAULT_RULES) -> int:
    """plays = [(seat, Card)] in play order. Returns the winning seat.

    Trump beats everything; otherwise the strongest card of the led suit wins.
    """
    lead = plays[0][1].suit

    def key(p):
        c = p[1]
        if c.suit == trump:
            return (2, rules.power_of(c))
        if c.suit == lead:
            return (1, rules.power_of(c))
        return (0, 0)

    return max(plays, key=key)[0]
