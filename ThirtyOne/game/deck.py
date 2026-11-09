from __future__ import annotations

import random

from .cards import ALL_CARDS


def build_deck() -> list[str]:
    """Fresh, ordered 40-card deck (codes)."""
    return list(ALL_CARDS)


def shuffled_deck(rng: random.Random) -> list[str]:
    deck = build_deck()
    rng.shuffle(deck)
    return deck
