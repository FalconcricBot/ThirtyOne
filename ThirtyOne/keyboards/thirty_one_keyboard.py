from urllib.parse import quote

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from config import settings
from game.thirty_one.cards import label

LB_TABS = [("global", "🌍 Global"), ("week", "📅 Weekly"), ("month", "🗓 Monthly"), ("friends", "👥 Friends")]
MODE_LABEL = {"lives": "❤️ Lives mode", "knockout": "💀 Knockout (1 life)", "points": "🔢 Points mode"}


def games_menu_kb() -> M:
    return M([[B("🃏 BRISCOLA", callback_data="cg:briscola")],
              [B("🔥 31 CARD GAME", callback_data="cg:31")],
              [B("⬅️ BACK TO MENU", callback_data="m:home")]])


def menu_kb() -> M:
    return M([[B("⚡ Quick Match", callback_data="t31:quick")],
              [B("👥 Create Private Room", callback_data="t31:room"), B("🔑 Join Room", callback_data="t31:join")],
              [B("🤖 Practice with AI", callback_data="t31:ai"), B("🏟 Tournaments", callback_data="t:list")],
              [B("🏆 Leaderboard", callback_data="t31:lb:global:0"), B("📊 My Stats", callback_data="t31:stats")],
              [B("📜 History", callback_data="t31:hist:0"), B("📖 Rules", callback_data="t31:rules")],
              [B("⬅️ Card games", callback_data="m:games")]])


def back_kb() -> M:
    return M([[B("🔥 31 Menu", callback_data="cg:31"), B("🏠 Menu", callback_data="m:home")]])


def mode_pick_kb(cfg) -> M:
    rows = []
    if cfg.lives_mode_enabled:
        rows += [[B(MODE_LABEL["lives"], callback_data="t31:rm:lives")], [B(MODE_LABEL["knockout"], callback_data="t31:rm:knockout")]]
    if cfg.points_mode_enabled:
        rows.append([B(MODE_LABEL["points"], callback_data="t31:rm:points")])
    rows.append([B("⬅ Back", callback_data="cg:31")])
    return M(rows)


def size_kb(mode: str, cfg) -> M:
    sizes = [B(f"{n} players", callback_data=f"t31:new:{mode}:{n}") for n in range(cfg.min_players, cfg.max_players + 1)]
    rows = [sizes[i:i + 3] for i in range(0, len(sizes), 3)]
    rows.append([B("⬅ Back", callback_data="t31:room")])
    return M(rows)


def quick_pick_kb(cfg) -> M:
    sizes = [B(f"{n} players", callback_data=f"t31:q:{n}") for n in range(cfg.min_players, min(cfg.max_players, 4) + 1)]
    return M([sizes, [B("⬅ Back", callback_data="cg:31")]])


def quick_cancel_kb() -> M:
    return M([[B("❌ Cancel search", callback_data="t31:q:cancel")]])


def ai_level_kb() -> M:
    return M([[B("🟢 Easy", callback_data="t31:ai:lvl:easy"), B("🟡 Medium", callback_data="t31:ai:lvl:medium")],
              [B("🟠 Hard", callback_data="t31:ai:lvl:hard"), B("🔴 Expert", callback_data="t31:ai:lvl:expert")],
              [B("⬅ Back", callback_data="cg:31")]])


def ai_opp_kb(level: str) -> M:
    return M([[B(f"vs {k} AI", callback_data=f"t31:ai:go:{level}:{k}") for k in (1, 2, 3)],
              [B("⬅ Back", callback_data="t31:ai")]])


def invite_link(code: str) -> str:
    return f"https://t.me/{settings.bot_username}?start=room_{code}"


def room_kb(room) -> M:
    link = invite_link(room.code)
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('Join my 31 Card Game room ' + room.code + ' 🔥')}"
    rows = [[B("🙋 Join", callback_data=f"t31:r:join:{room.code}"), B("➕ Invite Friends", url=share)]]
    row = [B("🚀 Start Game", callback_data=f"t31:r:start:{room.code}")]
    if not room.full:
        row.append(B("🤖 Add AI", callback_data=f"t31:r:ai:{room.code}"))
    rows.append(row)
    rows.append([B("🔄 Refresh", callback_data=f"t31:r:refresh:{room.code}"),
                 B("❌ Leave Room", callback_data=f"t31:r:leave:{room.code}")])
    rows.append([B("🗑 Cancel Room (owner)", callback_data=f"t31:r:cancel:{room.code}")])
    return M(rows)


def action_kb(gid: int, version: int, *, my_turn: bool, phase: str, hand: list[str], top: str | None,
              can_knock: bool, can_declare: bool, taken: str | None) -> M:
    base = f"t31:a:{gid}:{version}"
    extra = [B("📊 My score", callback_data=f"t31:sc:{gid}"), B("📜 Rules", callback_data="t31:rules"),
             B("🏳 Leave", callback_data=f"t31:lv:{gid}")]
    if not my_turn:
        return M([extra])
    rows = []
    if phase == "draw":
        row = [B("🂠 Draw from deck", callback_data=f"{base}:dr")]
        if top:
            row.append(B(f"🗑 Take {label(top)}", callback_data=f"{base}:tk"))
        rows.append(row)
        row2 = []
        if can_knock:
            row2.append(B("✊ KNOCK", callback_data=f"{base}:kn"))
        if can_declare:
            row2.append(B("🎯 DECLARE 31", callback_data=f"{base}:d31"))
        if row2:
            rows.append(row2)
    elif phase == "discard":
        cards = [B(f"🗑 {label(c)}", callback_data=f"{base}:ds:{c}") for c in hand if c != taken]
        rows.append(cards)
    rows.append(extra)
    return M(rows)


