import json
import random
import unittest

from game.ai import DIFFICULTIES, choose_card
from game.cards import ALL_CARDS
from game.engine import (BriscolaGame, CardNotInHand, GameOver, NotYourTurn,
                         StaleMove, UnknownPlayer)


def play_random(g, rng):
    while not g.finished:
        seat = g.state.turn
        g.apply_move(seat, rng.choice(g.state.hands[seat]))
    return g


class GameFlowTests(unittest.TestCase):
    def test_full_two_player_games(self):
        for seed in range(40):
            g = play_random(BriscolaGame.new([10, 20], seed=seed), random.Random(seed))
            self.assertEqual(sum(g.side_scores()), 120)
            self.assertEqual(sum(len(p) for p in g.state.captured), 40)
            self.assertEqual(g.state.stock, [])

    def test_full_four_player_games_team_scoring(self):
        for seed in range(40):
            g = play_random(BriscolaGame.new([1, 2, 3, 4], seed=seed), random.Random(seed))
            a, b = g.side_scores()
            self.assertEqual(a + b, 120)
            # team A = seats 0 and 2
            from game.scoring import pile_points
            self.assertEqual(a, pile_points(g.state.captured[0] + g.state.captured[2]))
            self.assertEqual(b, pile_points(g.state.captured[1] + g.state.captured[3]))

    def test_winner_leads_next_and_draws_first(self):
        g = BriscolaGame.new([1, 2], seed=7)
        s = g.state.turn
        g.apply_move(s, g.state.hands[s][0])
        o = g.state.turn
        r = g.apply_move(o, g.state.hands[o][0])
        self.assertTrue(r.trick_complete)
        self.assertEqual(g.state.turn, r.trick_winner)
        self.assertEqual(g.state.leader, r.trick_winner)
        self.assertEqual(list(r.drawn)[0], r.trick_winner)
        self.assertEqual([len(h) for h in g.state.hands], [3, 3])

    def test_last_drawer_gets_trump_card_and_deck_exhaustion(self):
        g = BriscolaGame.new([1, 2], seed=11)
        trump_card = g.state.trump_card
        last_drawn = None
        while not g.finished:
            seat = g.state.turn
            before = len(g.state.stock)
            r = g.apply_move(seat, g.state.hands[seat][0])
            if before == 2 and r.trick_complete:
                last_drawn = r.drawn
        self.assertEqual(list(last_drawn.values())[-1], trump_card)

    def test_hands_shrink_after_stock_empty(self):
        g = BriscolaGame.new([1, 2], seed=2)
        while g.state.stock:
            seat = g.state.turn
            g.apply_move(seat, g.state.hands[seat][0])
        self.assertEqual([len(h) for h in g.state.hands], [3, 3])
        seat = g.state.turn
        g.apply_move(seat, g.state.hands[seat][0])
        g.apply_move(g.state.turn, g.state.hands[g.state.turn][0])
        self.assertEqual(sorted(len(h) for h in g.state.hands), [2, 2])

    def test_no_card_lost_or_duplicated_mid_game(self):
        g = BriscolaGame.new([1, 2, 3, 4], seed=9)
        rng = random.Random(9)
        for _ in range(30):
            seat = g.state.turn
            g.apply_move(seat, rng.choice(g.state.hands[seat]))
            every = ([c for h in g.state.hands for c in h] + g.state.stock +
                     [c for p in g.state.captured for c in p] + [c for _, c in g.state.trick])
            self.assertEqual(sorted(every), sorted(ALL_CARDS))


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.g = BriscolaGame.new([100, 200], seed=1)
        self.cur = self.g.current_user
        self.other = 200 if self.cur == 100 else 100

    def test_unauthorized_move(self):
        card = self.g.state.hands[self.g.seat_of(self.other)][0]
        with self.assertRaises(NotYourTurn):
            self.g.play_card(self.other, card)

    def test_card_not_in_hand(self):
        mine = set(self.g.state.hands[self.g.seat_of(self.cur)])
        foreign = next(c for c in ALL_CARDS if c not in mine)
        with self.assertRaises(CardNotInHand):
            self.g.play_card(self.cur, foreign)

    def test_unknown_player(self):
        with self.assertRaises(UnknownPlayer):
            self.g.play_card(999, "AH")

    def test_duplicate_callback_rejected_via_version(self):
        card = self.g.state.hands[self.g.seat_of(self.cur)][0]
        v = self.g.state.version
        self.g.play_card(self.cur, card, expected_version=v)
        with self.assertRaises(StaleMove):
            self.g.play_card(self.cur, card, expected_version=v)
        self.assertEqual(len(self.g.state.trick), 1)

    def test_move_after_game_over(self):
        g = play_random(BriscolaGame.new([1, 2], seed=4), random.Random(4))
        with self.assertRaises(GameOver):
            g.play_card(1, "AH")

    def test_public_view_has_no_hands(self):
        view = self.g.public_view()
        blob = json.dumps(view)
        self.assertNotIn("hands", view)
        for seat_hand in self.g.state.hands:
            for c in seat_hand:
                if c != self.g.state.trump_card:
                    self.assertNotIn(f'"{c}"', blob)

    def test_observation_is_private(self):
        obs = self.g.observation(0)
        self.assertEqual(obs.hand, self.g.state.hands[0])
        self.assertFalse(hasattr(obs, "hands"))


