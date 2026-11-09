from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M


def admin_kb(maintenance: bool) -> M:
    return M([[B("📊 Stats", callback_data="ad:stats"), B("📜 Logs", callback_data="ad:logs")],
              [B("🏟 Tournaments", callback_data="t:list")],
              [B("🟢 Maintenance OFF" if maintenance else "🔧 Maintenance ON", callback_data="ad:maint")],
              [B("🏠 Menu", callback_data="m:home")]])
