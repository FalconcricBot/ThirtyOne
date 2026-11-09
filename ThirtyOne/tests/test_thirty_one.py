"""31 Card Game: engine rules, scoring, lives, knock, AI, persistence, images, keyboards, admin config."""
import json
import random
import unittest

from tests import fake_telegram

fake_telegram.install()

from game.thirty_one import cards as C                                              # noqa: E402
from game.thirty_one.ai import DIFFICULTIES, choose_action, unseen_cards            # noqa: E402
from game.thirty_one.engine import (CardNotInHand, GameOver, IllegalAction, NotYourTurn, StaleMove,   # noqa: E402
                                    ThirtyOneGame, UnknownPlayer, WrongPhase)
from game.thirty_one.rules import ThirtyOneConfig                                   # noqa: E402
from game.thirty_one.scoring import (best_after_discard, counting_cards, hand_score, is_31,       # noqa: E402
                                     suit_totals)

CFG = ThirtyOneConfig()


def make(n=3, **cfg):
    g = ThirtyOneGame.new(list(range(1, n + 1)), ThirtyOneConfig(**cfg), seed=7)
    g.state.first = g.state.turn = 0
    return g


def rig(g, hands, discard="10D", draw=None):
    """Force hands / piles for deterministic rule tests."""
    st = g.state
    used = {c for h in hands for c in h} | {discard}
    st.hands = [list(h) for h in hands] + [[] for _ in range(g.n - len(hands))]
    st.discard = [discard]
    st.draw_pile = (draw if draw is not None else [c for c in C.build_deck() if c not in used])
    st.turn, st.phase = 0, "draw"
    return g


def turn(g, seat, act="draw", throw=None):
    """One full turn: draw/take, then discard `throw` (default: first allowed card)."""
    g.apply(seat, act)
    st = g.state
    if throw in st.hands[seat] and throw != st.taken_from_discard:
        card = throw
    elif act == "draw":
        card = st.drawn_card                                  # keep the rigged hand: throw what we just drew
    else:
        card = next(c for c in st.hands[seat] if c != st.taken_from_discard)
    return g.apply(seat, "discard", card)


class DeckAndScoring(unittest.TestCase):
    def test_deck(self):
        d = C.build_deck()
        self.assertEqual((len(d), len(set(d))), (52, 52))
        self.assertEqual({C.rank(c) for c in d}, set(C.RANKS))
        self.assertEqual({C.suit(c) for c in d}, set("HDCS"))

    def test_card_values(self):
        vals = {r: C.value(r + "H") for r in C.RANKS}
        self.assertEqual(vals, {"A": 11, "K": 10, "Q": 10, "J": 10, "10": 10, "9": 9, "8": 8, "7": 7, "6": 6, "5": 5,
                                "4": 4, "3": 3, "2": 2})

    def test_deal_and_piles(self):
        for n in range(2, 8):
            g = ThirtyOneGame.new(list(range(n)), seed=n)
            st = g.state
            self.assertTrue(all(len(h) == 3 for h in st.hands))
            self.assertEqual((len(st.discard), len(st.draw_pile)), (1, 52 - 3 * n - 1))
            every = [c for h in st.hands for c in h] + st.discard + st.draw_pile
            self.assertEqual(sorted(every), sorted(C.build_deck()))
            self.assertEqual(st.phase, "draw")

    def test_same_suit_scoring_examples_from_the_rules(self):
        self.assertEqual(hand_score(["AH", "KH", "QH"]), 31)
        self.assertEqual(hand_score(["AS", "10S", "KS"]), 31)
        self.assertEqual(hand_score(["KD", "QD", "9D"]), 29)
        self.assertTrue(is_31(["AH", "KH", "QH"]))
        self.assertFalse(is_31(["AH", "KH", "9H"]))

    def test_suits_are_never_mixed(self):
        self.assertEqual(hand_score(["AH", "KS", "QD"]), 11)          # best single suit only
        self.assertEqual(hand_score(["AH", "KH", "QS"]), 21)
        self.assertEqual(suit_totals(["AH", "KH", "QS"]), {"H": 21, "S": 10})

    def test_three_of_a_kind_rule_is_configurable(self):
        hand = ["7C", "7D", "7H"]
        self.assertEqual(hand_score(hand, CFG), 30.5)
        self.assertEqual(hand_score(hand, CFG.replace(three_kind_enabled=False)), 7)
        self.assertEqual(hand_score(hand, CFG.replace(three_kind_score=30)), 30)
        self.assertEqual(hand_score(["AC", "AD", "AH"], CFG), 30.5)
        self.assertEqual(hand_score(["KH", "KS", "KD"], CFG), 30.5)
        self.assertEqual(hand_score(["2C", "2D", "2H"], CFG), 30.5)
        self.assertFalse(is_31(hand))                                  # 30.5 is not 31
        self.assertEqual(counting_cards(hand, CFG), hand)
        self.assertEqual(counting_cards(["AH", "KH", "2S"], CFG), ["AH", "KH"])

    def test_best_discard_keeps_the_suit(self):
        score, throw = best_after_discard(["AH", "KH", "QH", "2S"], CFG)
        self.assertEqual((score, throw), (31, "2S"))
        self.assertEqual(best_after_discard(["AH", "KH", "2S", "3D"], CFG, forbidden="2S")[1] in ("2S", "3D"), True)
        self.assertNotEqual(best_after_discard(["AH", "KH", "QH", "2S"], CFG, forbidden="2S")[1], "2S")


