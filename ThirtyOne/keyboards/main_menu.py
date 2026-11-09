from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M


def main_menu_kb() -> M:
    return M([
        [B("🃏 CARD GAMES", callback_data="m:games")],
        [B("🎮 PLAY", callback_data="m:play"), B("🏆 LEADERBOARD", callback_data="lb:global:0")],
        [B("👤 MY PROFILE", callback_data="m:profile"), B("🏟 TOURNAMENTS", callback_data="t:list")],
        [B("🎯 DAILY MISSIONS", callback_data="d:missions"), B("📜 GAME HISTORY", callback_data="h:list:0")],
        [B("👥 INVITE FRIENDS", callback_data="f:menu"), B("⚙️ SETTINGS", callback_data="s:menu")],
        [B("❓ HOW TO PLAY", callback_data="m:help")],
    ])


def play_menu_kb() -> M:
    return M([
        [B("⚡ Quick Match", callback_data="p:quick")],
        [B("👥 Create Private Room", callback_data="p:room"), B("🔑 Join Room", callback_data="p:join")],
        [B("🤖 Practice with AI", callback_data="p:ai"), B("🏆 Tournament", callback_data="t:list")],
        [B("👀 Watch Live Games", callback_data="sp:list")],
        [B("🏠 Menu", callback_data="m:home")],
    ])


def home_kb() -> M:
    return M([[B("🏠 Menu", callback_data="m:home")]])


def help_kb() -> M:
    return M([[B("📖 Full Rules", callback_data="m:rules"), B("🎮 Play", callback_data="m:play")],
              [B("🏠 Menu", callback_data="m:home")]])
