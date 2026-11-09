"""Quick strength check: python benchmark_ai.py"""
import random, sys
from game.ai import choose_card
from game.engine import BriscolaGame

def match(a, b, games=60):
    wins = {a: 0, b: 0}; 
    for i in range(games):
        order = [a, b] if i % 2 == 0 else [b, a]
        g = BriscolaGame.new([-1, -2], seed=i); rng = random.Random(i)
        while not g.finished:
            s = g.state.turn
            g.apply_move(s, choose_card(g.observation(s), order[s], rng=rng))
        sc = g.side_scores()
        if sc[0] != sc[1]:
            wins[order[0 if sc[0] > sc[1] else 1]] += 1
    return wins

if __name__ == "__main__":
    for a, b in (("medium", "easy"), ("hard", "medium"), ("expert", "hard")):
        print(a, "vs", b, match(a, b, 60 if a != "expert" else 40))