class TurnMechanics(unittest.TestCase):
    def test_draw_then_discard(self):
        g = rig(make(3), [["AH", "2C", "3D"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]])
        top = g.state.draw_pile[-1]
        r = g.apply(0, "draw")
        self.assertEqual((r.drawn, g.state.phase, len(g.state.hands[0])), (top, "discard", 4))
        self.assertEqual(g.state.drawn_card, top)
        g.apply(0, "discard", "3D")
        self.assertEqual((len(g.state.hands[0]), g.state.turn, g.state.phase), (3, 1, "draw"))
        self.assertEqual(g.state.discard[-1], "3D")

    def test_take_discard_and_cannot_throw_it_back(self):
        g = rig(make(3), [["AH", "2C", "3D"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]], discard="QH")
        r = g.apply(0, "take")
        self.assertEqual((r.card, g.state.known[0], g.state.discard), ("QH", ["QH"], []))
        with self.assertRaises(IllegalAction):
            g.apply(0, "discard", "QH")
        g.apply(0, "discard", "2C")
        self.assertEqual((g.state.discard, g.state.known[0], g.state.turn), (["2C"], ["QH"], 1))
        g.apply(0 + 1, "take")                                 # next player may take the 2C
        self.assertEqual(g.state.hands[1].count("2C"), 1)

    def test_taking_from_an_empty_discard_pile_is_illegal(self):
        g = rig(make(2), [["AH", "2C", "3D"], ["KS", "5S", "9S"]], discard="QH")
        g.state.discard = []                                   # cannot happen in play (a turn always ends with a discard)
        with self.assertRaises(IllegalAction):
            g.apply(0, "take")
        g.apply(0, "draw")                                     # drawing still works

    def test_errors(self):
        g = rig(make(3), [["AH", "2C", "3D"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]])
        with self.assertRaises(NotYourTurn):
            g.apply(1, "draw")
        with self.assertRaises(WrongPhase):
            g.apply(0, "discard", "2C")
        with self.assertRaises(IllegalAction):
            g.apply(0, "fly")
        g.apply(0, "draw")
        with self.assertRaises(WrongPhase):
            g.apply(0, "draw")
        with self.assertRaises(WrongPhase):
            g.apply(0, "knock")
        with self.assertRaises(CardNotInHand):
            g.apply(0, "discard", "KS")
        with self.assertRaises(UnknownPlayer):
            g.play(999, "draw")

    def test_stale_version_and_game_over(self):
        g = rig(make(2), [["AH", "2C", "3D"], ["KS", "5S", "9S"]])
        v = g.state.version
        g.play(1, "draw", expected_version=v)
        with self.assertRaises(StaleMove):
            g.play(1, "draw", expected_version=v)

    def test_deck_reshuffles_when_empty(self):
        g = rig(make(2), [["AH", "2C", "3D"], ["KS", "5S", "9S"]], discard="QH", draw=[])
        g.state.discard = ["4D", "5D", "6D", "7D", "QH"]
        g.apply(0, "draw")
        self.assertEqual(g.state.discard, ["QH"])
        self.assertEqual((len(g.state.draw_pile), g.state.reshuffles), (3, 1))
        g2 = rig(make(2), [["AH", "2C", "3D"], ["KS", "5S", "9S"]], discard="QH", draw=[])
        g2.state.discard = ["4D", "5D", "6D", "7D", "QH"]
        g2.apply(0, "draw")
        self.assertEqual(g.state.draw_pile, g2.state.draw_pile)            # deterministic

    def test_public_view_and_observation_never_leak(self):
        g = ThirtyOneGame.new([1, 2, 3], seed=3)
        blob = json.dumps(g.public_view())
        for h in g.state.hands:
            for c in h:
                self.assertNotIn(f'"{c}"', blob)
        self.assertNotIn("draw_pile", blob)
        obs = g.observation(0)
        self.assertEqual(obs.hand, g.state.hands[0])
        self.assertFalse(hasattr(obs, "hands"))


