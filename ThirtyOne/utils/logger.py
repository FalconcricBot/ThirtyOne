from __future__ import annotations

import logging
import sys
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILE = Path("logs") / "bot.log"
_errors_today: deque = deque(maxlen=1000)       # (timestamp, message)
_pending: list[str] = []                         # errors not yet reported to the admins


class ErrorCounter(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            msg = record.getMessage()[:200]
            _errors_today.append((record.created, msg))
            if len(_pending) < 200:
                _pending.append(msg)


def error_count(since_ts: float = 0.0) -> int:
    return sum(1 for ts, _ in _errors_today if ts >= since_ts)


def take_pending_errors() -> list[str]:
    """Errors logged since the last call (used by the admin alert job)."""
    out = list(_pending)
    _pending.clear()
    return out


def setup_logging(level: str = "INFO") -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    for h in (logging.StreamHandler(sys.stdout),
              RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
              ErrorCounter()):
        h.setFormatter(fmt)
        root.addHandler(h)
    for noisy in ("httpx", "httpcore", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def tail_log(lines: int = 30) -> str:
    if not LOG_FILE.exists():
        return "(no log file yet)"
    with LOG_FILE.open(encoding="utf-8", errors="replace") as f:
        return "".join(deque(f, maxlen=lines))
