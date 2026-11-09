"""Configurable rules for Thirty-One. Admins can change the defaults from Telegram (/t31config)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

MODES = ("lives", "knockout", "points")
TIE_RULES = ("all_lose", "none_lose", "high_card")
INSTANT_RULES = ("lowest_loses", "all_others_lose")


@dataclass(frozen=True)
class ThirtyOneConfig:
    min_players: int = 2
    max_players: int = 7
    mode: str = "lives"                  # lives | knockout (1 life, sudden death) | points
    start_lives: int = 3
    knock_enabled: bool = True
    knock_penalty_extra: int = 0         # extra lives the knocker loses if he ends up lowest (classic = 1)
    auto_declare_31: bool = True         # reaching 31 ends the round at once (else: press DECLARE 31)
    instant_31_rule: str = "lowest_loses"  # lowest_loses | all_others_lose
    three_kind_enabled: bool = True      # three cards of the same rank count as three_kind_score
    three_kind_score: float = 30.5
    tie_rule: str = "all_lose"           # all_lose | none_lose | high_card
    points_rounds: int = 5               # rounds played in points mode
    turn_timeout: int = 45
    lives_mode_enabled: bool = True
    points_mode_enabled: bool = True
    round_pause: int = 8                 # seconds the reveal stays on screen

    def __post_init__(self):
        if not 2 <= self.min_players <= self.max_players <= 7:
            raise ValueError("players: 2 <= min <= max <= 7")
        if self.mode not in MODES or self.tie_rule not in TIE_RULES or self.instant_31_rule not in INSTANT_RULES:
            raise ValueError("unknown mode / tie rule / instant-31 rule")
        if not 1 <= self.start_lives <= 9 or not 1 <= self.points_rounds <= 20 or not 10 <= self.turn_timeout <= 600:
            raise ValueError("lives 1-9, rounds 1-20, timeout 10-600")
        if not 0 <= self.knock_penalty_extra <= 3:
            raise ValueError("knock_penalty_extra 0-3")

    @property
    def lives_at_start(self) -> int:
        return 0 if self.mode == "points" else (1 if self.mode == "knockout" else self.start_lives)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "ThirtyOneConfig":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    def replace(self, **kw) -> "ThirtyOneConfig":
        return ThirtyOneConfig.from_dict({**self.to_dict(), **kw})


DEFAULT_CONFIG = ThirtyOneConfig()