class KnockAndInstant31(unittest.TestCase):
    def test_knock_gives_everyone_else_exactly_one_final_turn(self):
        g = rig(make(4), [["AH", "KH", "9H"], ["2C", "3D", "5S"], ["4H", "6C", "8S"], ["7D", "9C", "JS"]])
        g.apply(0, "knock")
        self.assertEqual((g.state.knocker, g.state.final_left, g.state.turn), (0, [1, 2, 3], 1))
        turn(g, 1)
        self.assertEqual((g.state.turn, g.state.final_left), (2, [2, 3]))
        with self.assertRaises(IllegalAction):                 # nobody may knock again
            g.apply(2, "knock")
        turn(g, 2)
        r = turn(g, 3)
        self.assertTrue(r.round_ended)
        self.assertEqual(r.round["reason"], "knock")
        self.assertEqual(g.state.phase, "between")
        self.assertEqual(g.state.round_no, 1)

    def test_knock_can_be_disabled(self):
        g = rig(make(3, knock_enabled=False), [["AH", "KH", "9H"], ["2C", "3D", "5S"], ["4H", "6C", "8S"]])
        with self.assertRaises(IllegalAction):
            g.apply(0, "knock")

    def test_knocker_has_no_further_turn(self):
        g = rig(make(2), [["AH", "KH", "9H"], ["2C", "3D", "5S"]])
        g.apply(0, "knock")
        r = turn(g, 1)
        self.assertTrue(r.round_ended)

    def test_auto_declare_ends_round_immediately(self):
        g = rig(make(3), [["AH", "KH", "2C"], ["4D", "6D", "8S"], ["3C", "5H", "9D"]], draw=["QH"] + ["3S"] * 0)
        g.state.draw_pile = [c for c in C.build_deck() if c not in {"AH", "KH", "2C", "4D", "6D", "8S", "3C", "5H", "9D", "2C"}]
        g.state.draw_pile.remove("QH"); g.state.draw_pile.append("QH")
        g.apply(0, "draw")
        r = g.apply(0, "discard", "2C")
        self.assertTrue(r.round_ended)
        self.assertEqual(r.round["reason"], "declare31")
        self.assertEqual(r.round["scores"][0], 31)
        self.assertEqual(g.state.lives[0], 3)

    def test_manual_declare_when_auto_is_off(self):
        g = rig(make(3, auto_declare_31=False), [["AH", "KH", "2C"], ["4D", "6D", "8S"], ["3C", "5H", "9D"]])
        g.state.draw_pile = [c for c in C.build_deck() if c not in {"AH", "KH", "2C", "4D", "6D", "8S", "3C", "5H", "9D"}]
        g.state.draw_pile.remove("QH"); g.state.draw_pile.append("QH")
        turn(g, 0, "draw", "2C")
        self.assertFalse(g.state.phase == "between")           # 31 held but the round continues (manual declare)
        self.assertEqual(g.state.hands[0], ["AH", "KH", "QH"])
        turn(g, 1)
        turn(g, 2)
        self.assertEqual(g.state.turn, 0)
        r = g.apply(0, "declare")
        self.assertTrue(r.round_ended)
        self.assertEqual(r.round["reason"], "declare31")

    def test_declare_without_31_is_rejected(self):
        g = rig(make(2), [["AH", "KH", "9H"], ["2C", "3D", "5S"]])
        with self.assertRaises(IllegalAction):
            g.apply(0, "declare")
        g.state.hands[0] = ["7C", "7D", "7H"]                  # 30.5 is not 31
        with self.assertRaises(IllegalAction):
            g.apply(0, "declare")

    def test_instant_31_rules(self):
        base = [["AH", "KH", "QH"], ["2C", "3D", "5S"], ["4H", "9C", "8S"]]
        g = rig(make(3), base)                                  # dealt 31, declares at the start of the turn
        r = g.apply(0, "declare")
        self.assertEqual(r.round["losers"], [1])                # lowest_loses: 5 pts (2C+3D=... seat1 best suit 5)
        g = rig(make(3, instant_31_rule="all_others_lose"), base)
        r = g.apply(0, "declare")
        self.assertEqual(sorted(r.round["losers"]), [1, 2])
        self.assertEqual(g.state.lives, [3, 2, 2])


