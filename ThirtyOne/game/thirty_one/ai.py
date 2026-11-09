"""Thirty-One computer players. They only ever see an Observation (never hidden hands).

easy   - mostly random, knocks rarely
medium - takes the discard when it improves the hand, discards the weakest card
hard   - compares the exact expected value of drawing vs taking, knocks when a quick simulation says it is safe
expert - like hard with deeper simulation, tracks what opponents picked up, avoids feeding them useful cards
"""
from __future__ import annotations

import random

from .cards import ALL_CODES, suit, value
from .rules import ThirtyOneConfig
from .scoring import best_after_discard, hand_score, is_31, suit_totals

DIFFICULTIES = ("easy", "medium", "hard", "expert")


def unseen_cards(obs) -> list[str]:
    """Cards that could be in the draw pile or in an opponent's hand (minus what we can see/deduce)."""
    held = {c for k in obs.known for c in k}
    gone = set(obs.hand) | set(obs.discard_pile) | held
    return [c for c in ALL_CODES if c not in gone]


def expected_after_draw(hand: list[str], unseen: list[str], cfg: ThirtyOneConfig) -> float:
    if not unseen:
        return hand_score(hand, cfg)
    return sum(best_after_discard(hand + [c], cfg)[0] for c in unseen) / len(unseen)


def knock_lose_prob(obs, cfg: ThirtyOneConfig, samples: int, rng: random.Random) -> float:
    """Chance that I end up among the lowest scorers if I knock now (each opponent gets one last turn)."""
    unseen = unseen_cards(obs)
    opps = [s for s in range(obs.n) if s != obs.seat and obs.active[s]]
    mine = hand_score(obs.hand, cfg)
    if not opps:
        return 0.0
    lose = 0
    for _ in range(samples):
        pool = unseen[:]
        rng.shuffle(pool)
        scores = []
        for s in opps:
            held = list(obs.known[s])[:3]
            need = 3 - len(held)
            h, pool = held + pool[:need], pool[need:]
            if pool and len(h) == 3:
                sc = best_after_discard(h + [pool.pop()], cfg)[0]
            else:
                sc = hand_score(h, cfg)
            scores.append(sc)
        if mine <= min(scores):
            lose += 1
    return lose / samples


def _discard(obs, cfg, level, rng) -> str:
    allowed = [c for c in obs.hand if c != obs.taken_from_discard]
    if level == "easy" and rng.random() < 0.65:
        return rng.choice(allowed)
    if level != "expert":
        return best_after_discard(obs.hand, cfg, forbidden=obs.taken_from_discard)[1]
    best = None
    for c in allowed:                                 # expert: also avoid handing opponents a card they collect
        rest = [x for x in obs.hand if x != c]
        feeds = sum(1 for s in range(obs.n) if s != obs.seat and obs.active[s]
                    for k in obs.known[s] if suit(k) == suit(c) and value(c) >= 8)
        key = (hand_score(rest, cfg), max(suit_totals(rest).values()), -feeds, -value(c))
        if best is None or key > best[0]:
            best = (key, c)
    return best[1]


def choose_action(obs, level: str = "medium", rng: random.Random | None = None) -> tuple[str, str | None]:
    """-> (action, argument). Always legal for the phase in obs."""
    if level not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}")
    rng = rng or random.Random()
    cfg = ThirtyOneConfig.from_dict(obs.cfg)
    if obs.phase == "discard":
        return "discard", _discard(obs, cfg, level, rng)
    score = hand_score(obs.hand, cfg)
    if is_31(obs.hand):
        return "declare", None
    can_knock = cfg.knock_enabled and obs.knocker is None and obs.round_no >= 1
    top = obs.top_discard
    if can_knock:
        if level == "easy" and score >= 28 and rng.random() < 0.2:
            return "knock", None
        if level == "medium" and score >= 27 and rng.random() < 0.6:
            return "knock", None
        if level in ("hard", "expert") and score >= 21:
            safe = 0.2 if level == "hard" else (0.2 if obs.lives[obs.seat] > 1 or cfg.mode == "points" else 0.12)
            if knock_lose_prob(obs, cfg, 40 if level == "hard" else 120, rng) < safe:
                return "knock", None
    can_take = top is not None
    if level == "easy":
        return ("take", None) if can_take and rng.random() < 0.3 else ("draw", None)
    if not can_take:
        return "draw", None
    take_value = best_after_discard(obs.hand + [top], cfg, forbidden=top)[0]
    if level == "medium":
        return ("take", None) if take_value > score else ("draw", None)
    if take_value >= 31:
        return "take", None
    exp_draw = expected_after_draw(obs.hand, unseen_cards(obs), cfg)
    return ("take", None) if take_value > exp_draw or (take_value > score and take_value >= exp_draw - 0.2) else ("draw", None)
