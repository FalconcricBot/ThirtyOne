from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

from config import settings
from game.cards import card


def hand_kb(game_id: int, version: int, hand: list[str]) -> M:
    cards = [B(str(card(c)), callback_data=f"g:{game_id}:{version}:{c}") for c in hand]
    return M([cards, [B("📊 Score", callback_data=f"g:score:{game_id}"),
                      B("🏳 Leave match", callback_data=f"lv:{game_id}")]])


def table_kb(game_id: int) -> M:
    return M([[B("👀 Watch in DM", callback_data=f"sp:{game_id}")]])


def spectator_kb() -> M:
    return M([[B("❌ Stop watching", callback_data="sp:stop")]])


def confirm_leave_kb(game_id: int) -> M:
    return M([[B("✅ Yes, forfeit", callback_data=f"lv:yes:{game_id}"), B("↩ Keep playing", callback_data="lv:no")]])


def result_kb(game_id: int, rematch: bool = True) -> M:
    row = []
    if rematch:
        row.append(B("🔁 Rematch", callback_data=f"rm:{game_id}"))
    row.append(B("📜 Replay", callback_data=f"rp:{game_id}:0"))
    return M([row, [B("🎮 Play", callback_data="m:play"), B("🏠 Menu", callback_data="m:home")]])


def replay_kb(game_id: int, idx: int, total: int) -> M:
    nav = []
    if idx > 0:
        nav.append(B("⬅ Prev", callback_data=f"rp:{game_id}:{idx - 1}"))
    if idx < total - 1:
        nav.append(B("Next ➡", callback_data=f"rp:{game_id}:{idx + 1}"))
    return M([nav, [B("🏠 Menu", callback_data="m:home")]] if nav else [[B("🏠 Menu", callback_data="m:home")]])


def open_cards_kb() -> M:
    """Under the group turn-ping: jumps straight into the bot's private chat (and resends the hand)."""
    return M([[B("🃏 Open my cards", url=f"https://t.me/{settings.bot_username}?start=hand")]])