class LivesAndScoring(unittest.TestCase):
    def end_with(self, g, hands, knocker=0):
        rig(g, hands)
        g.apply(knocker, "knock")
        for s in list(g.state.final_left):
            turn(g, s, "draw", None)
        return g.state.last_round

    def test_lowest_scorer_loses_one_life(self):
        g = make(3)
        # fix hands after the final turns by rigging an empty-ish draw pile of harmless cards
        rig(g, [["AH", "KH", "9H"], ["KS", "QS", "9S"], ["2C", "3D", "5S"]], draw=["2D", "2S", "3H", "3S", "4C", "4S"])
        g.apply(0, "knock")
        turn(g, 1, "draw", "2S")
        turn(g, 2, "draw", "3S")
        info = g.state.last_round
        self.assertEqual(info["losers"], [2])
        self.assertEqual(g.state.lives, [3, 3, 2])
        self.assertEqual(info["scores"], [30, 29, hand_score(info["hands"][2])])

    def test_tie_rules(self):
        def run(rule, hands):
            g = make(3, tie_rule=rule)
            rig(g, hands, draw=["2D", "2S", "3H", "3S", "4C", "4S"])
            g.apply(0, "knock")
            turn(g, 1, "draw", "2S"); turn(g, 2, "draw", "3S")
            return g
        tied = [["AH", "KH", "9H"], ["5S", "3S", "2C"], ["5D", "3D", "2D"]]
        # seats 1 and 2 both end with 8 + whatever they draw - force identical by rigging hands post-draw instead:
        g = make(3, tie_rule="all_lose")
        rig(g, [["AH", "KH", "9H"], ["5S", "3S", "2S"], ["5D", "3D", "2D"]], draw=["4H", "4C"])
        g.apply(0, "knock")
        turn(g, 1, "draw", "4H"); turn(g, 2, "draw", "4C")
        self.assertEqual(sorted(g.state.last_round["losers"]), [1, 2])
        g = make(3, tie_rule="none_lose")
        rig(g, [["AH", "KH", "9H"], ["5S", "3S", "2S"], ["5D", "3D", "2D"]], draw=["4H", "4C"])
        g.apply(0, "knock")
        turn(g, 1, "draw", "4H"); turn(g, 2, "draw", "4C")
        self.assertEqual((g.state.last_round["losers"], g.state.lives), ([], [3, 3, 3]))
        # high_card: same total (10) but different cards; the lower high card loses
        g = make(3, tie_rule="high_card")
        rig(g, [["AH", "KH", "9H"], ["5S", "3S", "2S"], ["6D", "4D", "2H"]], draw=["4H", "4C"])
        g.apply(0, "knock")
        turn(g, 1, "draw", "4H"); turn(g, 2, "draw", "4C")
        self.assertEqual(g.state.last_round["scores"][1:], [10, 10])
        self.assertEqual(g.state.last_round["losers"], [1])           # 5,3,2 beats... lower high card = 5 < 6

    def test_everyone_tied_means_nobody_loses(self):
        g = make(2)
        rig(g, [["AH", "KH", "9H"], ["AS", "KS", "9S"]], draw=["2D", "2C"])
        g.apply(0, "knock")
        turn(g, 1, "draw", "2D")
        self.assertEqual((g.state.last_round["losers"], g.state.lives), ([], [3, 3]))

    def test_failed_knock_extra_penalty(self):
        g = make(3, knock_penalty_extra=1)
        rig(g, [["2H", "3H", "4H"], ["KS", "QS", "9S"], ["AC", "KC", "9C"]], draw=["2D", "2S"])
        g.apply(0, "knock")
        turn(g, 1, "draw", "2D"); turn(g, 2, "draw", "2S")
        self.assertEqual(g.state.lives[0], 1)                          # lowest knocker loses 1 + 1
        self.assertEqual(g.state.pstats[0]["knock_losses"], 1)
        self.assertEqual(g.state.pstats[1]["knock_wins"], 0)

    def test_knock_win_is_counted(self):
        g = make(2)
        rig(g, [["AH", "KH", "QH"], ["2C", "3D", "5S"]], draw=["2D"])
        g.state.hands[0] = ["AH", "KH", "9H"]
        g.apply(0, "knock")
        turn(g, 1, "draw", "2D")
        self.assertEqual((g.state.pstats[0]["knock_wins"], g.state.lives), (1, [3, 2]))

    def test_elimination_and_last_player_wins(self):
        g = make(2, start_lives=1)
        rig(g, [["AH", "KH", "9H"], ["2C", "3D", "5S"]], draw=["2D"])
        g.apply(0, "knock")
        r = turn(g, 1, "draw", "2D")
        self.assertTrue(r.finished)
        self.assertEqual((g.state.winner_seats, g.state.active, g.result()["winner_sides"]), ([0], [True, False], [0]))
        self.assertEqual(g.placements(), [1, 2])
        with self.assertRaises(GameOver):
            g.apply(0, "draw")

    def test_knockout_mode_is_sudden_death(self):
        g = ThirtyOneGame.new([1, 2, 3], ThirtyOneConfig(mode="knockout"), seed=1)
        self.assertEqual(g.state.lives, [1, 1, 1])
        rig(g, [["AH", "KH", "9H"], ["KS", "QS", "9S"], ["2C", "3D", "5S"]], draw=["2D", "2S"])
        g.apply(0, "knock")
        turn(g, 1, "draw", "2D"); turn(g, 2, "draw", "2S")
        self.assertEqual(g.state.active, [True, True, False])
        self.assertEqual(g.state.phase, "between")                      # 2 players left -> next round
        g.start_next_round()
        self.assertEqual((g.state.round_no, len(g.state.hands[2])), (2, 0))   # eliminated player gets no cards
        self.assertNotEqual(g.state.turn, 2)

    def test_points_mode_plays_fixed_rounds_and_picks_highest_total(self):
        g = ThirtyOneGame.new([1, 2], ThirtyOneConfig(mode="points", points_rounds=2), seed=2)
        self.assertEqual(g.state.lives, [0, 0])
        for i in range(2):
            rig(g, [["AH", "KH", "9H"], ["2C", "3D", "5S"]], draw=["2D"])
            g.state.turn = 0
            g.apply(0, "knock"); turn(g, 1, "draw", "2D")
            if i == 0:
                self.assertEqual(g.state.phase, "between")
                g.start_next_round()
        self.assertTrue(g.finished)
        self.assertEqual(g.state.totals, [60.0, 10.0])
        self.assertEqual(g.result()["winner_sides"], [0])
        self.assertEqual(g.placements(), [1, 2])

    def test_points_mode_draw_on_equal_totals(self):
        g = ThirtyOneGame.new([1, 2], ThirtyOneConfig(mode="points", points_rounds=1), seed=2)
        rig(g, [["AH", "KH", "9H"], ["AS", "KS", "9S"]], draw=["2D"])
        g.apply(0, "knock"); turn(g, 1, "draw", "2D")
        r = g.result()
        self.assertTrue(r["draw"])
        self.assertEqual(r["winner_sides"], [0, 1])

    def test_dealer_rotates_between_rounds(self):
        g = make(3)
        rig(g, [["AH", "KH", "9H"], ["2C", "3D", "5S"], ["4H", "6C", "8S"]], draw=["2D", "2S"])
        g.apply(0, "knock"); turn(g, 1, "draw", "2D"); turn(g, 2, "draw", "2S")
        first = g.state.first
        g.start_next_round()
        self.assertEqual(g.state.first, (first + 1) % 3)
        self.assertEqual(g.state.round_no, 2)
        with self.assertRaises(WrongPhase):
            g.start_next_round()


