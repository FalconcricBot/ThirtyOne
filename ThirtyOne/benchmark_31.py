"""Compare AI levels: python benchmark_31.py"""
import random
from game.thirty_one.ai import choose_action
from game.thirty_one.engine import ThirtyOneGame


def play(levels, seed):
    g = ThirtyOneGame.new(list(range(1, len(levels) + 1)), seed=seed)
    rng = random.Random(seed)
    while not g.finished:
        st = g.state
        if st.phase == "between":
            g.start_next_round(); continue
        act, arg = choose_action(g.observation(st.turn), levels[st.turn], rng)
        g.apply(st.turn, act, arg)
    return g.result()["winner_sides"][0]


def match(a, b, games=60):
    w = {a: 0, b: 0}
    for i in range(games):
        order = [a, b] if i % 2 == 0 else [b, a]
        w[order[play(order, i)]] += 1
    return w


if __name__ == "__main__":
    for a, b in (("medium", "easy"), ("hard", "medium"), ("expert", "hard"), ("expert", "easy")):
        print(a, "vs", b, match(a, b, 60 if "expert" not in (a, b) else 30))
