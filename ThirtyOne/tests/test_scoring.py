import unittest

from game.scoring import outcome, pile_points


class ScoringTests(unittest.TestCase):
    def test_pile_points(self):
        self.assertEqual(pile_points(["AH", "3S", "KD", "QC", "JH", "7H", "2D"]), 30)
        self.assertEqual(pile_points([]), 0)

    def test_win_threshold(self):
        self.assertEqual(outcome([61, 59])["winner_side"], 0)
        self.assertTrue(outcome([61, 59])["decisive"])
        self.assertEqual(outcome([40, 80])["winner_side"], 1)

    def test_exact_60_60_is_draw(self):
        r = outcome([60, 60])
        self.assertTrue(r["draw"])
        self.assertIsNone(r["winner_side"])


if __name__ == "__main__":
    unittest.main()