class LeavingAndRecovery(unittest.TestCase):
    def test_two_player_forfeit(self):
        g = make(2)
        g.eliminate(0)
        self.assertTrue(g.finished)
        r = g.result()
        self.assertEqual((r["winner_sides"], r["forfeit"], r["placements"]), ([1], True, [2, 1]))

    def test_leaving_player_mid_turn_passes_the_turn_and_returns_cards(self):
        g = rig(make(3), [["AH", "2C", "3D"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]], discard="QH")
        g.apply(0, "draw")
        g.eliminate(0)
        self.assertEqual((g.state.turn, g.state.phase, g.state.hands[0]), (1, "draw", []))
        every = [c for h in g.state.hands for c in h] + g.state.discard + g.state.draw_pile
        self.assertEqual(sorted(every), sorted(C.build_deck()))
        self.assertFalse(g.finished)

    def test_knocker_leaving_cancels_the_knock(self):
        g = rig(make(3), [["AH", "KH", "9H"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]])
        g.apply(0, "knock")
        g.eliminate(0)
        self.assertEqual((g.state.knocker, g.state.final_left), (None, []))

    def test_last_final_turn_player_leaving_finishes_the_round(self):
        g = rig(make(3), [["AH", "KH", "9H"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]])
        g.apply(0, "knock")
        turn(g, 1)
        g.eliminate(2)
        self.assertEqual(g.state.phase == "between" or g.finished, True)

    def test_json_roundtrip_continues_identically(self):
        def play(g, steps, rng):
            for _ in range(steps):
                st = g.state
                if g.finished:
                    break
                if st.phase == "between":
                    g.start_next_round(); continue
                a, arg = choose_action(g.observation(st.turn), "medium", rng)
                g.apply(st.turn, a, arg)
        a = ThirtyOneGame.new([1, 2, 3], seed=77)
        play(a, 40, random.Random(1))
        b = ThirtyOneGame.from_dict(json.loads(json.dumps(a.to_dict())))
        self.assertEqual(a.to_dict(), b.to_dict())
        play(a, 400, random.Random(2)); play(b, 400, random.Random(2))
        self.assertEqual(a.to_dict(), b.to_dict())

    def test_simultaneous_games_are_independent(self):
        games = [ThirtyOneGame.new([1, 2, 3], seed=s) for s in range(15)]
        rngs = [random.Random(s) for s in range(15)]
        def step(g, rng):
            st = g.state
            if st.phase == "between":
                g.start_next_round(); return
            a, arg = choose_action(g.observation(st.turn), "medium", rng)
            g.apply(st.turn, a, arg)
        while not all(g.finished for g in games):
            for g, r in zip(games, rngs):
                if not g.finished:
                    step(g, r)
        for s, g in enumerate(games):
            solo = ThirtyOneGame.new([1, 2, 3], seed=s); r = random.Random(s)
            while not solo.finished:
                step(solo, r)
            self.assertEqual(g.to_dict(), solo.to_dict())


