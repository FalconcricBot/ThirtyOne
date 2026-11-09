"""Game-style profile cards that show the user's real Telegram photo, name and @username
exactly as they appear in Telegram (Latin, Hindi/Devanagari, Cyrillic, colour emoji...).

Templates: "face" (portrait playing card), "arena" (landscape, fan of cards), "vip" (casino pass).
All functions return PNG BytesIO; call via asyncio.to_thread()."""
from __future__ import annotations

import io
import math
import random
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from ui.images import (CARD_H, CARD_W, GOLD, INK, PINK, PURPLE, SUIT_SYM, VIOLET, WHITE, RED_SUIT, BLACK_SUIT,
                       _card_face, _glow, background, font as dj_font)

FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
SYS = [Path("/usr/share/fonts/truetype"), Path("C:/Windows/Fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts")]
INK2, CREAM, LAVENDER = (34, 20, 62), (249, 246, 252), (200, 190, 235)
RANK_CARD = {"Bronze": "4", "Silver": "7", "Gold": "J", "Platinum": "Q", "Diamond": "K", "Master": "3", "Grandmaster": "A"}


def _find(*names: str) -> str | None:
    for n in names:
        if (FONTS / n).exists():
            return str(FONTS / n)
    for root in SYS:
        for n in names:
            hit = next(root.rglob(n), None) if root.exists() else None
            if hit:
                return str(hit)
    return None


@lru_cache(maxsize=96)
def _font(kind: str, size: int):
    path = {"main": _find("Poppins-Bold.ttf", "DejaVuSans-Bold.ttf"),
            "medium": _find("Poppins-Medium.ttf", "DejaVuSans.ttf"),
            "dj": _find("DejaVuSans-Bold.ttf"),
            "free": _find("FreeSansBold.ttf", "FreeSans.ttf", "arialbd.ttf"),
            "emoji": _find("NotoColorEmoji.ttf", "seguiemj.ttf")}[kind]
    if path is None:
        return None
    try:
        if kind == "emoji":
            return ImageFont.truetype(path, 109)
        return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return None


@lru_cache(maxsize=4096)
def _has(kind: str, ch: str) -> bool:
    f = _font(kind, 40)
    if f is None:
        return False
    def sig(c):
        im = Image.new("L", (64, 64), 0)
        ImageDraw.Draw(im).text((6, 6), c, font=f, fill=255)
        return im.tobytes()
    return sig(ch) != sig("\U0010ffff")


def _is_emoji(cp: int) -> bool:
    if cp in (0x2660, 0x2661, 0x2662, 0x2663, 0x2664, 0x2665, 0x2666, 0x2667, 0x2605, 0x2606):
        return False
    return (cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF or 0x2190 <= cp <= 0x21FF
            or cp in (0x203C, 0x2049, 0x2122, 0x2139, 0x231A, 0x231B, 0x23E9, 0x23F0, 0x23F3, 0x24C2, 0x3030, 0x303D))


def _clusters(text: str):
    """Split into grapheme-ish clusters so emoji sequences (ZWJ, skin tones, flags) stay together."""
    out, i = [], 0
    while i < len(text):
        c = text[i]; i += 1
        cl = c
        ri = 0x1F1E6 <= ord(c) <= 0x1F1FF
        while i < len(text):
            n, cp = text[i], ord(text[i])
            if cp in (0x200D, 0xFE0F, 0x20E3) or 0x1F3FB <= cp <= 0x1F3FF or (ri and 0x1F1E6 <= cp <= 0x1F1FF and len(cl) == 1):
                cl += n; i += 1
                if cp == 0x200D and i < len(text):
                    cl += text[i]; i += 1
            else:
                break
        out.append(cl)
    return out


def _runs(text: str):
    """-> [(kind, string)] where kind is a font key or 'emoji'. Unsupported characters are dropped."""
    runs: list[list] = []
    for cl in _clusters(" ".join(text.split())):
        base = ord(cl[0])
        if cl.isspace():
            kind = None
        elif _is_emoji(base) or "\ufe0f" in cl:
            kind = "emoji" if _has("emoji", cl[0]) else None
        else:
            kind = next((k for k in ("main", "dj", "free") if all(_has(k, ch) or ch in "\u200d\u200c" or ord(ch) < 32 for ch in cl)), None)
        if kind is None and cl.isspace():
            kind = runs[-1][0] if runs and runs[-1][0] != "emoji" else "main"
        if kind is None:
            continue
        if runs and runs[-1][0] == kind and kind != "emoji":
            runs[-1][1] += cl
        else:
            runs.append([kind, cl])
    return runs


def rich_width(text: str, size: int) -> float:
    w = 0.0
    for kind, s in _runs(text):
        w += size * 1.12 if kind == "emoji" else _font(kind, size).getlength(s)
        if kind == "emoji":
            w += size * 1.12 * (len(_clusters(s)) - 1)
    return w