def open_cards_kb() -> M:
    """Under the group turn-ping: jumps straight into the bot's private chat (and resends the hand)."""
    return M([[B("🃏 Open my cards", url=f"https://t.me/{settings.bot_username}?start=hand")]])


def group_kb() -> M:
    return M([[B("📊 LEADERBOARD", callback_data="t31:lb:global:0"), B("❓ RULES", callback_data="t31:rules")]])


def confirm_leave_kb(gid: int) -> M:
    return M([[B("✅ Yes, leave", callback_data=f"t31:lv:yes:{gid}"), B("↩ Keep playing", callback_data="t31:lv:no")]])


def result_kb(gid: int, rematch: bool = True) -> M:
    row = [B("🔁 Rematch", callback_data=f"t31:rm2:{gid}")] if rematch else []
    return M([row, [B("🔥 31 Menu", callback_data="cg:31"), B("🏠 Menu", callback_data="m:home")]] if row
             else [[B("🔥 31 Menu", callback_data="cg:31"), B("🏠 Menu", callback_data="m:home")]])


def lb_kb(kind: str, page: int, pages: int) -> M:
    tabs = [B(("• " if k == kind else "") + lab, callback_data=f"t31:lb:{k}:0") for k, lab in LB_TABS]
    nav = []
    if page > 0:
        nav.append(B("⬅ Previous", callback_data=f"t31:lb:{kind}:{page - 1}"))
    if page < pages - 1:
        nav.append(B("Next ➡", callback_data=f"t31:lb:{kind}:{page + 1}"))
    rows = [tabs[:2], tabs[2:]]
    if nav:
        rows.append(nav)
    rows.append([B("🔥 31 Menu", callback_data="cg:31")])
    return M(rows)


def history_kb(page: int, pages: int) -> M:
    nav = []
    if page > 0:
        nav.append(B("⬅ Previous", callback_data=f"t31:hist:{page - 1}"))
    if page < pages - 1:
        nav.append(B("Next ➡", callback_data=f"t31:hist:{page + 1}"))
    return M(([nav] if nav else []) + [[B("🔥 31 Menu", callback_data="cg:31")]])


# ---- admin configuration panel ---------------------------------------------------------
CONFIG_CHOICES = {
    "min_players": [2, 3, 4], "max_players": [2, 3, 4, 5, 6, 7], "start_lives": [1, 2, 3, 4, 5],
    "turn_timeout": [30, 45, 60, 90, 120], "knock_enabled": [True, False], "knock_penalty_extra": [0, 1],
    "auto_declare_31": [True, False], "instant_31_rule": ["lowest_loses", "all_others_lose"],
    "three_kind_enabled": [True, False], "tie_rule": ["all_lose", "none_lose", "high_card"],
    "points_rounds": [3, 5, 7, 10], "lives_mode_enabled": [True, False], "points_mode_enabled": [True, False],
}
CONFIG_LABELS = {
    "min_players": "Min players", "max_players": "Max players", "start_lives": "Starting lives",
    "turn_timeout": "Turn timeout (s)", "knock_enabled": "Knocking", "knock_penalty_extra": "Failed-knock extra lives",
    "auto_declare_31": "Auto-declare 31", "instant_31_rule": "Instant 31 rule", "three_kind_enabled": "Three of a kind = 30.5",
    "tie_rule": "Tie rule", "points_rounds": "Points-mode rounds", "lives_mode_enabled": "Lives mode",
    "points_mode_enabled": "Points mode",
}


def next_config_value(cfg: dict, key: str):
    """Cycle a setting to its next allowed value, keeping min <= max."""
    choices = CONFIG_CHOICES[key]
    cur = cfg.get(key)
    nxt = choices[(choices.index(cur) + 1) % len(choices)] if cur in choices else choices[0]
    new = {**cfg, key: nxt}
    if new.get("min_players", 2) > new.get("max_players", 7):
        if key == "min_players":
            new["max_players"] = new["min_players"]
        else:
            new["min_players"] = new["max_players"]
    return new


def _show(v) -> str:
    return "ON" if v is True else ("OFF" if v is False else str(v).replace("_", " "))


def config_kb(cfg: dict) -> M:
    rows = [[B(f"{CONFIG_LABELS[k]}: {_show(cfg.get(k))}", callback_data=f"t31c:{k}")] for k in CONFIG_CHOICES]
    rows.append([B("↩ Reset to defaults", callback_data="t31c:reset"), B("🏠 Menu", callback_data="m:home")])
    return M(rows)
