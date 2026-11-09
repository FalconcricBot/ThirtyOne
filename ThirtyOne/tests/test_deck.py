import random
import unittest

from game.cards import ALL_CARDS, RANKS, Suit, card
from game.deck import build_deck, shuffled_deck
from game.engine import BriscolaGame
from game.rules import RulesConfig


class DeckTests(unittest.TestCase):
    def test_deck_has_40_unique_cards_without_8_9_10(self):
        d = build_deck()
        self.assertEqual(len(d), 40)
        self.assertEqual(len(set(d)), 40)
        self.assertFalse({"8", "9", "10"} & {c[:-1] for c in d})
        self.assertEqual(set(RANKS), {c[:-1] for c in d})

    def test_shuffle_is_deterministic_per_seed(self):
        self.assertEqual(shuffled_deck(random.Random(5)), shuffled_deck(random.Random(5)))
        self.assertNotEqual(shuffled_deck(random.Random(5)), shuffled_deck(random.Random(6)))

    def test_unknown_card(self):
        with self.assertRaises(ValueError):
            card("10H")

    def test_deal_two_players(self):
        g = BriscolaGame.new([1, 2], seed=1)
        self.assertEqual([len(h) for h in g.state.hands], [3, 3])
        self.assertEqual(len(g.state.stock), 34)
        self.assertEqual(g.state.trump_card, g.state.stock[0])
        self.assertEqual(g.state.trump_suit, card(g.state.trump_card).suit.value)
        self._all_cards_unique(g)

    def test_deal_four_players(self):
        g = BriscolaGame.new([1, 2, 3, 4], seed=1)
        self.assertEqual([len(h) for h in g.state.hands], [3] * 4)
        self.assertEqual(len(g.state.stock), 28)
        self._all_cards_unique(g)

    def test_random_suit_mode(self):
        g = BriscolaGame.new([1, 2], RulesConfig(trump_mode="random_suit"), seed=3)
        self.assertIsNone(g.state.trump_card)
        self.assertIn(g.trump, list(Suit))

    def test_first_player_is_random_but_valid(self):
        firsts = {BriscolaGame.new([1, 2, 3, 4], seed=s).state.turn for s in range(60)}
        self.assertEqual(firsts, {0, 1, 2, 3})

    def test_bad_player_counts(self):
        for seats in ([1], [1, 2, 3], [1, 1]):
            with self.assertRaises(ValueError):
                BriscolaGame.new(seats)

    def _all_cards_unique(self, g):
        every = [c for h in g.state.hands for c in h] + g.state.stock
        self.assertEqual(sorted(every), sorted(ALL_CARDS))


if __name__ == "__main__":
    unittest.main()