def draw_rich(img: Image.Image, xy, text: str, size: int, fill, anchor: str = "l", max_width: int | None = None,
              min_size: int = 16) -> int:
    """Draw mixed-script text. anchor: l/m/r (horizontal) around xy=(x, y_center). Shrinks to fit max_width.
    Returns the size actually used."""
    text = " ".join((text or "").split()) or "Player"
    if max_width:
        while size > min_size and rich_width(text, size) > max_width:
            size -= 1
        if rich_width(text, size) > max_width:           # still too wide: trim with an ellipsis
            while len(text) > 1 and rich_width(text + "…", size) > max_width:
                text = text[:-1]
            text = text.rstrip() + "…"
    total = rich_width(text, size)
    x, y = xy
    x = x - total / 2 if anchor == "m" else (x - total if anchor == "r" else x)
    base = y + size * 0.36
    d = ImageDraw.Draw(img)
    for kind, s in _runs(text):
        if kind == "emoji":
            f = _font("emoji", 109)
            for cl in _clusters(s):
                tile = Image.new("RGBA", (136, 128), (0, 0, 0, 0))
                ImageDraw.Draw(tile).text((0, 0), cl, font=f, embedded_color=True)
                bb = tile.getbbox() or (0, 0, 136, 128)
                tile = tile.crop(bb)
                sc = (size * 1.05) / max(tile.height, 1)
                tile = tile.resize((max(1, int(tile.width * sc)), max(1, int(tile.height * sc))), Image.LANCZOS)
                img.alpha_composite(tile, (int(x), int(y - tile.height / 2)))
                x += size * 1.12
        else:
            f = _font(kind, size)
            d.text((x, base), s, font=f, fill=fill, anchor="ls")
            x += f.getlength(s)
    return size


