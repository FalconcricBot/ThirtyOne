"""Lobby state: private rooms, quick-match queues, and the 'one activity per user' registry.
Pure in-memory logic (no Telegram / DB) so it is unit-testable. Rooms are short-lived by design;
only *games* are persisted."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from utils.helpers import new_room_code


class LobbyError(Exception):
    """Message is safe to show to the user."""


@dataclass
class Room:
    code: str
    mode: int                                   # 2 or 4 players
    owner_id: int
    players: list[tuple[int, str]]              # (user_id, name) in seating order
    chat_id: int                                # where the room card lives (group or private)
    message_id: int | None = None
    message_kind: str = "text"
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    starting: bool = False
    game: str = "briscola"                       # briscola | thirty_one
    options: dict = field(default_factory=dict)  # e.g. 31: {"mode": "lives"}

    @property
    def full(self) -> bool:
        return len(self.players) >= self.mode

    def has(self, uid: int) -> bool:
        return any(p[0] == uid for p in self.players)


class Lobby:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.user_room: dict[int, str] = {}
        self.queues: dict[int, list[tuple[int, str, float]]] = {2: [], 4: []}
        self.playing: set[int] = set()          # users currently inside a running game

    # ---- registry
    def busy_reason(self, uid: int) -> str | None:
        if uid in self.playing:
            return "You are already in a running match. Finish it (or /leave) first."
        if uid in self.user_room:
            return f"You are already in room {self.user_room[uid]}. Use /leave first."
        if self.in_queue(uid):
            return "You are searching for a match. Use /cancel first."
        return None

    def set_playing(self, uids, on: bool = True) -> None:
        for u in uids:
            (self.playing.add if on else self.playing.discard)(u)

    # ---- rooms
    def create_room(self, owner_id: int, name: str, mode: int, chat_id: int, *, game: str = "briscola",
                    options: dict | None = None) -> Room:
        if game == "briscola" and mode not in (2, 4):
            raise LobbyError("Mode must be 2 or 4 players.")
        if game == "thirty_one" and not 2 <= mode <= 7:
            raise LobbyError("31 supports 2 to 7 players.")
        reason = self.busy_reason(owner_id)
        if reason:
            raise LobbyError(reason)
        room = Room(code=new_room_code(set(self.rooms), "31" if game == "thirty_one" else "BA"), mode=mode,
                    owner_id=owner_id, players=[(owner_id, name)], chat_id=chat_id, game=game,
                    options=dict(options or {}))
        self.rooms[room.code] = room
        self.user_room[owner_id] = room.code
        return room

    def join_room(self, code: str, uid: int, name: str) -> Room:
        room = self.rooms.get(code)
        if room is None or room.starting:
            raise LobbyError("Room not found or already started.")
        if room.has(uid):
            raise LobbyError("You are already in this room.")
        reason = self.busy_reason(uid)
        if reason:
            raise LobbyError(reason)
        if room.full:
            raise LobbyError("This room is full.")
        room.players.append((uid, name))
        room.last_activity = time.time()
        self.user_room[uid] = code
        return room

    def leave_room(self, uid: int) -> tuple[Room | None, bool]:
        """-> (room, closed). If the owner leaves, ownership passes on; empty rooms close."""
        code = self.user_room.pop(uid, None)
        room = self.rooms.get(code) if code else None
        if room is None:
            return None, False
        room.players = [p for p in room.players if p[0] != uid]
        room.last_activity = time.time()
        if not room.players:
            self.rooms.pop(code, None)
            return room, True
        if room.owner_id == uid:
            room.owner_id = room.players[0][0]
        return room, False

    def fill_ai(self, code: str, by: int) -> Room:
        room = self.rooms.get(code)
        if room is None:
            raise LobbyError("Room not found.")
        if room.owner_id != by:
            raise LobbyError("Only the room owner can add AI players.")
        while not room.full:
            seat = len(room.players)
            room.players.append((-(seat + 1), f"🤖 Bot {seat + 1}"))
        room.last_activity = time.time()
        return room

    def add_ai(self, code: str, by: int) -> Room:
        """Add ONE bot seat (31 rooms start with any number of players, so bots are added one by one)."""
        room = self.rooms.get(code)
        if room is None:
            raise LobbyError("Room not found.")
        if room.owner_id != by:
            raise LobbyError("Only the room owner can add AI players.")
        if room.full:
            raise LobbyError("The room is full.")
        seat = len(room.players)
        room.players.append((-(seat + 1), f"🤖 Bot {seat + 1}"))
        room.last_activity = time.time()
        return room

    def close_room(self, code: str) -> Room | None:
        room = self.rooms.pop(code, None)
        if room:
            for uid, _ in room.players:
                self.user_room.pop(uid, None)
        return room

    def begin_start(self, code: str, by: int) -> Room:
        room = self.rooms.get(code)
        if room is None:
            raise LobbyError("Room not found.")
        if room.owner_id != by:
            raise LobbyError("Only the room owner can start the game.")
        if room.starting:
            raise LobbyError("The game is already starting.")
        if len(room.players) < 2:
            raise LobbyError("You need at least 2 players (or add AI players).")
        room.starting = True
        return room

    def finish_start(self, code: str) -> None:
        """Room turned into a game: members move from 'in room' to 'playing'."""
        room = self.close_room(code)
        if room:
            self.set_playing(u for u, _ in room.players)

    def abort_start(self, code: str) -> None:
        room = self.rooms.get(code)
        if room:
            room.starting = False

    def expire_rooms(self, ttl_seconds: float, now: float | None = None) -> list[Room]:
        now = now or time.time()
        dead = [r for r in self.rooms.values() if not r.starting and now - r.last_activity > ttl_seconds]
        for r in dead:
            self.close_room(r.code)
        return dead

    # ---- quick match
    def in_queue(self, uid: int) -> bool:
        return any(u == uid for q in self.queues.values() for u, _, _ in q)

    def queue_add(self, uid: int, name: str, mode: int, size: int | None = None) -> list[tuple[int, str]] | None:
        """Returns the matched players (and removes them from the queue) when a table is full.
        `mode` is the queue key (Briscola 2/4, 31 uses 102..107); `size` defaults to `mode`."""
        reason = self.busy_reason(uid)
        if reason:
            raise LobbyError(reason)
        size = size or mode
        q = self.queues.setdefault(mode, [])
        q.append((uid, name, time.time()))
        if len(q) >= size:
            group, self.queues[mode] = q[:size], q[size:]
            return [(u, n) for u, n, _ in group]
        return None

    def queue_remove(self, uid: int) -> bool:
        removed = False
        for m in self.queues:
            before = len(self.queues[m])
            self.queues[m] = [x for x in self.queues[m] if x[0] != uid]
            removed |= len(self.queues[m]) != before
        return removed

    def queue_size(self, mode: int) -> int:
        return len(self.queues.get(mode, []))

    def expire_queue(self, max_wait: float, now: float | None = None) -> list[int]:
        now = now or time.time()
        gone = [u for q in self.queues.values() for u, _, t in q if now - t > max_wait]
        for u in gone:
            self.queue_remove(u)
        return gone