class SkipTurn(unittest.TestCase):
    def test_skip_passes_the_turn_and_changes_no_cards(self):
        g = rig(make(3), [["AH", "KH", "3D"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]])
        before = [list(h) for h in g.state.hands]
        r = g.apply(0, "skip")
        self.assertEqual((g.state.turn, g.state.phase, g.state.hands), (1, "draw", before))
        self.assertEqual(g.state.moves[-1][2], "skip")
        self.assertEqual(r.action, "skip")

    def test_skip_after_draw_returns_the_card_to_the_deck(self):
        g = rig(make(2), [["AH", "KH", "3D"], ["KS", "5S", "9S"]])
        top = g.state.draw_pile[-1]
        n = len(g.state.draw_pile)
        g.apply(0, "draw")
        g.apply(0, "skip")
        self.assertEqual((len(g.state.hands[0]), g.state.draw_pile[-1], len(g.state.draw_pile)), (3, top, n))
        self.assertEqual((g.state.turn, g.state.drawn_card), (1, None))

    def test_skip_after_take_returns_the_card_to_the_discard_pile(self):
        g = rig(make(2), [["AH", "KH", "3D"], ["KS", "5S", "9S"]], discard="QH")
        g.apply(0, "take")
        g.apply(0, "skip")
        self.assertEqual((g.state.discard, g.state.known[0], len(g.state.hands[0])), (["QH"], [], 3))
        self.assertIsNone(g.state.taken_from_discard)

    def test_skipped_final_turn_still_counts_and_can_end_the_round(self):
        g = rig(make(3), [["AH", "KH", "9H"], ["KS", "5S", "9S"], ["4H", "6H", "8H"]])
        g.apply(0, "knock")
        g.apply(1, "skip")
        self.assertEqual((g.state.final_left, g.state.turn), ([2], 2))
        r = g.apply(2, "skip")
        self.assertTrue(r.round_ended)
        self.assertEqual(g.state.phase, "between")

    def test_skip_is_not_available_to_the_wrong_player_or_between_rounds(self):
        g = rig(make(2), [["AH", "KH", "9H"], ["KS", "5S", "9S"]])
        with self.assertRaises(NotYourTurn):
            g.apply(1, "skip")
        g.apply(0, "knock"); g.apply(1, "skip")
        with self.assertRaises(WrongPhase):
            g.apply(0, "skip")