# --------------------------------------------------------------------------- pieces
def _avatar(avatar: bytes | None, name: str, w: int, h: int | None = None, radius: int | None = None) -> Image.Image:
    """Circle (radius=None, w==h) or rounded rectangle avatar. Falls back to a monogram of the first character."""
    h = h or w
    im = None
    if avatar:
        try:
            im = ImageOps.fit(Image.open(io.BytesIO(avatar)).convert("RGBA"), (w, h), Image.LANCZOS, centering=(0.5, 0.35))
        except Exception:
            im = None
    if im is None:
        g = Image.linear_gradient("L").resize((w, h))
        im = ImageOps.colorize(g, black=VIOLET, white=PINK).convert("RGBA")
        cl = next((c for c in _clusters(name.strip()) if not c.isspace()), "?")
        draw_rich(im, (w // 2, h // 2), cl.upper(), int(min(w, h) * 0.5), WHITE, "m")
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    if radius is None:
        md.ellipse([0, 0, w - 1, h - 1], fill=255)
    else:
        md.rounded_rectangle([0, 0, w - 1, h - 1], radius, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    return out


def _tilt(code: str, angle: float, scale: float, trump: bool = False) -> Image.Image:
    face = _card_face(code, trump).resize((int(CARD_W * scale), int(CARD_H * scale)), Image.LANCZOS)
    return face.rotate(angle, expand=True, resample=Image.BICUBIC)


def _pill(img, box, fill, outline=None, width=2):
    ImageDraw.Draw(img).rounded_rectangle(box, (box[3] - box[1]) // 2, fill=fill, outline=outline, width=width)


def _stat_chips(img, x0, y0, total_w, h, items, gap=10, dark=True):
    n = len(items)
    cw = (total_w - gap * (n - 1)) // n
    d = ImageDraw.Draw(img)
    for i, (lab, val) in enumerate(items):
        x = x0 + i * (cw + gap)
        d.rounded_rectangle([x, y0, x + cw, y0 + h], 14, fill=INK2 if dark else (20, 8, 40), outline=VIOLET, width=2)
        d.text((x + cw // 2, y0 + h * 0.27), lab, font=dj_font(max(11, int(h * 0.19))), fill=LAVENDER, anchor="mm")
        draw_rich(img, (x + cw // 2, y0 + h * 0.65), str(val), int(h * 0.38), GOLD, "m", max_width=cw - 12)


def _xp_bar(img, x0, x1, y, h, xp, floor, nxt):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y, x1, y + h], h // 2, fill=(20, 8, 40), outline=VIOLET, width=2)
    frac = 1.0 if nxt is None else max(0.0, min(1.0, (xp - floor) / max(nxt - floor, 1)))
    if frac > 0:
        d.rounded_rectangle([x0, y, x0 + max(h, int((x1 - x0) * frac)), y + h], h // 2, fill=PINK)


def _png(img) -> io.BytesIO:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", optimize=True)
    buf.seek(0); buf.name = "profile.png"
    return buf


def _suit_for(player_no: int) -> str:
    return "HDCS"[player_no % 4]


def _suit_color(s: str):
    return RED_SUIT if s in "HD" else BLACK_SUIT


def _pct(stats):
    return f"{stats['win_pct']:.0f}%"


# --------------------------------------------------------------------------- template A: playing card
def _face(name, username, player_no, rank_name, level, xp, floor, nxt, stats, avatar):
    W, H = 680, 940
    img = background(W, H)
    suit = _suit_for(player_no)
    col = _suit_color(suit)
    rank = RANK_CARD.get(rank_name, "A")
    d = ImageDraw.Draw(img)
    _glow(img, (40, 40, 640, 900), PINK, radius=18, grow=6)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 40, 640, 900], 38, fill=GOLD)
    d.rounded_rectangle([48, 48, 632, 892], 32, fill=CREAM)
    d.rounded_rectangle([62, 62, 618, 878], 24, outline=VIOLET, width=3)
    # watermark suit
    wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(wm).text((340, 620), SUIT_SYM[suit], font=dj_font(520), fill=col + (22,), anchor="mm")
    img.alpha_composite(wm)
    # corner indices (bottom-right is the top-left rotated 180°)
    idx = Image.new("RGBA", (110, 170), (0, 0, 0, 0))
    idd = ImageDraw.Draw(idx)
    idd.text((55, 52), rank, font=dj_font(78 if rank != "10" else 60), fill=col, anchor="mm")
    idd.text((55, 128), SUIT_SYM[suit], font=dj_font(66), fill=col, anchor="mm")
    img.alpha_composite(idx, (68, 74))
    img.alpha_composite(idx.rotate(180), (W - 68 - 110, H - 74 - 170))
    # avatar in a face-card panel
    fx0, fy0, fx1, fy1 = 160, 118, 520, 560
    d.rounded_rectangle([fx0, fy0, fx1, fy1], 30, fill=PURPLE)
    d.rounded_rectangle([fx0 + 8, fy0 + 8, fx1 - 8, fy1 - 8], 24, outline=PINK, width=3)
    av = _avatar(avatar, name, fx1 - fx0 - 36, fy1 - fy0 - 36, radius=18)
    img.alpha_composite(av, (fx0 + 18, fy0 + 18))
    for (sx, sy) in ((fx0 + 4, fy0 + 4), (fx1 - 4, fy0 + 4), (fx0 + 4, fy1 - 4), (fx1 - 4, fy1 - 4)):
        d.ellipse([sx - 22, sy - 22, sx + 22, sy + 22], fill=CREAM, outline=GOLD, width=3)
        d.text((sx, sy + 1), SUIT_SYM[suit], font=dj_font(26), fill=col, anchor="mm")
    # rank banner
    _pill(img, (190, 536, 490, 588), INK2, PINK, 3)
    d = ImageDraw.Draw(img)
    d.text((340, 562), f"{rank_name.upper()}  •  LV {level}", font=dj_font(24), fill=WHITE, anchor="mm")
    # name + username (exactly as in Telegram)
    draw_rich(img, (340, 650), name, 54, INK2, "m", max_width=440, min_size=22)
    if username:
        draw_rich(img, (340, 710), f"@{username}", 30, VIOLET, "m", max_width=420, min_size=16)
    _xp_bar(img, 170, 510, 746, 16, xp, floor, nxt)
    ImageDraw.Draw(img).text((340, 786), f"{xp:,} XP" + (f"  /  {nxt:,}" if nxt else "  •  MAX"), font=dj_font(15), fill=VIOLET, anchor="mm")
    _stat_chips(img, 160, 806, 360, 66, [("MATCHES", stats["matches"]), ("WINS", stats["wins"]), ("WIN %", _pct(stats))], gap=8)
    return img


# --------------------------------------------------------------------------- template B: arena + fan
def _arena(name, username, player_no, rank_name, level, xp, floor, nxt, stats, avatar):
    W, H = 1000, 560
    img = background(W, H)
    suit = _suit_for(player_no)
    wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(wm).text((840, 300), SUIT_SYM[suit], font=dj_font(460), fill=(255, 255, 255, 14), anchor="mm")
    img.alpha_composite(wm)
    rank = RANK_CARD.get(rank_name, "A")
    # fan of cards behind the avatar: your "rank card" in the middle
    fan = [(f"3{'HDCS'[(player_no + 1) % 4]}", 26, False), (f"A{'HDCS'[(player_no + 2) % 4]}", -26, False), (f"{rank}{suit}", 0, True)]
    for code, ang, top in fan:
        t = _tilt(code, ang, 0.74, trump=top)
        cx = 205 + int(math.sin(math.radians(-ang)) * 150)
        cy = 215 - int(math.cos(math.radians(ang)) * 40)
        if top:
            _glow(img, (cx - t.width // 2 + 18, cy - t.height // 2 + 18, cx + t.width // 2 - 18, cy + t.height // 2 - 18), GOLD, 14, 2)
        img.alpha_composite(t, (cx - t.width // 2, cy - t.height // 2))
    # avatar disc
    S = 250
    _glow(img, (80, 250, 80 + S, 250 + S), PINK, radius=16, grow=6)
    d = ImageDraw.Draw(img)
    d.ellipse([74, 244, 80 + S + 6, 250 + S + 6], fill=PINK)
    d.ellipse([80, 250, 80 + S, 250 + S], fill=INK)
    img.alpha_composite(_avatar(avatar, name, S - 12), (86, 256))
    # texts
    draw_rich(img, (400, 150), name, 66, WHITE, "l", max_width=560, min_size=26)
    if username:
        draw_rich(img, (402, 212), f"@{username}", 32, (255, 150, 205), "l", max_width=520, min_size=16)
    _pill(img, (400, 252, 640, 302), PURPLE, PINK, 3)
    d = ImageDraw.Draw(img)
    d.text((520, 277), rank_name.upper(), font=dj_font(24), fill=WHITE, anchor="mm")
    d.text((662, 277), f"LEVEL {level}", font=dj_font(28), fill=GOLD, anchor="lm")
    _xp_bar(img, 400, 940, 322, 20, xp, floor, nxt)
    d.text((400, 362), f"{xp:,} XP" + (f" / {nxt:,}" if nxt else "  (MAX)"), font=dj_font(16), fill=WHITE, anchor="lm")
    _stat_chips(img, 400, 392, 540, 78, [("MATCHES", stats["matches"]), ("WINS", stats["wins"]),
                                         ("WIN %", _pct(stats)), ("STREAK", stats["streak"])])
    d.text((400, 506), f"PLAYER ID  #{player_no}", font=dj_font(18), fill=LAVENDER, anchor="lm")
    d.text((940, 506), "THIRTY ONE", font=dj_font(18), fill=PINK, anchor="rm")
    return img


# --------------------------------------------------------------------------- template C: VIP pass
def _vip(name, username, player_no, rank_name, level, xp, floor, nxt, stats, avatar):
    W, H = 1000, 520
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = ImageOps.colorize(Image.linear_gradient("L").rotate(90).resize((W, H)), black=(10, 6, 22), white=(40, 14, 70)).convert("RGBA")
    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([6, 6, W - 7, H - 7], 34, fill=255)
    for cx in (330,):                                   # ticket notches
        md.ellipse([cx - 22, -22, cx + 22, 22], fill=0)
        md.ellipse([cx - 22, H - 22, cx + 22, H + 22], fill=0)
    img.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, W - 7, H - 7], 34, outline=GOLD, width=4)
    d.rounded_rectangle([18, 18, W - 19, H - 19], 26, outline=(120, 90, 30), width=1)
    for y in range(40, H - 40, 16):                     # perforation
        d.ellipse([327, y, 333, y + 6], fill=GOLD)
    # stub (left): avatar + barcode
    d.text((165, 52), "V I P   P A S S", font=dj_font(20), fill=GOLD, anchor="mm")
    _glow(img, (65, 80, 265, 280), GOLD, 14, 4)
    d = ImageDraw.Draw(img)
    d.ellipse([60, 75, 270, 285], fill=GOLD)
    img.alpha_composite(_avatar(avatar, name, 198), (66, 81))
    rnd = random.Random(player_no)
    x = 50
    while x < 280:
        w = rnd.choice((2, 2, 3, 5)); d.rectangle([x, 350, x + w, 440], fill=(240, 235, 250)); x += w + rnd.choice((2, 3, 4))
    d.text((165, 462), f"#{player_no}", font=dj_font(22), fill=GOLD, anchor="mm")
    # main
    d.text((370, 62), "THIRTY ONE  •  PREMIUM CARD CLUB", font=dj_font(17), fill=PINK, anchor="lm")
    draw_rich(img, (370, 140), name, 64, WHITE, "l", max_width=420, min_size=26)
    if username:
        draw_rich(img, (372, 202), f"@{username}", 30, (255, 150, 205), "l", max_width=420, min_size=16)
    rank = RANK_CARD.get(rank_name, "A")
    suit = _suit_for(player_no)
    t = _tilt(f"{rank}{suit}", 8, 0.62, trump=True)
    _glow(img, (820, 60, 820 + t.width, 60 + t.height), GOLD, 12, 2)
    img.alpha_composite(t, (820, 56))
    _pill(img, (370, 240, 600, 288), PURPLE, GOLD, 3)
    d = ImageDraw.Draw(img)
    d.text((485, 264), rank_name.upper(), font=dj_font(22), fill=WHITE, anchor="mm")
    d.text((622, 264), f"LV {level}", font=dj_font(26), fill=GOLD, anchor="lm")
    _xp_bar(img, 370, 780, 312, 16, xp, floor, nxt)
    d.text((370, 346), f"{xp:,} XP" + (f" / {nxt:,}" if nxt else "  (MAX)"), font=dj_font(15), fill=WHITE, anchor="lm")
    _stat_chips(img, 370, 376, 590, 84, [("MATCHES", stats["matches"]), ("WINS", stats["wins"]), ("WIN %", _pct(stats)),
                                         ("BEST", stats["highest"])])
    return img


TEMPLATES = {"face": _face, "arena": _arena, "vip": _vip}


def render_profile_card(template: str = "face", *, name: str, username: str | None, player_no: int, rank_name: str,
                        level: int, xp: int, xp_floor: int, xp_next: int | None, stats: dict,
                        avatar: bytes | None = None) -> io.BytesIO:
    fn = TEMPLATES.get(template, _face)
    return _png(fn(name, username, player_no, rank_name, level, xp, xp_floor, xp_next, stats, avatar))


# =========================================================================== OWNER cards (premium gold)
GOLD_LO, GOLD_MID, GOLD_HI = (112, 66, 10), (232, 172, 48), (255, 244, 178)
GOLD_PALE = (255, 226, 150)
BLACK = (9, 6, 16)


_GOLD_STOPS = [(0.00, (255, 246, 186)), (0.16, (244, 198, 78)), (0.42, (212, 146, 26)), (0.58, (255, 228, 128)),
               (0.76, (196, 128, 22)), (1.00, (112, 64, 8))]


@lru_cache(maxsize=1)
def _gold_strip() -> Image.Image:
    """256 px column of banded 'polished gold' (dark edges, rich body, a bright highlight band)."""
    strip = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        for (t0, c0), (t1, c1) in zip(_GOLD_STOPS, _GOLD_STOPS[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0)
                strip.putpixel((0, y), tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3)))
                break
    return strip


@lru_cache(maxsize=64)
def _gold(w: int, h: int, diag: bool = False) -> Image.Image:
    """Gold gradient tile of exactly w x h (diag=True tilts the highlight band like brushed metal)."""
    if not diag:
        return _gold_strip().resize((max(w, 1), max(h, 1)), Image.BILINEAR).convert("RGBA")
    side = int((w + h) * 0.9) + 8
    big = _gold_strip().resize((side, side), Image.BILINEAR).rotate(-28, resample=Image.BICUBIC, expand=False)
    left, top = (side - w) // 2, (side - h) // 2
    return big.crop((left, top, left + w, top + h)).convert("RGBA")


@lru_cache(maxsize=64)
def _gold_text_tile(w: int, h: int) -> Image.Image:
    """Bright gold for lettering: light top, rich body, slightly darker foot."""
    stops = [(0.0, (255, 250, 214)), (0.35, (255, 218, 110)), (0.7, (238, 172, 48)), (1.0, (196, 128, 24))]
    strip = Image.new("RGB", (1, 128))
    for y in range(128):
        t = y / 127
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0)
                strip.putpixel((0, y), tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3)))
                break
    return strip.resize((max(w, 1), max(h, 1)), Image.BILINEAR).convert("RGBA")


def _paste_gold(layer: Image.Image, mask: Image.Image, box, text: bool = False) -> None:
    """Fill `mask` (same size as layer) with gold, using a gradient sized to `box` so every shape gets the full gold range."""
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, layer.width), min(y1, layer.height)
    tile = _gold_text_tile(x1 - x0, y1 - y0) if text else _gold(x1 - x0, y1 - y0, True)
    layer.paste(tile, (x0, y0), mask.crop((x0, y0, x1, y1)))


def _gold_fill(img: Image.Image, mask: Image.Image, box, text: bool = False) -> None:
    """Paint the gold gradient into `box` of img wherever `mask` (same size as img, mode L) is set."""
    x0, y0, x1, y1 = [int(v) for v in box]
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _paste_gold(layer, mask, (x0, y0, x1, y1), text)
    img.alpha_composite(Image.composite(layer, Image.new("RGBA", img.size, (0, 0, 0, 0)), mask))


def gold_text(img: Image.Image, xy, text: str, size: int, anchor: str = "m", max_width: int | None = None,
              min_size: int = 18) -> None:
    """Mixed-script text filled with the gold gradient (colour emoji keep their own colours)."""
    tmp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    used = draw_rich(tmp, xy, text, size, (255, 255, 255, 255), anchor, max_width=max_width, min_size=min_size)
    r, g, b, a = tmp.split()
    near_white = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v >= 236 else 0)
    white = ImageChops.multiply(near_white, a)
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 150), (3, 4), a)
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2)))
    img.alpha_composite(tmp)                                      # emoji colours + base text
    bbox = a.getbbox() or (0, 0, 1, 1)
    _gold_fill(img, white, (bbox[0], bbox[1], bbox[2], bbox[3]), text=True)


