"""52-card deck for Thirty-One. Codes: rank + suit letter, e.g. 'AH', '10S', 'KD'."""
from __future__ import annotations

SUITS = ("H", "D", "C", "S")
SYMBOL = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
SUIT_NAME = {"H": "Hearts", "D": "Diamonds", "C": "Clubs", "S": "Spades"}
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
VALUE = {"A": 11, "K": 10, "Q": 10, "J": 10, "10": 10, "9": 9, "8": 8, "7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2}
ALL_CODES = tuple(r + s for s in SUITS for r in RANKS)
_VALID = set(ALL_CODES)


def build_deck() -> list[str]:
    return list(ALL_CODES)


def valid(code: str) -> bool:
    return code in _VALID


def rank(code: str) -> str:
    return code[:-1]


def suit(code: str) -> str:
    return code[-1]


def value(code: str) -> int:
    return VALUE[code[:-1]]


def label(code: str) -> str:
    return f"{code[:-1]}{SYMBOL[code[-1]]}"