class ConfigTests(unittest.TestCase):
    def test_validation_and_helpers(self):
        for bad in (dict(min_players=1), dict(max_players=8), dict(min_players=5, max_players=3), dict(mode="x"),
                    dict(start_lives=0), dict(tie_rule="x"), dict(instant_31_rule="x"), dict(turn_timeout=1)):
            with self.assertRaises(ValueError):
                ThirtyOneConfig(**bad)
        self.assertEqual(ThirtyOneConfig.from_dict({"nonsense": 1, "start_lives": 4}).start_lives, 4)
        self.assertEqual(CFG.replace(mode="knockout").lives_at_start, 1)
        self.assertEqual(CFG.replace(mode="points").lives_at_start, 0)
        with self.assertRaises(ValueError):
            ThirtyOneGame.new([1], CFG)
        with self.assertRaises(ValueError):
            ThirtyOneGame.new([1, 1], CFG)
        with self.assertRaises(ValueError):
            ThirtyOneGame.new(list(range(8)), CFG)


class FullGamesAndAI(unittest.TestCase):
    def play_full(self, n, mode, levels, seed):
        g = ThirtyOneGame.new(list(range(1, n + 1)), ThirtyOneConfig(mode=mode, points_rounds=3), seed)
        rng = random.Random(seed)
        steps = 0
        while not g.finished:
            st = g.state
            if st.phase == "between":
                g.start_next_round(); continue
            seat = st.turn
            act, arg = choose_action(g.observation(seat), levels[seat % len(levels)], rng)
            if st.phase == "discard":
                self.assertIn(arg, st.hands[seat]); self.assertNotEqual(arg, st.taken_from_discard)
            g.apply(seat, act, arg)
            every = [c for h in st.hands for c in h] + st.discard + st.draw_pile
            if st.phase != "between":
                self.assertEqual(len(every), 52)
            steps += 1
            self.assertLess(steps, 20000)
        return g

    def test_games_complete_for_every_size_and_mode(self):
        for n in range(2, 8):
            for mode in ("lives", "knockout", "points"):
                g = self.play_full(n, mode, ["medium"], n * 3)
                r = g.result()
                self.assertTrue(r["winner_sides"])
                self.assertEqual(sorted(r["placements"])[0], 1)

    def test_ai_levels_are_always_legal(self):
        for level in DIFFICULTIES:
            for n in (2, 4):
                self.play_full(n, "lives", [level], 11 + n)

    def test_mixed_levels(self):
        self.play_full(4, "lives", list(DIFFICULTIES), 5)

    def test_ai_declares_31_and_takes_the_missing_card(self):
        g = rig(make(2), [["AH", "KH", "QH"], ["2C", "3D", "5S"]])
        self.assertEqual(choose_action(g.observation(0), "easy")[0], "declare")
        g = rig(make(2), [["AH", "KH", "2C"], ["2D", "3D", "5S"]], discard="QH")
        self.assertEqual(choose_action(g.observation(0), "medium")[0], "take")
        g.apply(0, "take")
        self.assertEqual(choose_action(g.observation(0), "medium"), ("discard", "2C"))

    def test_medium_beats_easy(self):
        wins = 0
        for s in range(20):
            g = ThirtyOneGame.new([1, 2], seed=s)
            rng = random.Random(s)
            lv = ["medium", "easy"] if s % 2 == 0 else ["easy", "medium"]
            while not g.finished:
                st = g.state
                if st.phase == "between":
                    g.start_next_round(); continue
                a, arg = choose_action(g.observation(st.turn), lv[st.turn], rng)
                g.apply(st.turn, a, arg)
            wins += lv[g.state.winner_seats[0]] == "medium"
        self.assertGreaterEqual(wins, 16)

    def test_ai_only_uses_visible_information(self):
        g = ThirtyOneGame.new([1, 2, 3], seed=4)
        obs = g.observation(0)
        unseen = set(unseen_cards(obs))
        self.assertTrue(set(g.state.hands[1]) <= unseen)         # opponents' cards look 'unseen' to me
        self.assertFalse(set(obs.hand) & unseen)
        self.assertFalse(set(obs.discard_pile) & unseen)


if __name__ == "__main__":
    unittest.main()
