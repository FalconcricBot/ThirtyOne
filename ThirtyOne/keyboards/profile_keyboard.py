from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M


def profile_kb() -> M:
    return M([[B("🏅 Achievements", callback_data="m:ach"), B("📜 History", callback_data="h:list:0")],
              [B("👥 Friends", callback_data="f:menu"), B("🏆 Rank list", callback_data="lb:global:0")],
              [B("🏠 Menu", callback_data="m:home")]])


CARD_STYLES = (("face", "🃏 Face"), ("arena", "🏟 Arena"), ("vip", "🎟 VIP"))


def settings_kb(p: dict, is_owner: bool = False) -> M:
    on = lambda v: "✅" if v else "❌"
    cur = p.get("profile_template", "face")
    styles = [B(("✅ " if k == cur else "") + label, callback_data=f"s:tpl:{k}") for k, label in CARD_STYLES]
    rows = [styles]
    if is_owner:                                           # the gold owner designs are owner-only
        rows.append([B(("✅ " if cur == "owner" else "") + "👑 Owner Pass", callback_data="s:tpl:owner"),
                     B(("✅ " if cur == "owner_card" else "") + "👑 Owner Card", callback_data="s:tpl:owner_card")])
    return M(rows + [[B("👁 Preview my profile card", callback_data="s:preview")],
              [B(f"{on(p['hand_images'])} Image hand (private chat)", callback_data="s:hand_images")],
              [B(f"{on(p['table_images'])} Image table (rooms you host)", callback_data="s:table_images")],
              [B(f"{on(p['notify'])} Turn notifications", callback_data="s:notify")],
              [B("🚫 Blocked players", callback_data="f:blocked")],
              [B("🏠 Menu", callback_data="m:home")]])


def history_kb(page: int, pages: int) -> M:
    nav = []
    if page > 0:
        nav.append(B("⬅ Previous", callback_data=f"h:list:{page - 1}"))
    if page < pages - 1:
        nav.append(B("Next ➡", callback_data=f"h:list:{page + 1}"))
    rows = [nav] if nav else []
    return M(rows + [[B("🏠 Menu", callback_data="m:home")]])