class PersistenceTests(unittest.TestCase):
    def test_json_roundtrip_mid_game_then_finish(self):
        g = BriscolaGame.new([1, 2, 3, 4], seed=21)
        rng = random.Random(21)
        for _ in range(13):
            s = g.state.turn
            g.apply_move(s, rng.choice(g.state.hands[s]))
        restored = BriscolaGame.from_dict(json.loads(json.dumps(g.to_dict())))
        self.assertEqual(restored.to_dict(), g.to_dict())
        play_random(restored, random.Random(1))
        self.assertTrue(restored.finished)

    def test_replay_reproduces_game(self):
        g = play_random(BriscolaGame.new([1, 2], seed=33), random.Random(33))
        r = BriscolaGame.replay([1, 2], 33, g.state.moves)
        self.assertEqual(r.to_dict(), g.to_dict())

    def test_simultaneous_games_are_independent(self):
        games = [BriscolaGame.new([i, i + 1000], seed=i) for i in range(25)]
        rngs = [random.Random(i) for i in range(25)]
        while not all(g.finished for g in games):          # interleave moves
            for g, rng in zip(games, rngs):
                if not g.finished:
                    s = g.state.turn
                    g.apply_move(s, rng.choice(g.state.hands[s]))
        for i, g in enumerate(games):
            solo = play_random(BriscolaGame.new([i, i + 1000], seed=i), random.Random(i))
            self.assertEqual(g.to_dict(), solo.to_dict())


class AITests(unittest.TestCase):
    def test_ai_always_plays_legal_cards_all_levels(self):
        for level in DIFFICULTIES:
            for n, seats in ((2, [-1, -2]), (4, [-1, -2, -3, -4])):
                g = BriscolaGame.new(seats, seed=n * 7)
                rng = random.Random(1)
                while not g.finished:
                    s = g.state.turn
                    c = choose_card(g.observation(s), level, rng=rng)
                    self.assertIn(c, g.state.hands[s])
                    g.play_card(g.current_user, c, expected_version=g.state.version)
                self.assertEqual(sum(g.side_scores()), 120)

    def test_ai_takes_free_points_and_does_not_waste_trump(self):
        from game.engine import Observation
        obs = Observation(seat=1, n=2, hand=["AS", "2H", "4D"], trump_suit="H", trump_card="KH",
                          trick=[[0, "3S"]], captured=[[], []], hand_sizes=[2, 3],
                          stock_count=10, leader=0)
        self.assertEqual(choose_card(obs, "medium"), "AS")          # beats the 3 with the ace
        obs.hand, obs.trick = ["2H", "6C", "5S"], [[0, "4D"]]
        self.assertEqual(choose_card(obs, "medium"), "5S")        # only a trump wins 0 points: don't burn it
        for level in ("hard", "expert"):     # look-ahead levels decide by simulation: just require a legal card
            self.assertIn(choose_card(obs, level, rng=random.Random(1)), obs.hand)


if __name__ == "__main__":
    unittest.main()


class ForfeitTests(unittest.TestCase):
    def test_forfeit_two_player(self):
        g = BriscolaGame.new([1, 2], seed=5)
        g.forfeit(0)
        r = g.result()
        self.assertTrue(g.finished)
        self.assertEqual(r["winner_sides"], [1])
        with self.assertRaises(GameOver):
            g.forfeit(1)

    def test_forfeit_four_player_whole_team_loses(self):
        g = BriscolaGame.new([1, 2, 3, 4], seed=5)
        g.forfeit(1)                       # seat 1 is on team B
        self.assertEqual(g.result()["winner_sides"], [0])
        self.assertEqual(BriscolaGame.from_dict(g.to_dict()).result()["winner_sides"], [0])
