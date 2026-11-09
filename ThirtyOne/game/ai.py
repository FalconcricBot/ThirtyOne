"""Computer opponents. The AI only ever sees an Observation (no peeking at hidden cards)."""
from __future__ import annotations

import random

from .cards import ALL_CARDS, Suit, card
from .engine import BriscolaGame, Observation
from .rules import DEFAULT_RULES, RulesConfig, trick_winner

DIFFICULTIES = ("easy", "medium", "hard", "expert")


def heuristic_pick(hand: list[str], trick: list[list], trump: Suit, rules: RulesConfig,
                   n: int, seat: int, smart: bool = True) -> str:
    cards = [card(c) for c in hand]

    def low_key(c):  # cheapest card to give away: non-trump, few points, weak
        return (c.suit == trump, rules.point_of(c), rules.power_of(c))

    if not trick:
        return min(cards, key=low_key).code
    plays = [(s, card(c)) for s, c in trick]
    trick_pts = sum(rules.point_of(c) for _, c in plays)
    current = trick_winner(plays, trump, rules)
    if smart and n == 4 and current == (seat + 2) % 4:
        if len(trick) == n - 1:   # partner's win is safe: load it with points
            return max(cards, key=lambda c: (c.suit != trump, rules.point_of(c),
                                             -rules.power_of(c))).code
        return min(cards, key=low_key).code
    winners = [c for c in cards if trick_winner(plays + [(seat, c)], trump, rules) == seat]
    if winners:
        cheapest = min(winners, key=lambda c: (c.suit == trump, rules.power_of(c)))
        gain = trick_pts + rules.point_of(cheapest)
        if cheapest.suit != trump:
            return cheapest.code
        if gain >= (4 if smart else 1):
            return cheapest.code
    return min(cards, key=low_key).code


def _expert(obs: Observation, rules: RulesConfig, rng: random.Random, sims: int) -> str:
    n = obs.n
    trump = Suit(obs.trump_suit)
    seen = set(obs.hand) | {c for pile in obs.captured for c in pile} | {c for _, c in obs.trick}
    bottom = obs.trump_card if (obs.stock_count > 0 and obs.trump_card) else None
    unseen = [c for c in ALL_CARDS if c not in seen and c != bottom]
    others = [s for s in range(n) if s != obs.seat]
    me = obs.seat % 2 if n == 4 else obs.seat
    totals = {c: 0.0 for c in set(obs.hand)}
    for _ in range(sims):
        pool = unseen[:]
        rng.shuffle(pool)
        other_hands, i = {}, 0
        for s in others:
            k = obs.hand_sizes[s]
            other_hands[s] = pool[i:i + k]
            i += k
        stock = ([bottom] if bottom else []) + pool[i:]
        for c in totals:
            g = BriscolaGame.determinize(obs, other_hands, stock, rules)
            g.apply_move(obs.seat, c)
            while not g.finished:
                s = g.state.turn
                g.apply_move(s, heuristic_pick(g.state.hands[s], g.state.trick, trump,
                                               rules, n, s, True))
            sc = g.side_scores()
            totals[c] += sc[me % len(sc)] - sc[1 - (me % 2)] if len(sc) == 2 else \
                sc[me] - max(x for j, x in enumerate(sc) if j != me)
    return max(totals, key=totals.get)


def choose_card(obs: Observation, difficulty: str = "medium",
                rules: RulesConfig = DEFAULT_RULES, rng: random.Random | None = None) -> str:
    rng = rng or random.Random()
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}")
    if len(obs.hand) == 1:
        return obs.hand[0]
    trump = Suit(obs.trump_suit)
    if difficulty == "easy":
        return rng.choice(obs.hand)
    if difficulty == "medium":
        return heuristic_pick(obs.hand, obs.trick, trump, rules, obs.n, obs.seat, smart=False)
    if difficulty == "hard":     # light look-ahead
        return _expert(obs, rules, rng, sims=8)
    return _expert(obs, rules, rng, sims=60)   # expert: deeper look-ahead