def spaced(img: Image.Image, xy, text: str, size: int, fill, tracking: int = 6, anchor: str = "l") -> None:
    """Letter-spaced caps (draw_rich collapses spaces, so place each letter ourselves)."""
    f = dj_font(size)
    d = ImageDraw.Draw(img)
    widths = [f.getlength(c) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x, y = xy
    x = x - total / 2 if anchor == "m" else (x - total if anchor == "r" else x)
    for c, w in zip(text, widths):
        d.text((x, y), c, font=f, fill=fill, anchor="lm")
        x += w + tracking


def _sunburst(img: Image.Image, cx: int, cy: int, radius: int, rays: int = 28, alpha: int = 34) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i in range(rays):
        a = math.radians(i * 360 / rays)
        w = math.radians(360 / rays * 0.28)
        d.polygon([(cx, cy), (cx + math.cos(a - w) * radius, cy + math.sin(a - w) * radius),
                   (cx + math.cos(a + w) * radius, cy + math.sin(a + w) * radius)], fill=GOLD_MID + (alpha,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(1.5)))


def _lattice(img: Image.Image, step: int = 46, alpha: int = 14) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w, h = img.size
    for x in range(-h, w + h, step):
        d.line([(x, 0), (x + h, h)], fill=GOLD_MID + (alpha,), width=1)
        d.line([(x + h, 0), (x, h)], fill=GOLD_MID + (alpha,), width=1)
    img.alpha_composite(layer)


def _sparkles(img: Image.Image, seed: int, count: int, area) -> None:
    rnd = random.Random(seed)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0, y0, x1, y1 = area
    for _ in range(count):
        cx, cy, r = rnd.randint(x0, x1), rnd.randint(y0, y1), rnd.choice((5, 7, 9, 12, 16))
        d.polygon([(cx, cy - r), (cx + r * .22, cy - r * .22), (cx + r, cy), (cx + r * .22, cy + r * .22), (cx, cy + r),
                   (cx - r * .22, cy + r * .22), (cx - r, cy), (cx - r * .22, cy - r * .22)], fill=GOLD_HI + (rnd.randint(150, 235),))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(0.6)))
    img.alpha_composite(layer)


