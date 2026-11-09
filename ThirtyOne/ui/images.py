"""Pillow renderers: hand, live table, profile card. Neon pink / violet / black theme.

All functions return PNG bytes (BytesIO) ready for Telegram send_photo / InputMediaPhoto.
Rendering is CPU work - call via asyncio.to_thread() from handlers.
"""
from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from game.cards import card as get_card

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
BOLD, REG = FONT_DIR / "DejaVuSans-Bold.ttf", FONT_DIR / "DejaVuSans.ttf"

PINK, VIOLET, PURPLE = (255, 45, 149), (138, 43, 226), (88, 28, 160)
WHITE, INK, GOLD = (250, 250, 255), (22, 14, 40), (255, 205, 80)
RED_SUIT, BLACK_SUIT = (214, 30, 70), (28, 24, 48)
CARD_W, CARD_H = 180, 260
SUIT_SYM = {"H": "♥", "D": "♦", "C": "♣", "S": "♠"}
SUIT_NAME = {"H": "HEARTS", "D": "DIAMONDS", "C": "CLUBS", "S": "SPADES"}
POINTS = {"A": 11, "3": 10, "K": 4, "Q": 3, "J": 2}


@lru_cache(maxsize=64)
def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD if bold else REG), size)


@lru_cache(maxsize=4096)
def _glyph_sig(ch: str) -> bytes:
    im = Image.new("L", (48, 48), 0)
    ImageDraw.Draw(im).text((4, 4), ch, font=font(32), fill=255)
    return im.tobytes()


def safe_text(text: str, size: int = 24, fallback: str = "Player") -> str:
    """Drop glyphs DejaVu cannot draw (emoji, Indic scripts...) so we never render tofu boxes."""
    notdef = _glyph_sig("\U0010ffff")
    def ok(ch: str) -> bool:
        cp = ord(ch)
        if 0x0590 <= cp < 0x1E00:      # Hebrew/Arabic/Indic/etc: partial coverage renders badly
            return False
        return ch.isspace() or _glyph_sig(ch) != notdef
    out = "".join(ch for ch in text if ok(ch))
    out = " ".join(out.split())
    return out or fallback


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, size: int, bold=True) -> ImageFont.FreeTypeFont:
    while size > 10 and draw.textlength(text, font=font(size, bold)) > max_w:
        size -= 1
    return font(size, bold)


def _center(draw, xy, text, fnt, fill):
    draw.text(xy, text, font=fnt, fill=fill, anchor="mm")


def background(w: int, h: int) -> Image.Image:
    g = Image.linear_gradient("L").resize((w, h))
    img = ImageOps.colorize(g, black=(8, 4, 22), white=(46, 12, 84)).convert("RGBA")
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd0 = ImageDraw.Draw(grid)
    for x in range(0, w, 60):                                  # faint grid
        gd0.line([(x, 0), (x, h)], fill=(255, 255, 255, 12))
    for y in range(0, h, 60):
        gd0.line([(0, y), (w, y)], fill=(255, 255, 255, 12))
    img.alpha_composite(grid)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rectangle([6, 6, w - 7, h - 7], outline=PINK + (255,), width=4)
    gd.rectangle([16, 16, w - 17, h - 17], outline=VIOLET + (255,), width=2)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(5)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([5, 5, w - 6, h - 6], 18, outline=PINK, width=2)
    return img


def _glow(img: Image.Image, box, color, radius=14, grow=8):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow], 24,
                                            fill=color + (230,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius)))


