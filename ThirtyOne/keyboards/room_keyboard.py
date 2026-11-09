from urllib.parse import quote

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from config import settings


def mode_kb(prefix: str) -> M:
    """prefix: 'q' quick match, 'r:new' private room."""
    return M([[B("👤 1 vs 1", callback_data=f"{prefix}:2"), B("👥 2 vs 2 (teams)", callback_data=f"{prefix}:4")],
              [B("⬅ Back", callback_data="m:play")]])


def quick_kb() -> M:
    return M([[B("❌ Cancel search", callback_data="q:cancel")]])


def invite_link(code: str) -> str:
    return f"https://t.me/{settings.bot_username}?start=room_{code}"


def room_kb(room) -> M:
    link = invite_link(room.code)
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('Join my Thirty One Briscola room ' + room.code + ' 🃏')}"
    rows = [[B("🙋 Join", callback_data=f"r:join:{room.code}"), B("➕ Invite Friends", url=share)]]
    row = [B("🚀 Start Game", callback_data=f"r:start:{room.code}")]
    if not room.full:
        row.append(B("🤖 Fill with AI", callback_data=f"r:ai:{room.code}"))
    rows.append(row)
    rows.append([B("🔄 Refresh", callback_data=f"r:refresh:{room.code}"),
                 B("❌ Leave Room", callback_data=f"r:leave:{room.code}")])
    rows.append([B("🗑 Cancel Room (owner)", callback_data=f"r:cancel:{room.code}")])
    return M(rows)


def ai_level_kb() -> M:
    return M([[B("🟢 Easy", callback_data="a:lvl:easy"), B("🟡 Medium", callback_data="a:lvl:medium")],
              [B("🟠 Hard", callback_data="a:lvl:hard"), B("🔴 Expert", callback_data="a:lvl:expert")],
              [B("⬅ Back", callback_data="m:play")]])


def ai_mode_kb(level: str) -> M:
    return M([[B("👤 1 vs 1 AI", callback_data=f"a:go:{level}:2"),
               B("👥 You + AI vs 2 AI", callback_data=f"a:go:{level}:4")],
              [B("⬅ Back", callback_data="p:ai")]])
