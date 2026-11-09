from __future__ import annotations

from .cards import card
from .rules import DEFAULT_RULES, RulesConfig


def pile_points(codes, rules: RulesConfig = DEFAULT_RULES) -> int:
    return sum(rules.point_of(card(c)) for c in codes)


def outcome(scores: list[int], rules: RulesConfig = DEFAULT_RULES) -> dict:
    """scores = points per side (2 sides in team mode, N players otherwise)."""
    best = max(scores)
    leaders = [i for i, s in enumerate(scores) if s == best]
    draw = len(leaders) > 1
    return {"scores": list(scores),
            "winner_side": None if draw else leaders[0],
            "draw": draw,
            "decisive": best > rules.win_threshold}
