from __future__ import annotations

from .cards import suit, value, rank
from .rules import DEFAULT_CONFIG, ThirtyOneConfig


def suit_totals(hand: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in hand:
        out[suit(c)] = out.get(suit(c), 0) + value(c)
    return out


def is_three_of_a_kind(hand: list[str]) -> bool:
    return len(hand) == 3 and len({rank(c) for c in hand}) == 1


def hand_score(hand: list[str], cfg: ThirtyOneConfig = DEFAULT_CONFIG) -> float:
    """Best same-suit total, or the three-of-a-kind score if that rule is on and it is higher."""
    best = max(suit_totals(hand).values(), default=0)
    if cfg.three_kind_enabled and is_three_of_a_kind(hand):
        return max(best, cfg.three_kind_score)
    return best


def best_suit(hand: list[str]) -> str | None:
    t = suit_totals(hand)
    return max(t, key=lambda s: (t[s], sum(1 for c in hand if suit(c) == s))) if t else None


def counting_cards(hand: list[str], cfg: ThirtyOneConfig = DEFAULT_CONFIG) -> list[str]:
    """The cards that make up the score (used to highlight them in the picture)."""
    if cfg.three_kind_enabled and is_three_of_a_kind(hand) and cfg.three_kind_score > max(suit_totals(hand).values()):
        return list(hand)
    s = best_suit(hand)
    return [c for c in hand if suit(c) == s]


def is_31(hand: list[str]) -> bool:
    return max(suit_totals(hand).values(), default=0) == 31


def best_after_discard(hand4: list[str], cfg: ThirtyOneConfig = DEFAULT_CONFIG,
                       forbidden: str | None = None) -> tuple[float, str]:
    """-> (best score reachable, card to discard) for a 4-card hand."""
    best = None
    for c in hand4:
        if c == forbidden:
            continue
        rest = [x for x in hand4 if x != c]
        key = (hand_score(rest, cfg), max(suit_totals(rest).values()), -value(c))
        if best is None or key > best[0]:
            best = (key, c)
    return best[0][0], best[1]
