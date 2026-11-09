"""Pillow renderers for the 31 Card Game (same neon pink / violet / black identity as Briscola).
All return PNG BytesIO. Names may contain Hindi / emoji (rendered through profile_cards.draw_rich)."""
from __future__ import annotations

import io
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

from game.thirty_one.cards import SYMBOL, SUIT_NAME, rank as c_rank, suit as c_suit, value as c_value
from ui.images import (BLACK_SUIT, CARD_H, CARD_W, GOLD, INK, PINK, PURPLE, RED_SUIT, VIOLET, WHITE, _glow, _png,
                       background, font as dj)
from ui.profile_cards import LAVENDER, draw_rich

GREY = (110, 98, 140)
GREEN = (80, 230, 160)


# ------------------------------------------------------------------ primitives
@lru_cache(maxsize=512)
def face52(code: str, mode: str = "") -> Image.Image:
    """mode: '' normal | 'gold' counts towards the score | 'new' just picked up | 'dim' not counting."""
    r, s = c_rank(code), c_suit(code)
    col = RED_SUIT if s in "HD" else BLACK_SUIT
    im = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    edge, width = {"gold": (GOLD, 6), "new": (PINK, 6)}.get(mode, (VIOLET, 3))
    d.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], 16, fill=(248, 246, 253), outline=edge, width=width)
    d.rounded_rectangle([10, 10, CARD_W - 11, CARD_H - 11], 11, outline=(226, 219, 241), width=1)
    rs = 40 if len(r) == 1 else 33
    d.text((16, 12), r, font=dj(rs), fill=col)
    d.text((16, 58), SYMBOL[s], font=dj(30), fill=col)
    d.text((CARD_W - 16, CARD_H - 12), r, font=dj(rs), fill=col, anchor="rs")
    d.text((CARD_W - 16, CARD_H - 58), SYMBOL[s], font=dj(30), fill=col, anchor="rs")
    if r in "JQK":
        d.rounded_rectangle([46, 64, CARD_W - 47, 148], 12, fill=PURPLE)
        d.rounded_rectangle([50, 68, CARD_W - 51, 144], 9, outline=PINK, width=2)
        d.text((CARD_W // 2, 106), r, font=dj(62), fill=WHITE, anchor="mm")
        d.text((CARD_W // 2, 188), SYMBOL[s], font=dj(60), fill=col, anchor="mm")
    else:
        d.text((CARD_W // 2, CARD_H // 2), SYMBOL[s], font=dj(112 if r == "A" else 90), fill=col, anchor="mm")
    d.rounded_rectangle([CARD_W // 2 - 29, CARD_H - 42, CARD_W // 2 + 29, CARD_H - 15], 10, fill=INK)
    d.text((CARD_W // 2, CARD_H - 28), f"{c_value(code)} pt", font=dj(15), fill=GOLD, anchor="mm")
    if mode == "dim":
        shade = Image.new("RGBA", im.size, (20, 8, 40, 120))
        mask = Image.new("L", im.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], 16, fill=255)
        im.paste(Image.alpha_composite(im, shade), (0, 0), mask)
    if mode == "new":
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([CARD_W // 2 - 30, -2, CARD_W // 2 + 30, 26], 12, fill=PINK)
        d.text((CARD_W // 2, 12), "NEW", font=dj(15), fill=WHITE, anchor="mm")
    return im


@lru_cache(maxsize=1)
def back() -> Image.Image:
    im = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, CARD_W - 1, CARD_H - 1], 16, fill=(30, 10, 60), outline=PINK, width=3)
    for i in range(-CARD_H, CARD_W + CARD_H, 26):
        d.line([(i, 0), (i + CARD_H, CARD_H)], fill=(110, 40, 190), width=2)
        d.line([(i + CARD_H, 0), (i, CARD_H)], fill=(110, 40, 190), width=2)
    d.rounded_rectangle([34, 88, CARD_W - 35, 172], 14, fill=INK, outline=VIOLET, width=2)
    d.text((CARD_W // 2, 130), "31", font=dj(54), fill=PINK, anchor="mm")
    return im


def paste(img, tile: Image.Image, x: int, y: int, scale: float = 1.0, glow=None):
    if scale != 1.0:
        tile = tile.resize((int(tile.width * scale), int(tile.height * scale)), Image.LANCZOS)
    if glow:
        _glow(img, (x, y, x + tile.width, y + tile.height), glow, radius=12, grow=4)
    img.alpha_composite(tile, (x, y))
    return tile.size


def heart(img: Image.Image, cx: float, cy: float, size: float, full: bool = True) -> None:
    """Neon heart (filled pink when alive, grey outline when lost). Drawn 4x then downsampled."""
    k = 4
    S = int(size * 1.4) * k
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    r = size * k * 0.27
    c = S / 2
    pts = [(c - 2 * r * 0.97, c - r * 0.2), (c + 2 * r * 0.97, c - r * 0.2), (c, c + size * k * 0.52)]
    col = PINK if full else GREY
    kw = {"fill": col} if full else {"outline": col, "width": max(2, k)}
    if full:
        d.ellipse([c - 2 * r, c - r * 1.55, c, c + r * 0.45], **kw)
        d.ellipse([c, c - r * 1.55, c + 2 * r, c + r * 0.45], **kw)
        d.polygon(pts, **kw)
    else:
        d.ellipse([c - 2 * r, c - r * 1.55, c, c + r * 0.45], **kw)
        d.ellipse([c, c - r * 1.55, c + 2 * r, c + r * 0.45], **kw)
        d.polygon(pts, fill=(20, 10, 40))
        d.line(pts + [pts[0]], fill=col, width=max(2, k))
    tile = tile.resize((S // k, S // k), Image.LANCZOS)
    if full:
        _glow_tile = tile.filter(ImageFilter.GaussianBlur(3))
        img.alpha_composite(_glow_tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))
    img.alpha_composite(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))


def hearts_row(img, x, y, lives: int, total: int, size: float = 22, gap: float = 6):
    total = max(total, lives, 1)
    for i in range(total):
        heart(img, x + i * (size + gap) + size / 2, y, size, full=i < lives)


def sparkle(draw: ImageDraw.ImageDraw, cx, cy, r, fill=GOLD):
    draw.polygon([(cx, cy - r), (cx + r * .25, cy - r * .25), (cx + r, cy), (cx + r * .25, cy + r * .25),
                  (cx, cy + r), (cx - r * .25, cy + r * .25), (cx - r, cy), (cx - r * .25, cy - r * .25)], fill=fill)


def gauge(img: Image.Image, cx: int, cy: int, radius: int, score: float, label: str = "POINTS") -> None:
    """Ring gauge 0 -> 31. Turns gold with sparkles at 31."""
    k, R, T = 3, radius, 20
    S = (R * 2 + 40) * k
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    box = [20 * k, 20 * k, (R * 2 + 20) * k, (R * 2 + 20) * k]
    d.arc(box, 0, 360, fill=(40, 22, 72), width=T * k)
    frac = max(0.0, min(1.0, score / 31))
    full = score >= 31
    if frac > 0:
        d.arc(box, -90, -90 + 360 * frac, fill=GOLD if full else PINK, width=T * k)
    tile = tile.resize((S // k, S // k), Image.LANCZOS)
    ox, oy = cx - tile.width // 2, cy - tile.height // 2
    if full:
        glow = tile.filter(ImageFilter.GaussianBlur(10))
        img.alpha_composite(glow, (ox, oy))
    img.alpha_composite(tile, (ox, oy))
    d = ImageDraw.Draw(img)
    txt = f"{score:g}"
    d.text((cx, cy - 6), txt, font=dj(int(R * (0.9 if len(txt) < 3 else 0.7))), fill=GOLD if full else WHITE, anchor="mm")
    d.text((cx, cy + R * 0.52), label, font=dj(int(R * 0.2)), fill=LAVENDER, anchor="mm")
    if full:
        for ang, rr in ((-35, 12), (40, 9), (150, 11), (215, 8)):
            sparkle(d, cx + math.cos(math.radians(ang)) * (R + 22), cy + math.sin(math.radians(ang)) * (R + 22), rr)


def _title(img, text, sub=None):
    draw_rich(img, (img.width // 2, 36), text, 34, PINK, "m")
    if sub:
        draw_rich(img, (img.width // 2, 70), sub, 17, LAVENDER, "m", max_width=img.width - 80)


def _strip(img, box, text, color=WHITE, outline=VIOLET):
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box, (box[3] - box[1]) // 2 if box[3] - box[1] < 70 else 18, fill=(20, 8, 40), outline=outline, width=3)
    draw_rich(img, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), text, 22, color, "m", max_width=box[2] - box[0] - 40, min_size=12)


# ------------------------------------------------------------------ private hand
def render_hand(*, hand: list[str], counting: list[str], score: float, new_card: str | None, lives: int,
                total_lives: int, top_discard: str | None, draw_count: int, status: str, round_no: int,
                points_mode: bool = False, total_points: float = 0, taken: str | None = None) -> io.BytesIO:
    n = max(len(hand), 1)
    w, h = 860, 560
    img = background(w, h)
    _title(img, "🔥 31 CARD GAME", f"ROUND {round_no}   •   YOUR PRIVATE CARDS")
    scale = 0.8 if n <= 3 else 0.72
    cw, ch = int(CARD_W * scale), int(CARD_H * scale)
    gap = 16
    total_w = n * cw + (n - 1) * gap
    x0 = 28 + (590 - total_w) // 2
    for i, c in enumerate(hand):
        mode = "new" if c == new_card else ("gold" if c in counting else "dim")
        paste(img, face52(c, mode), x0 + i * (cw + gap), 110, scale, glow=GOLD if mode == "gold" and score >= 31 else None)
    # score gauge
    gauge(img, 725, 240, 88, score, "BEST SUIT" if score < 31 else "PERFECT")
    d = ImageDraw.Draw(img)
    if score >= 31:
        d.rounded_rectangle([640, 365, 810, 405], 20, fill=GOLD)
        d.text((725, 385), "31! DECLARE", font=dj(19), fill=INK, anchor="mm")
    elif score >= 27:
        d.text((725, 385), "SO CLOSE!", font=dj(20), fill=PINK, anchor="mm")
    else:
        d.text((725, 385), "TARGET 31", font=dj(18), fill=LAVENDER, anchor="mm")
    # status + footer
    _strip(img, (28, 342 + 80, w - 28, 342 + 134), status, PINK if "YOUR TURN" in status.upper() else WHITE,
           PINK if "YOUR TURN" in status.upper() else VIOLET)
    y = 492
    d.rounded_rectangle([28, y - 10, w - 28, y + 46], 16, fill=(20, 8, 40), outline=VIOLET, width=2)
    if points_mode:
        d.text((52, y + 18), f"TOTAL {total_points:g} PTS", font=dj(20), fill=GOLD, anchor="lm")
    else:
        hearts_row(img, 52, y + 18, lives, total_lives, 22)
    d.text((w // 2, y + 18), f"DRAW PILE {draw_count}", font=dj(18), fill=WHITE, anchor="mm")
    d.text((w - 150, y + 18), "DISCARD", font=dj(16), fill=LAVENDER, anchor="rm")
    if top_discard:
        paste(img, face52(top_discard), w - 138, y - 6, 0.26)
    return _png(img)


# ------------------------------------------------------------------ live table
def render_table(*, room: str, mode_label: str, names: list[str], lives: list[int], total_lives: int, totals: list[float],
                 points_mode: bool, active: list[bool], turn: int | None, knocker: int | None, final_left: list[int],
                 draw_count: int, discard_top: str | None, discard_count: int, round_no: int, last_action: str = "",
                 status: str = "", winner_text: str | None = None) -> io.BytesIO:
    n = len(names)
    w, h = 1000, 700
    img = background(w, h)
    _title(img, "🔥 31 CARD GAME  •  LIVE MATCH", f"ROOM {room}   •   {mode_label}   •   ROUND {round_no}")
    d = ImageDraw.Draw(img)
    per_row = 4 if n > 4 else n
    rows = [list(range(i, min(i + per_row, n))) for i in range(0, n, per_row)]
    cwid, chei, gapx = 220, 104, 14
    y = 108
    for row in rows:
        tw = len(row) * cwid + (len(row) - 1) * gapx
        x = (w - tw) // 2
        for s in row:
            alive = active[s]
            is_turn = turn == s and not winner_text
            if is_turn:
                _glow(img, (x, y, x + cwid, y + chei), PINK, radius=12, grow=3)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([x, y, x + cwid, y + chei], 16, fill=(24, 10, 46) if alive else (18, 12, 28),
                                outline=PINK if is_turn else (VIOLET if alive else GREY), width=3 if is_turn else 2)
            draw_rich(img, (x + 14, y + 26), f"{'▶ ' if is_turn else ''}{names[s]}", 21,
                      PINK if is_turn else (WHITE if alive else GREY), "l", max_width=cwid - 28, min_size=12)
            if not alive:
                d.text((x + 14, y + 72), "OUT", font=dj(22), fill=GREY, anchor="lm")
            elif points_mode:
                d.text((x + 14, y + 72), f"{totals[s]:g} PTS", font=dj(24), fill=GOLD, anchor="lm")
            else:
                hearts_row(img, x + 14, y + 72, lives[s], total_lives, 22 if total_lives <= 5 else 17, 5)
            if knocker == s:
                d.rounded_rectangle([x + cwid - 84, y + 52, x + cwid - 10, y + 88], 14, fill=GOLD)
                d.text((x + cwid - 47, y + 70), "KNOCK", font=dj(16), fill=INK, anchor="mm")
            elif s in final_left and not winner_text:
                d.text((x + cwid - 12, y + 72), "LAST TURN", font=dj(12), fill=LAVENDER, anchor="rm")
            x += cwid + gapx
        y += chei + 14
    # piles
    py = 112 + len(rows) * (chei + 14) + 8
    cx = w // 2
    d = ImageDraw.Draw(img)
    for k in range(min(4, max(1, draw_count // 8 + 1))):
        paste(img, back(), cx - 190 + k * 5, py + k * 3, 0.55)
    d.text((cx - 150, py + 160), f"DRAW PILE · {draw_count}", font=dj(17), fill=WHITE, anchor="mm")
    if discard_top:
        paste(img, face52(discard_top), cx + 55, py, 0.55, glow=VIOLET)
    else:
        d.rounded_rectangle([cx + 55, py, cx + 55 + int(CARD_W * .55), py + int(CARD_H * .55)], 10, outline=GREY, width=2)
    d.text((cx + 105, py + 160), f"DISCARD · {discard_count}", font=dj(17), fill=WHITE, anchor="mm")
    if last_action:
        draw_rich(img, (60, py + 60), "LAST MOVE", 14, LAVENDER, "l")
        draw_rich(img, (60, py + 92), last_action, 20, WHITE, "l", max_width=270, min_size=12)
    # bottom strip
    if winner_text:
        _strip(img, (40, 610, w - 40, 676), winner_text, GOLD, GOLD)
    else:
        _strip(img, (40, 610, w - 40, 676), status or "…", PINK if knocker is not None else WHITE,
               GOLD if knocker is not None else VIOLET)
    return _png(img)


# ------------------------------------------------------------------ round reveal / final
def render_reveal(*, room: str, names: list[str], round_info: dict, points_mode: bool, total_lives: int,
                  headline: str, footer: str, match_over: bool = False) -> io.BytesIO:
    n = len(names)
    cols = 1 if n <= 3 else 2
    rows = math.ceil(n / cols)
    cw, chh = (820 if cols == 1 else 470), 180
    w = 60 + cols * cw + (cols - 1) * 20
    h = 150 + rows * (chh + 14) + 110
    img = background(w, h)
    _title(img, f"ROUND {round_info['no']} RESULT" if not match_over else "🏆 MATCH OVER", f"ROOM {room}")
    draw_rich(img, (w // 2, 106), headline, 24, WHITE, "m", max_width=w - 80, min_size=14)
    scores, hands = round_info["scores"], round_info["hands"]
    losers, elim = set(round_info["losers"]), set(round_info["eliminated"])
    best = max((s for s in scores if s is not None), default=0)
    d = ImageDraw.Draw(img)
    for s in range(n):
        col, row = s % cols, s // cols
        x, y = 30 + col * (cw + 20), 140 + row * (chh + 14)
        sc = scores[s]
        lost = s in losers and not round_info["void"]
        win = sc is not None and sc == best and not lost
        if win:
            _glow(img, (x, y, x + cw, y + chh), GOLD, radius=12, grow=3)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([x, y, x + cw, y + chh], 18, fill=(24, 10, 46),
                            outline=GOLD if win else ((230, 70, 90) if lost else VIOLET), width=3)
        draw_rich(img, (x + 16, y + 26), names[s] + ("  ✊" if round_info["knocker"] == s else ""), 22,
                  GOLD if win else WHITE, "l", max_width=cw - 200, min_size=12)
        if sc is None:
            d.text((x + 16, y + 100), "OUT", font=dj(28), fill=GREY, anchor="lm")
            if not points_mode:
                hearts_row(img, x + cw - 16 - max(total_lives, 1) * 23 + 5, y + 26, 0, total_lives, 18, 5)
            continue
        for i, c in enumerate(hands[s]):
            mode = "gold" if win else ""
            paste(img, face52(c, mode), x + 16 + i * 82, y + 48, 0.46)
        d.text((x + cw - 100, y + 74), f"{sc:g}", font=dj(54), fill=GOLD if sc >= 31 else WHITE, anchor="mm")
        d.text((x + cw - 100, y + 112), "POINTS", font=dj(13), fill=LAVENDER, anchor="mm")
        if not points_mode:
            left, size, gap = round_info["lives"][s], (18 if total_lives <= 5 else 12), (5 if total_lives <= 5 else 3)
            width = max(total_lives, left, 1) * (size + gap) - gap
            hearts_row(img, x + cw - 16 - width, y + 26, max(left, 0), total_lives, size, gap)   # lives left after this round
            lossn = round_info["life_loss"][s]
            if lossn:
                d.text((x + cw - 100, y + 138), f"-{lossn} ♥" + ("  OUT" if s in elim else ""), font=dj(18),
                       fill=(255, 100, 120), anchor="mm")
            else:
                d.text((x + cw - 100, y + 138), "SAFE", font=dj(15), fill=GREEN, anchor="mm")
        else:
            d.text((x + cw - 100, y + 138), f"TOTAL {round_info['totals'][s]:g}", font=dj(15), fill=GOLD, anchor="mm")
    _strip(img, (40, h - 92, w - 40, h - 30), footer, GOLD if match_over else PINK, GOLD if match_over else VIOLET)
    return _png(img)
