import io
import unittest

from tests import fake_telegram

fake_telegram.install()

from PIL import Image, ImageDraw                                     # noqa: E402

from keyboards.profile_keyboard import settings_kb                   # noqa: E402
from ui import profile_cards as pc                                    # noqa: E402

STATS = dict(matches=10, wins=6, win_pct=60.0, streak=2, highest=88, losses=3, draws=1, points=500)


def card(tpl, name="Nihar", username="nihar", avatar=None, rank="Gold", xp_next=3500):
    return pc.render_profile_card(tpl, name=name, username=username, player_no=10001, rank_name=rank, level=5, xp=2000,
                                  xp_floor=1500, xp_next=xp_next, stats=STATS, avatar=avatar)


def jpeg() -> bytes:
    im = Image.new("RGB", (300, 400), (30, 120, 160))
    ImageDraw.Draw(im).ellipse([80, 60, 220, 220], fill=(230, 180, 150))
    b = io.BytesIO(); im.save(b, "JPEG"); return b.getvalue()


class ProfileCardTests(unittest.TestCase):
    def test_all_templates_render_png_with_and_without_photo(self):
        for tpl in ("face", "arena", "vip"):
            for av in (None, jpeg(), b"not an image"):                    # bad bytes fall back to the monogram
                buf = card(tpl, avatar=av)
                self.assertEqual(buf.getvalue()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(Image.open(card("face")).size, (680, 940))
        self.assertEqual(Image.open(card("arena")).size, (1000, 560))
        self.assertEqual(Image.open(card("vip")).size, (1000, 520))

    def test_unusual_names_never_crash(self):
        names = ["निहार 🔥 Sharma", "Aisha ✨ अंजलि 💎", "👨‍👩‍👧 family", "🇮🇳 India", "Ünïcödé Ñame", "Иван Петров",
                 "x" * 100, "Very Long Display Name That Keeps Going And Going Forever 🙂", "   ", "", "\u200b", "عربي"]
        for tpl in ("face", "arena", "vip"):
            for n in names:
                card(tpl, name=n, username="u" * 32)
                card(tpl, name=n, username=None, rank="Grandmaster", xp_next=None)

    def test_exact_text_is_preserved(self):
        runs = pc._runs("निहार 🔥 Sharma")
        self.assertEqual([k for k, _ in runs if k == "emoji"], ["emoji"])
        joined = "".join(s for _, s in runs)
        self.assertEqual(joined.replace(" ", ""), "निहार🔥Sharma")            # nothing dropped, order kept
        self.assertGreater(pc.rich_width("Hello", 40), pc.rich_width("Hi", 40))
        self.assertEqual(pc._runs("   "), [])

    def test_long_name_is_fitted(self):
        im = Image.new("RGBA", (800, 100))
        used = pc.draw_rich(im, (10, 50), "W" * 60, 60, (255, 255, 255, 255), "l", max_width=300, min_size=20)
        self.assertLessEqual(used, 60)
        right_edge = im.getbbox()[2]
        self.assertLessEqual(right_edge, 10 + 300 + 6)                       # shrunk / trimmed to the box

    def test_owner_templates_render_with_hindi_emoji_and_missing_photo(self):
        stats = {**STATS, "wins31": 12}
        for tpl, size in (("owner", (1000, 580)), ("owner_card", (680, 940))):
            for av in (None, jpeg(), b"junk"):
                buf = pc.render_profile_card(tpl, name="निहार 🔥 Sharma", username="sinoex", player_no=10001, rank_name="Grandmaster",
                                             level=22, xp=21500, xp_floor=20000, xp_next=None, stats=stats, avatar=av)
                self.assertEqual(Image.open(buf).size, size)
            for n in ("x" * 100, "👑👑👑", "   ", "Аня 🇮🇳", "A"):
                pc.render_profile_card(tpl, name=n, username=None, player_no=7, rank_name="Gold", level=1, xp=0, xp_floor=0,
                                       xp_next=500, stats={**STATS, "wins31": 0}, avatar=None)
        pc.render_profile_card("owner", name="N", username="u" * 32, player_no=1, rank_name="x", level=1, xp=10, xp_floor=0,
                               xp_next=100, stats=STATS, avatar=None)           # works without wins31 too

    def test_gold_text_keeps_emoji_colours(self):
        im = Image.new("RGBA", (500, 120), (0, 0, 0, 255))
        pc.gold_text(im, (20, 60), "Aa 🔥", 60, "l")
        px = [im.getpixel((x, y)) for x in range(0, 500, 3) for y in range(0, 120, 3)]
        golden = [p for p in px if p[0] > 180 and 120 < p[1] < 235 and p[2] < 150]
        self.assertTrue(golden)                                                  # lettering is gold, not white
        self.assertFalse(any(p[0] > 250 and p[1] > 250 and p[2] > 250 for p in px))   # no pure-white halo left behind

    def test_rank_maps_to_card_and_suit_is_stable(self):
        self.assertEqual(pc.RANK_CARD["Grandmaster"], "A")
        self.assertEqual(pc._suit_for(10001), pc._suit_for(10001))
        self.assertEqual({pc._suit_for(i) for i in range(4)}, set("HDCS"))


class OwnerAccessTests(unittest.TestCase):
    def test_only_owners_can_use_the_owner_designs(self):
        from handlers import profile as ph
        from unittest import mock
        from types import SimpleNamespace
        fake = SimpleNamespace(owners={1})
        with mock.patch.object(ph, "cfg", fake):
            self.assertEqual(ph.allowed_templates(1), ("face", "arena", "vip", "owner", "owner_card"))
            self.assertEqual(ph.allowed_templates(2), ("face", "arena", "vip"))
            self.assertEqual(ph.effective_template(1, "face"), "owner")              # default for the owner
            self.assertEqual(ph.effective_template(1, "owner_card"), "owner_card")
            self.assertEqual(ph.effective_template(1, "vip"), "vip")                 # owner may still pick another style
            self.assertEqual(ph.effective_template(2, "owner"), "face")              # forged / stale value is ignored
            self.assertEqual(ph.effective_template(2, "arena"), "arena")

    def test_owner_buttons_only_for_the_owner(self):
        p = dict(hand_images=True, table_images=True, notify=True, profile_template="owner")
        plain = [b.callback_data for r in settings_kb(p).inline_keyboard for b in r]
        owner = [b.callback_data for r in settings_kb(p, True).inline_keyboard for b in r]
        self.assertNotIn("s:tpl:owner", plain)
        self.assertIn("s:tpl:owner", owner)
        self.assertIn("s:tpl:owner_card", owner)
        self.assertTrue(next(b for r in settings_kb(p, True).inline_keyboard for b in r if b.callback_data == "s:tpl:owner").text.startswith("✅"))

    def test_owner_ids_setting(self):
        from config import Settings
        self.assertEqual(Settings(owner_ids={5}, admin_ids={1, 2}).owners, {5})
        self.assertEqual(Settings(owner_ids=set(), admin_ids={9}).owners, {9})       # single admin = owner
        self.assertEqual(Settings(owner_ids=set(), admin_ids={1, 2}).owners, set())


class SettingsKeyboardTests(unittest.TestCase):
    def test_template_buttons_and_selection_mark(self):
        p = dict(hand_images=True, table_images=True, notify=True, profile_template="arena")
        rows = settings_kb(p).inline_keyboard
        styles = rows[0]
        self.assertEqual([b.callback_data for b in styles], ["s:tpl:face", "s:tpl:arena", "s:tpl:vip"])
        self.assertTrue(styles[1].text.startswith("✅"))
        self.assertFalse(styles[0].text.startswith("✅"))
        self.assertEqual(rows[1][0].callback_data, "s:preview")
        self.assertTrue(all(len(b.callback_data.encode()) <= 64 for r in rows for b in r if b.callback_data))
        # old players without the key default to 'face'
        self.assertTrue(settings_kb(dict(hand_images=1, table_images=1, notify=1)).inline_keyboard[0][0].text.startswith("✅"))


if __name__ == "__main__":
    unittest.main()
