import itertools
import unittest

from game.cards import RANKS, Suit, card
from game.rules import DEFAULT_RULES, RulesConfig, trick_winner

H, D, C, S = Suit.HEARTS, Suit.DIAMONDS, Suit.CLUBS, Suit.SPADES


def play(*codes):
    return [(i, card(c)) for i, c in enumerate(codes)]


class RulesTests(unittest.TestCase):
    def test_strength_order_within_suit(self):
        order = ["A", "3", "K", "Q", "J", "7", "6", "5", "4", "2"]
        for hi, lo in itertools.combinations(order, 2):
            # lead the weaker card, answer with the stronger: stronger wins (trump = other suit)
            self.assertEqual(trick_winner(play(lo + "S", hi + "S"), H), 1, (hi, lo))
            self.assertEqual(trick_winner(play(hi + "S", lo + "S"), H), 0, (hi, lo))

    def test_any_trump_beats_any_non_trump(self):
        for r1, r2 in itertools.product(RANKS, RANKS):
            self.assertEqual(trick_winner(play(r1 + "S", r2 + "H"), H), 1)
            self.assertEqual(trick_winner(play(r1 + "H", r2 + "S"), H), 0)

    def test_strongest_trump_wins(self):
        self.assertEqual(trick_winner(play("2H", "3H", "AH", "KH"), H), 2)

    def test_off_suit_cannot_win(self):
        self.assertEqual(trick_winner(play("2S", "AD", "3C"), H), 0)

    def test_led_suit_beats_off_suit_without_trump(self):
        self.assertEqual(trick_winner(play("2D", "AS", "4D"), H), 2)

    def test_four_player_trick_mixed(self):
        self.assertEqual(trick_winner(play("AS", "2H", "3S", "KH"), H), 3)

    def test_points_table(self):
        pts = {r: DEFAULT_RULES.point_of(card(r + "H")) for r in RANKS}
        self.assertEqual(pts, {"A": 11, "3": 10, "K": 4, "Q": 3, "J": 2,
                               "7": 0, "6": 0, "5": 0, "4": 0, "2": 0})
        self.assertEqual(DEFAULT_RULES.total_points, 120)

    def test_configurable_rules(self):
        r = RulesConfig(strength=("3", "A", "K", "Q", "J", "7", "6", "5", "4", "2"))
        self.assertEqual(trick_winner(play("AS", "3S"), H, r), 1)
        with self.assertRaises(ValueError):
            RulesConfig(trump_mode="nope")


if __name__ == "__main__":
    unittest.main()