def _crown(img: Image.Image, cx: int, cy: int, w: int) -> None:
    """Gold crown with jewels, centred on (cx, cy). Drawn 3x then downsampled for clean edges."""
    k = 3
    h = int(w * 0.62)
    S = Image.new("RGBA", ((w + 40) * k, (h + 60) * k), (0, 0, 0, 0))
    ox, oy = 20 * k, 40 * k
    W, H = w * k, h * k
    pts = [(0, H), (0, int(H * .22)), (int(W * .22), int(H * .55)), (int(W * .36), int(H * .12)), (int(W * .5), int(H * .55)),
           (int(W * .5), 0), (int(W * .5), int(H * .55)), (int(W * .64), int(H * .12)), (int(W * .78), int(H * .55)), (W, int(H * .22)), (W, H)]
    # simple 5-peak outline
    pts = [(0, H), (0, int(H * .18)), (int(W * .19), int(H * .52)), (int(W * .31), 0), (int(W * .42), int(H * .5)),
           (int(W * .5), int(-H * .12)), (int(W * .58), int(H * .5)), (int(W * .69), 0), (int(W * .81), int(H * .52)), (W, int(H * .18)), (W, H)]
    mask = Image.new("L", S.size, 0)
    ImageDraw.Draw(mask).polygon([(x + ox, y + oy) for x, y in pts], fill=255)
    tile = _gold(S.width, S.height, True)
    body = Image.new("RGBA", S.size, (0, 0, 0, 0))
    body.paste(tile, (0, 0), mask)
    S.alpha_composite(body)
    d = ImageDraw.Draw(S)
    d.polygon([(x + ox, y + oy) for x, y in pts], outline=GOLD_LO + (255,), width=3 * k)
    d.rectangle([ox, oy + int(H * .72), ox + W, oy + H], fill=(150, 92, 16, 255), outline=GOLD_LO + (255,), width=2 * k)
    for gx, col in ((0.18, PINK), (0.5, (70, 140, 255)), (0.82, PINK)):
        r = int(H * .09)
        d.ellipse([ox + int(W * gx) - r, oy + int(H * .86) - r, ox + int(W * gx) + r, oy + int(H * .86) + r], fill=col + (255,), outline=WHITE + (255,), width=k)
    for px, py in ((.31, 0), (.5, -.12), (.69, 0)):                  # pearls on the peaks
        r = int(H * .075)
        d.ellipse([ox + int(W * px) - r, oy + int(H * py) - r, ox + int(W * px) + r, oy + int(H * py) + r], fill=(255, 250, 235, 255), outline=GOLD_LO + (255,), width=k)
    S = S.resize((S.width // k, S.height // k), Image.LANCZOS)
    glow = S.filter(ImageFilter.GaussianBlur(10))
    img.alpha_composite(glow, (cx - S.width // 2, cy - S.height // 2))
    img.alpha_composite(S, (cx - S.width // 2, cy - S.height // 2))


def _gold_ring(img: Image.Image, cx: int, cy: int, r: int, thick: int = 12, beads: int = 28) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([cx - r - thick, cy - r - thick, cx + r + thick, cy + r + thick], fill=255)
    md.ellipse([cx - r, cy - r, cx + r, cy + r], fill=0)
    _paste_gold(layer, mask, (cx - r - thick - 2, cy - r - thick - 2, cx + r + thick + 2, cy + r + thick + 2))
    glow = layer.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(glow)
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r - thick, cy - r - thick, cx + r + thick, cy + r + thick], outline=GOLD_LO, width=2)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GOLD_LO, width=2)
    R = r + thick + 14
    for i in range(beads):
        a = math.radians(i * 360 / beads)
        bx, by = cx + math.cos(a) * R, cy + math.sin(a) * R
        d.ellipse([bx - 4, by - 4, bx + 4, by + 4], fill=GOLD_HI if i % 2 else GOLD_MID, outline=GOLD_LO)


def _gold_frame(img: Image.Image, box, radius: int = 26, thick: int = 8) -> None:
    x0, y0, x1, y1 = box
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([x0, y0, x1, y1], radius, fill=255)
    md.rounded_rectangle([x0 + thick, y0 + thick, x1 - thick, y1 - thick], max(radius - thick, 2), fill=0)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _paste_gold(layer, mask, (x0, y0, x1, y1))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(8)))
    img.alpha_composite(layer)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x1, y1], radius, outline=GOLD_LO, width=2)
    d.rounded_rectangle([x0 + thick, y0 + thick, x1 - thick, y1 - thick], max(radius - thick, 2), outline=GOLD_LO, width=2)
    for (px, py) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):       # corner studs
        d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=GOLD_HI, outline=GOLD_LO, width=2)
        d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=GOLD_LO)


