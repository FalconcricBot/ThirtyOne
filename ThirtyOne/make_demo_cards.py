"""Render demo profile cards with placeholder avatars: python make_demo_cards.py"""
import io, random, sys
from PIL import Image, ImageDraw, ImageFilter
from ui.profile_cards import render_profile_card


def fake_photo(c1, c2, skin, hair, seed):
    """Stand-in for a Telegram profile photo (the bot downloads the real one at runtime)."""
    rnd = random.Random(seed)
    s = 640
    bg = Image.linear_gradient("L").resize((s, s))
    from PIL import ImageOps
    im = ImageOps.colorize(bg, black=c1, white=c2).convert("RGB")
    d = ImageDraw.Draw(im)
    d.ellipse([90, 430, 550, 900], fill=(40, 60, 110))                      # shoulders
    d.rectangle([280, 360, 360, 470], fill=skin)                              # neck
    d.ellipse([205, 120, 435, 420], fill=hair)                                # hair back
    d.ellipse([220, 160, 420, 400], fill=skin)                                # face
    d.pieslice([205, 110, 435, 330], 180, 360, fill=hair)                     # hair top
    d.ellipse([268, 260, 292, 280], fill=(30, 30, 40)); d.ellipse([348, 260, 372, 280], fill=(30, 30, 40))
    d.arc([280, 300, 360, 360], 20, 160, fill=(120, 50, 50), width=5)
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    px = im.load()
    for _ in range(9000):                                                     # light grain
        x, y = rnd.randrange(s), rnd.randrange(s); r, g, b = px[x, y]; n = rnd.randint(-10, 10)
        px[x, y] = (max(0, min(255, r + n)),) * 1 + (max(0, min(255, g + n)), max(0, min(255, b + n)))
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=90); return buf.getvalue()


DEMOS = [
    ("face", dict(name="Nihar Sharma", username="nihar_bs", player_no=10042, rank_name="Diamond", level=8, xp=5200,
                  xp_floor=3500, xp_next=7000, stats=dict(matches=120, wins=70, win_pct=58.3, streak=3, highest=98)),
     ((20, 90, 120), (120, 200, 190), (224, 172, 140), (30, 25, 25), 1)),
    ("arena", dict(name="निहार 🔥 Sharma", username="nihar_gamer", player_no=10077, rank_name="Grandmaster", level=22, xp=21500,
                   xp_floor=20000, xp_next=None, stats=dict(matches=842, wins=611, win_pct=72.6, streak=9, highest=117)),
     ((110, 30, 120), (255, 120, 160), (198, 140, 110), (60, 30, 20), 2)),
    ("vip", dict(name="Aisha ✨ अंजलि 💎", username="aisha_cards", player_no=10133, rank_name="Gold", level=6, xp=2100,
                 xp_floor=1500, xp_next=3500, stats=dict(matches=64, wins=31, win_pct=48.4, streak=1, highest=89)),
     ((30, 40, 100), (140, 120, 230), (240, 195, 165), (90, 40, 30), 3)),
]
if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    for tpl, data, ph in DEMOS:
        buf = render_profile_card(tpl, avatar=fake_photo(*ph), **data)
        open(f"{out}/profile_{tpl}.png", "wb").write(buf.getvalue())
        print("wrote", tpl)
