"""Plain, JSON-serialisable game state (for DB persistence and crash recovery)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class GameState:
    seats: list[int]                 # user ids in seating order (AI = negative ids)
    seed: int
    trump_suit: str                  # 'H' | 'D' | 'C' | 'S'
    trump_card: str | None
    hands: list[list[str]]
    stock: list[str]                 # draw from the END; index 0 is the bottom (trump card)
    trick: list[list]                # [[seat, code], ...] in play order
    leader: int
    turn: int
    captured: list[list[str]]
    version: int = 0                 # +1 per move; used to reject stale/duplicate callbacks
    status: str = "active"           # 'active' | 'finished'
    moves: list[list] = field(default_factory=list)   # [[seat, code], ...] for replay
    forfeit_seat: int | None = None   # set when a player quits / is AFK-removed

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        d = dict(d)
        d["trick"] = [list(p) for p in d["trick"]]
        d["moves"] = [list(m) for m in d.get("moves", [])]
        return cls(**d)
