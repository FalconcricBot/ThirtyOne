from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ThirtyOneState:
    config: dict
    seed: int
    players: list[int]                    # user ids by seat (AI = negative ids)
    lives: list[int]
    totals: list[float]
    active: list[bool]
    round_no: int
    first: int                            # seat that starts the current round
    hands: list[list[str]]
    draw_pile: list[str]                  # draw from the END
    discard: list[str]                    # last element = face-up top card
    turn: int
    phase: str                            # draw | discard | between | finished
    drawn_card: str | None = None         # card picked up this turn (marked NEW)
    taken_from_discard: str | None = None  # may not be thrown straight back
    knocker: int | None = None
    final_left: list[int] = field(default_factory=list)
    reshuffles: int = 0
    known: list[list[str]] = field(default_factory=list)   # public: discard-pile cards each seat picked up and still holds
    last_round: dict | None = None
    elim_order: list[int] = field(default_factory=list)    # earliest eliminated first
    pstats: list[dict] = field(default_factory=list)       # per seat: rounds, times_31, knock_wins, knock_losses, best
    version: int = 0
    status: str = "active"
    moves: list[list] = field(default_factory=list)        # [round, seat, action, card|None]
    forfeit_seats: list[int] = field(default_factory=list)
    winner_seats: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ThirtyOneState":
        return cls(**d)