def _gold_pill(img: Image.Image, box, text: str, size: int, text_fill=BLACK) -> None:
    x0, y0, x1, y1 = [int(v) for v in box]
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([x0, y0, x1, y1], (y1 - y0) // 2, fill=255)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    _paste_gold(layer, mask, (x0, y0, x1, y1))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(7)))
    img.alpha_composite(layer)
    ImageDraw.Draw(img).rounded_rectangle([x0, y0, x1, y1], (y1 - y0) // 2, outline=GOLD_LO, width=2)
    draw_rich(img, ((x0 + x1) // 2, (y0 + y1) // 2), text, size, text_fill, "m", max_width=x1 - x0 - 24, min_size=10)


def _gold_chips(img: Image.Image, x0: int, y0: int, total_w: int, h: int, items, gap: int = 10) -> None:
    n = len(items)
    cw = (total_w - gap * (n - 1)) // n
    d = ImageDraw.Draw(img)
    for i, (lab, val) in enumerate(items):
        x = x0 + i * (cw + gap)
        d.rounded_rectangle([x, y0, x + cw, y0 + h], 14, fill=(20, 14, 30), outline=GOLD_MID, width=2)
        d.rounded_rectangle([x + 4, y0 + 4, x + cw - 4, y0 + h - 4], 11, outline=(90, 62, 20), width=1)
        d.text((x + cw // 2, y0 + h * 0.27), lab, font=dj_font(max(11, int(h * 0.18))), fill=GOLD_PALE, anchor="mm")
        gold_text(img, (x + cw // 2, y0 + h * 0.64), str(val), int(h * 0.4), "m", max_width=cw - 14, min_size=12)


def _gold_xp(img: Image.Image, x0: int, x1: int, y: int, h: int, xp: int, floor: int, nxt: int | None) -> None:
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y, x1, y + h], h // 2, fill=(18, 12, 26), outline=GOLD_MID, width=2)
    frac = 1.0 if nxt is None else max(0.0, min(1.0, (xp - floor) / max(nxt - floor, 1)))
    if frac > 0:
        mask = Image.new("L", img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([x0 + 3, y + 3, x0 + 3 + max(h - 6, int((x1 - x0 - 6) * frac)), y + h - 3], (h - 6) // 2, fill=255)
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        _paste_gold(layer, mask, (x0, y, x1, y + h))
        img.alpha_composite(layer)


def _vignette(img: Image.Image) -> None:
    w, h = img.size
    v = Image.new("L", (w, h), 0)
    ImageDraw.Draw(v).ellipse([-w * .15, -h * .25, w * 1.15, h * 1.25], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(min(w, h) // 5))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 170))
    dark.putalpha(ImageChops.invert(v).point(lambda x: int(x * 0.66)))
    img.alpha_composite(dark)


# ---- landscape: "Royal Owner Pass"
def _owner(name, username, player_no, rank_name, level, xp, floor, nxt, stats, avatar):
    W, H = 1000, 580
    img = Image.new("RGBA", (W, H), BLACK + (255,))
    bg = ImageOps.colorize(Image.linear_gradient("L").resize((W, H)), black=(6, 3, 12), white=(34, 12, 52)).convert("RGBA")
    img.alpha_composite(bg)
    _lattice(img)
    _sunburst(img, 215, 292, 760, 32, 30)
    _vignette(img)
    _gold_frame(img, (16, 16, W - 17, H - 17), 30, 8)
    _sparkles(img, player_no, 26, (40, 40, W - 40, H - 40))
    d = ImageDraw.Draw(img)
    # avatar medallion + crown
    cx, cy, r = 215, 312, 128
    _glow(img, (cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14), GOLD_MID, radius=22, grow=4)
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=BLACK)
    img.alpha_composite(_avatar(avatar, name, r * 2), (cx - r, cy - r))
    _gold_ring(img, cx, cy, r + 2, 13, 30)
    _crown(img, cx, cy - r - 30, 150)
    # ribbon under avatar
    _gold_pill(img, (cx - 118, cy + r + 6, cx + 118, cy + r + 52), "👑  THE OWNER", 24)
    # right side
    tx = 400
    spaced(img, (tx, 78), "FOUNDER  &  OWNER", 17, GOLD_PALE, 7)
    d = ImageDraw.Draw(img)
    d.line([(tx + 372, 78), (W - 66, 78)], fill=GOLD_MID, width=2)
    d.polygon([(W - 50, 70), (W - 42, 78), (W - 50, 86), (W - 58, 78)], fill=GOLD_HI)
    gold_text(img, (tx, 150), name, 70, "l", max_width=W - tx - 50, min_size=28)
    if username:
        draw_rich(img, (tx + 3, 214), f"@{username}", 32, GOLD_PALE, "l", max_width=W - tx - 60, min_size=16)
    _gold_pill(img, (tx, 250, tx + 230, 302), "ALL ACCESS", 22)
    d = ImageDraw.Draw(img)
    d.text((tx + 252, 276), f"LEVEL {level}", font=dj_font(28), fill=GOLD_HI, anchor="lm")
    _gold_xp(img, tx, W - 50, 318, 20, xp, floor, nxt)
    d.text((W - 50, 356), f"{xp:,} XP" + ("   •   MAX LEVEL" if nxt is None else f"  /  {nxt:,}"), font=dj_font(15), fill=GOLD_PALE, anchor="rm")
    _gold_chips(img, tx, 380, W - tx - 50, 80, [("MATCHES", stats["matches"]), ("WINS", stats["wins"]),
                                                   ("WIN %", _pct(stats)), ("31 WINS", stats.get("wins31", stats["streak"]))])
    d = ImageDraw.Draw(img)
    d.text((tx, 512), f"PLAYER ID  #{player_no}", font=dj_font(18), fill=GOLD_PALE, anchor="lm")
    for i, sy in enumerate("♠♥♦♣"):
        d.text((W // 2 + 120 + i * 34, 512), sy, font=dj_font(28), fill=GOLD_MID if sy in "♠♣" else (214, 60, 90), anchor="mm")
    spaced(img, (W - 50, 512), "THIRTY ONE", 17, GOLD_HI, 5, "r")
    return img


# ---- portrait: "Owner Card" (a black & gold king card)
def _owner_card(name, username, player_no, rank_name, level, xp, floor, nxt, stats, avatar):
    W, H = 680, 940
    img = Image.new("RGBA", (W, H), BLACK + (255,))
    bg = ImageOps.colorize(Image.linear_gradient("L").resize((W, H)), black=(8, 4, 14), white=(44, 14, 60)).convert("RGBA")
    img.alpha_composite(bg)
    _glow(img, (40, 40, 640, 900), GOLD_MID, radius=24, grow=4)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 40, 640, 900], 40, fill=(14, 10, 22))
    card = img.crop((40, 40, 640, 900))
    _lattice(card, 40, 16)
    _sunburst(card, 300, 330, 700, 30, 26)
    img.paste(card, (40, 40))
    watermark = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(watermark).text((340, 640), "♚", font=dj_font(560), fill=GOLD_MID + (11,), anchor="mm")
    img.alpha_composite(watermark)
    _gold_frame(img, (40, 40, 640, 900), 40, 9)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([68, 68, 612, 872], 28, outline=(120, 86, 28), width=2)
    _sparkles(img, player_no + 7, 18, (70, 70, 610, 870))
    # corner indices: king + suit (bottom-right rotated)
    suit = _suit_for(player_no)
    idx = Image.new("RGBA", (120, 190), (0, 0, 0, 0))
    mask = Image.new("L", idx.size, 0)
    md = ImageDraw.Draw(mask)
    md.text((60, 56), "♚", font=dj_font(92), fill=255, anchor="mm")
    md.text((60, 140), SUIT_SYM[suit], font=dj_font(64), fill=255, anchor="mm")
    idx.paste(_gold(120, 190, True), (0, 0), mask)
    img.alpha_composite(idx, (66, 76))
    img.alpha_composite(idx.rotate(180), (W - 66 - 120, H - 76 - 190))
    # avatar in a gold arch frame with crown
    fx0, fy0, fx1, fy1 = 168, 150, 512, 580
    d.rounded_rectangle([fx0, fy0, fx1, fy1], 28, fill=(30, 12, 52))
    av = _avatar(avatar, name, fx1 - fx0 - 28, fy1 - fy0 - 28, radius=18)
    img.alpha_composite(av, (fx0 + 14, fy0 + 14))
    _gold_frame(img, (fx0, fy0, fx1, fy1), 28, 9)
    _crown(img, 340, fy0 - 6, 190)
    # owner ribbon
    _gold_pill(img, (170, 562, 510, 616), "👑  THE OWNER  👑", 26)
    gold_text(img, (340, 684), name, 56, "m", max_width=470, min_size=22)
    if username:
        draw_rich(img, (340, 740), f"@{username}", 30, GOLD_PALE, "m", max_width=430, min_size=16)
    _gold_xp(img, 170, 510, 776, 16, xp, floor, nxt)
    d = ImageDraw.Draw(img)
    d.text((340, 814), f"LEVEL {level}  •  {xp:,} XP", font=dj_font(16), fill=GOLD_PALE, anchor="mm")
    _gold_chips(img, 166, 826, 324, 56, [("MATCHES", stats["matches"]), ("WINS", stats["wins"]), ("WIN %", _pct(stats))], gap=7)
    return img


TEMPLATES["owner"] = _owner
TEMPLATES["owner_card"] = _owner_card
