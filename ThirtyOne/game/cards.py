"""Card primitives. Cards are identified everywhere by a short code like 'AH' or '3S'."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Suit(str, Enum):
    HEARTS = "H"
    DIAMONDS = "D"
    CLUBS = "C"
    SPADES = "S"

    @property
    def symbol(self) -> str:
        return {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}[self.value]

    @property
    def label(self) -> str:
        return f"{self.symbol} {self.name.title()}"


# Strongest first. Ranks 8, 9, 10 do not exist in a Briscola deck.
RANKS = ("A", "3", "K", "Q", "J", "7", "6", "5", "4", "2")


@dataclass(frozen=True)
class Card:
    rank: str
    suit: Suit

    @property
    def code(self) -> str:
        return f"{self.rank}{self.suit.value}"

    def __str__(self) -> str:
        return f"{self.rank}{self.suit.symbol}"


ALL_CARDS: dict[str, Card] = {
    Card(r, s).code: Card(r, s) for s in Suit for r in RANKS
}


def card(code: str) -> Card:
    try:
        return ALL_CARDS[code]
    except KeyError:
        raise ValueError(f"Unknown card code: {code!r}") from None
