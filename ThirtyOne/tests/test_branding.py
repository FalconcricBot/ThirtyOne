"""The bot is called Thirty One (@Deck31Bot). 'Briscola' stays only as the name of the game."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
OLD = re.compile(r"briscola\s*arena|briscolaarena|trivo", re.I)


class Branding(unittest.TestCase):
    def test_no_old_bot_name_left_in_the_code(self):
        offenders = []
        for sub in ("ui", "handlers", "keyboards", "services", "utils", "game", "database"):
            for f in (ROOT / sub).rglob("*.py"):
                if OLD.search(f.read_text()):
                    offenders.append(str(f.relative_to(ROOT)))
        for f in ("main.py", "config.py", "README.md", ".env.example"):
            if OLD.search((ROOT / f).read_text()):
                offenders.append(f)
        self.assertEqual(offenders, [])

    def test_default_username_and_brand_texts(self):
        import os
        from tests import fake_telegram
        fake_telegram.install()
        from ui import texts
        if "BOT_USERNAME" not in os.environ:
            from config import Settings
            self.assertEqual(Settings().bot_username, "Deck31Bot")
        menu = texts.main_menu_text({"display_name": "A", "xp": 0, "coins": 1})
        self.assertIn("THIRTY ONE", menu)
        self.assertNotIn("BRISCOLA ARENA", menu)

    def test_player_id_prefix(self):
        from tests import fake_telegram
        fake_telegram.install()
        from datetime import datetime
        from ui import texts
        p = {"display_name": "A", "username": None, "player_no": 10042, "created_at": datetime(2026, 1, 1), "xp": 0, "coins": 0,
             "matches": 0, "wins": 0, "losses": 0, "draws": 0, "win_streak": 0, "best_streak": 0, "total_points": 0,
             "highest_score": 0, "tournament_wins": 0}
        self.assertIn("#10042", texts.profile_text(p, []))


if __name__ == "__main__":
    unittest.main()