@lru_cache(maxsize=128)
def _card_face(code: str, trump: bool = False) -> Image.Image:
    c = get_card(code)
    suit = c.suit.value
    col = RED_SUIT if suit in "HD" else BLACK_SUIT
    im = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], 16, fill=(247, 246, 252),
                        outline=GOLD if trump else VIOLET, width=5 if trump else 3)
    d.rounded_rectangle([9, 9, CARD_W - 10, CARD_H - 10], 11, outline=(225, 218, 240), width=1)
    r = c.rank
    d.text((16, 12), r, font=font(40), fill=col)
    d.text((16, 56), SUIT_SYM[suit], font=font(30), fill=col)
    d.text((CARD_W - 16, CARD_H - 12), r, font=font(40), fill=col, anchor="rs")
    d.text((CARD_W - 16, CARD_H - 56), SUIT_SYM[suit], font=font(30), fill=col, anchor="rs")
    if r in "KQJ":                                             # face-card panel
        d.rounded_rectangle([46, 62, CARD_W - 47, 150], 12, fill=PURPLE)
        d.rounded_rectangle([50, 66, CARD_W - 51, 146], 9, outline=PINK, width=2)
        _center(d, (CARD_W // 2, 106), r, font(64), WHITE)
        _center(d, (CARD_W // 2, 186), SUIT_SYM[suit], font(62), col)
    else:
        _center(d, (CARD_W // 2, CARD_H // 2 + 2), SUIT_SYM[suit], font(104 if r in "A3" else 88), col)
    if r in POINTS:                                            # points badge
        d.rounded_rectangle([CARD_W // 2 - 26, CARD_H - 40, CARD_W // 2 + 26, CARD_H - 14], 10, fill=INK)
        _center(d, (CARD_W // 2, CARD_H - 27), f"{POINTS[r]} pt", font(15), GOLD)
    return im


@lru_cache(maxsize=1)
def _card_back() -> Image.Image:
    im = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], 16, fill=(30, 10, 60), outline=PINK, width=3)
    for i in range(-CARD_H, CARD_W + CARD_H, 28):
        d.line([(i, 0), (i + CARD_H, CARD_H)], fill=(110, 40, 190), width=2)
        d.line([(i + CARD_H, 0), (i, CARD_H)], fill=(110, 40, 190), width=2)
    d.rounded_rectangle([40, 90, CARD_W - 41, 170], 14, fill=INK, outline=VIOLET, width=2)
    _center(d, (CARD_W // 2, 130), "31", font(46), PINK)
    return im


def _paste_card(img, code, x, y, scale=1.0, trump=False, glow=None, back=False):
    face = _card_back() if back else _card_face(code, trump)
    if scale != 1.0:
        face = face.resize((int(CARD_W * scale), int(CARD_H * scale)), Image.LANCZOS)
    if glow or trump:
        _glow(img, (x, y, x + face.width, y + face.height), glow or GOLD, radius=10, grow=4)
    img.alpha_composite(face, (x, y))
    return face.size


def _png(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    buf.seek(0)
    buf.name = "briscola.png"
    return buf


def _title(img, text, sub=None):
    d = ImageDraw.Draw(img)
    d.text((img.width // 2, 34), text, font=font(30), fill=PINK, anchor="mm")
    if sub:
        d.text((img.width // 2, 64), sub, font=font(16, False), fill=(200, 190, 230), anchor="mm")


# ------------------------------------------------------------------ hand
def render_hand(hand: list[str], trump_suit: str, trump_card: str | None, stock: int,
                score: int, your_turn: bool) -> io.BytesIO:
    n = max(len(hand), 1)
    w, h = 760, 470
    img = background(w, h)
    _title(img, "YOUR HAND", "YOUR TURN — TAP A CARD BELOW" if your_turn else "WAIT FOR YOUR TURN")
    total = n * CARD_W + (n - 1) * 26
    x = (w - total) // 2
    for code in hand:
        _paste_card(img, code, x, 96, trump=get_card(code).suit.value == trump_suit)
        x += CARD_W + 26
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 384, w - 40, 440], 14, fill=(20, 8, 40), outline=VIOLET, width=2)
    col = RED_SUIT if trump_suit in "HD" else WHITE
    d.text((70, 412), f"BRISCOLA  {SUIT_SYM[trump_suit]}", font=font(24), fill=col if trump_suit in "HD" else WHITE, anchor="lm")
    d.text((w // 2 + 20, 412), f"DECK {stock}", font=font(22), fill=WHITE, anchor="mm")
    d.text((w - 70, 412), f"SCORE {score}", font=font(24), fill=GOLD, anchor="rm")
    return _png(img)


# ------------------------------------------------------------------ table
def render_table(*, room: str, mode_label: str, names: list[str], trick: list[tuple[int, str]],
                 turn: int | None, trump_suit: str, trump_card: str | None, stock: int,
                 side_scores: list[int], team_mode: bool, last_trick: dict | None = None,
                 winner_text: str | None = None, deadline_text: str | None = None) -> io.BytesIO:
    n = len(names)
    w, h = 1000, 620
    img = background(w, h)
    _title(img, "BRISCOLA  •  LIVE MATCH", f"ROOM {room}   •   {mode_label}")
    d = ImageDraw.Draw(img)
    names = [safe_text(x, 20, f"Player {i + 1}") for i, x in enumerate(names)]

    # left column: deck + trump
    d.text((110, 112), "DECK", font=font(16), fill=(200, 190, 230), anchor="mm")
    if stock > 0:
        if trump_card:
            _paste_card(img, trump_card, 40, 150, scale=0.62, trump=True)
            for k in range(min(3, max(stock - 1, 0))):
                _paste_card(img, "", 40 + 38 + k * 6, 150 + 20 + k * 4, scale=0.62, back=True)
        else:
            for k in range(min(3, stock)):
                _paste_card(img, "", 50 + k * 6, 150 + k * 4, scale=0.62, back=True)
    else:
        d.rounded_rectangle([40, 150, 152, 311], 10, outline=(120, 100, 160), width=2)
    d.text((110, 346), f"{stock} cards", font=font(18), fill=WHITE, anchor="mm")
    d.text((110, 374), f"BRISCOLA {SUIT_SYM[trump_suit]}", font=font(20), fill=GOLD, anchor="mm")
    d.text((110, 398), SUIT_NAME[trump_suit], font=font(13, False), fill=(200, 190, 230), anchor="mm")

    # centre: current (or last) trick
    shown, label = list(trick), "CURRENT TRICK"
    if not trick and last_trick:
        shown, label = [(s, c) for s, c in last_trick["plays"]], "LAST TRICK"
    d.text((560, 112), label, font=font(16), fill=(200, 190, 230), anchor="mm")
    slot_w = 140
    gap = 18
    total = n * slot_w + (n - 1) * gap
    x0 = 560 - total // 2
    played = {s: c for s, c in shown}
    for seat in range(n):
        x = x0 + seat * (slot_w + gap)
        if seat in played:
            win = bool(last_trick) and not trick and last_trick["winner"] == seat
            _paste_card(img, played[seat], x, 140, scale=slot_w / CARD_W, glow=PINK if win else None)
        else:
            d.rounded_rectangle([x, 140, x + slot_w, 140 + int(CARD_H * slot_w / CARD_W)], 12,
                                outline=(120, 100, 170), width=2)
            _center(d, (x + slot_w // 2, 140 + int(CARD_H * slot_w / CARD_W) // 2), "?", font(40), (120, 100, 170))
        mark = "▶ " if (turn == seat and not trick == [] or turn == seat) and not winner_text else ""
        col = PINK if turn == seat and not winner_text else WHITE
        d.text((x + slot_w // 2, 140 + int(CARD_H * slot_w / CARD_W) + 24), mark + names[seat],
               font=_fit(d, mark + names[seat], slot_w + gap - 4, 17), fill=col, anchor="mm")

    # right: scoreboard
    d.rounded_rectangle([800, 100, 970, 330], 14, fill=(20, 8, 40), outline=VIOLET, width=2)
    d.text((885, 124), "SCORE", font=font(18), fill=PINK, anchor="mm")
    if team_mode:
        rows = [(f"{names[0].split()[0][:8]}+{names[2].split()[0][:8]}", side_scores[0]),
                (f"{names[1].split()[0][:8]}+{names[3].split()[0][:8]}", side_scores[1])]
    else:
        rows = [(names[i], side_scores[i]) for i in range(n)]
    for i, (nm, sc) in enumerate(rows):
        y = 170 + i * 70
        d.text((815, y), nm, font=_fit(d, nm, 150, 15), fill=WHITE, anchor="lm")
        d.text((815, y + 28), str(sc), font=font(32), fill=GOLD, anchor="lm")

    # bottom status strip
    d.rounded_rectangle([40, 470, w - 40, 580], 16, fill=(20, 8, 40), outline=PINK if winner_text else VIOLET, width=3)
    if winner_text:
        _center(d, (w // 2, 510), "WINNER ★" if "DRAW" not in winner_text.upper() else "DRAW", font(22), GOLD)
        _center(d, (w // 2, 546), safe_text(winner_text, 30), _fit(d, winner_text, w - 120, 30), WHITE)
    else:
        if last_trick and not trick:
            t = f"{names[last_trick['winner']]} won the last trick  +{last_trick['points']} pts"
            _center(d, (w // 2, 510), safe_text(t), _fit(d, t, w - 120, 24), WHITE)
        elif trick:
            _center(d, (w // 2, 510), "Waiting for next player...", font(24), WHITE)
        else:
            _center(d, (w // 2, 510), "New trick", font(24), WHITE)
        t2 = f"Turn: {names[turn]}" + (f"   •   {deadline_text}" if deadline_text else "")
        _center(d, (w // 2, 548), t2, _fit(d, t2, w - 120, 22), PINK)
    return _png(img)


# ------------------------------------------------------------------ profile
def _avatar(avatar: bytes | None, name: str, size: int) -> Image.Image:
    if avatar:
        try:
            im = Image.open(io.BytesIO(avatar)).convert("RGBA")
            im = ImageOps.fit(im, (size, size), Image.LANCZOS)
        except Exception:
            im = None
    else:
        im = None
    if im is None:
        g = Image.linear_gradient("L").resize((size, size))
        im = ImageOps.colorize(g, black=VIOLET, white=PINK).convert("RGBA")
        ImageDraw.Draw(im).text((size // 2, size // 2), safe_text(name, 60, "?")[:1].upper(),
                                font=font(size // 2), fill=WHITE, anchor="mm")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def render_profile(*, name: str, username: str | None, player_no: int, rank_name: str, level: int,
                   xp: int, xp_floor: int, xp_next: int | None, stats: dict, avatar: bytes | None = None) -> io.BytesIO:
    w, h = 900, 500
    img = background(w, h)
    _title(img, "THIRTY ONE  •  PLAYER CARD")
    av = _avatar(avatar, name, 170)
    _glow(img, (50, 100, 220, 270), PINK, radius=12, grow=4)
    img.alpha_composite(av, (50, 100))
    d = ImageDraw.Draw(img)
    nm = safe_text(name, 36)
    d.text((260, 125), nm, font=_fit(d, nm, 600, 38), fill=WHITE, anchor="lm")
    d.text((260, 165), (f"@{username}  •  " if username else "") + f"ID #{player_no}", font=font(18, False),
           fill=(200, 190, 230), anchor="lm")
    d.rounded_rectangle([260, 190, 470, 232], 20, fill=PURPLE, outline=PINK, width=2)
    _center(d, (365, 211), rank_name.upper(), font(20), WHITE)
    d.text((490, 211), f"LEVEL {level}", font=font(24), fill=GOLD, anchor="lm")
    bar_x0, bar_x1, bar_y = 260, 850, 255
    d.rounded_rectangle([bar_x0, bar_y, bar_x1, bar_y + 18], 9, fill=(20, 8, 40), outline=VIOLET, width=2)
    frac = 1.0 if xp_next is None else max(0.0, min(1.0, (xp - xp_floor) / max(xp_next - xp_floor, 1)))
    if frac > 0:
        d.rounded_rectangle([bar_x0, bar_y, bar_x0 + int((bar_x1 - bar_x0) * frac), bar_y + 18], 9, fill=PINK)
    d.text((bar_x0, bar_y + 38), f"XP {xp:,}" + (f" / {xp_next:,}" if xp_next else "  (MAX)"),
           font=font(16, False), fill=WHITE, anchor="lm")
    cells = [("MATCHES", stats["matches"]), ("WINS", stats["wins"]), ("LOSSES", stats["losses"]),
             ("DRAWS", stats["draws"]), ("WIN %", f"{stats['win_pct']:.0f}%"), ("STREAK", stats["streak"]),
             ("BEST SCORE", stats["highest"]), ("POINTS", stats["points"])]
    for i, (lab, val) in enumerate(cells):
        cx, cy = 50 + (i % 4) * 210, 320 + (i // 4) * 80
        d.rounded_rectangle([cx, cy, cx + 195, cy + 68], 12, fill=(20, 8, 40), outline=VIOLET, width=2)
        d.text((cx + 97, cy + 20), lab, font=font(13), fill=(200, 190, 230), anchor="mm")
        d.text((cx + 97, cy + 46), str(val), font=font(26), fill=GOLD, anchor="mm")
    return _png(img)
