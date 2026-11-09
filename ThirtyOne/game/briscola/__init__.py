"""Briscola engine namespace. The modules still live in `game/` (unchanged, so nothing that already works is
moved or rewritten); this package re-exports them so both games read symmetrically:

    from game.briscola import BriscolaGame, choose_card      # Briscola
    from game.thirty_one import ThirtyOneGame                 # 31 Card Game
"""
from game.ai import DIFFICULTIES, choose_card          # noqa: F401
from game.cards import Card, Suit, card                # noqa: F401
from game.engine import BriscolaGame                    # noqa: F401
from game.rules import DEFAULT_RULES, RulesConfig, trick_winner  # noqa: F401
from game.scoring import outcome, pile_points           # noqa: F401
