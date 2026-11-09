from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as M

LB_TABS = [("global", "🌍 Global"), ("week", "📅 Week"), ("month", "🗓 Month"), ("friends", "👥 Friends"),
           ("tour", "🏟 Tournament"), ("winpct", "📈 Win %"), ("streak", "🔥 Streak")]


def leaderboard_kb(kind: str, page: int, pages: int) -> M:
    tabs = [B(("• " if k == kind else "") + label, callback_data=f"lb:{k}:0") for k, label in LB_TABS]
    nav = []
    if page > 0:
        nav.append(B("⬅ Previous", callback_data=f"lb:{kind}:{page - 1}"))
    if page < pages - 1:
        nav.append(B("Next ➡", callback_data=f"lb:{kind}:{page + 1}"))
    rows = [tabs[:4], tabs[4:]]
    if nav:
        rows.append(nav)
    rows.append([B("🏠 Menu", callback_data="m:home")])
    return M(rows)


def missions_kb(claimable: list[tuple[str, str]], daily_ready: bool) -> M:
    rows = []
    if daily_ready:
        rows.append([B("🎁 Claim daily bonus", callback_data="d:daily")])
    for key, title in claimable:
        rows.append([B(f"✅ Claim: {title}", callback_data=f"d:claim:{key}")])
    rows.append([B("🏠 Menu", callback_data="m:home")])
    return M(rows)


def tournament_list_kb(items: list[dict]) -> M:
    rows = [[B(f"{'🔥' if t.get('game') == 'thirty_one' else '🃏'} {t['name'][:26]} ({t['players']}/{t['capacity']})",
               callback_data=f"t:view:{t['id']}")]
            for t in items]
    rows.append([B("🏆 Tournament leaderboard", callback_data="lb:tour:0")])
    rows.append([B("🏠 Menu", callback_data="m:home")])
    return M(rows)


def tournament_kb(t: dict, joined: bool, is_admin: bool) -> M:
    rows = []
    if t["status"] == "registration":
        rows.append([B("❌ Leave", callback_data=f"t:leave:{t['id']}") if joined
                     else B("✅ Register", callback_data=f"t:join:{t['id']}")])
        if is_admin:
            rows.append([B("▶ Start now", callback_data=f"t:start:{t['id']}"),
                         B("🛑 Cancel", callback_data=f"t:cancel:{t['id']}")])
    elif t["status"] == "running" and is_admin:
        rows.append([B("🛑 Cancel", callback_data=f"t:cancel:{t['id']}")])
    rows.append([B("🔄 Refresh", callback_data=f"t:view:{t['id']}"), B("⬅ List", callback_data="t:list")])
    return M(rows)


def friends_kb(friends: list[dict], pending: list[dict]) -> M:
    rows = [[B(f"✅ Accept {p['name'][:18]}", callback_data=f"f:accept:{p['id']}"),
             B("✖", callback_data=f"f:remove:{p['id']}")] for p in pending[:5]]
    for f in friends[:8]:
        rows.append([B(f"👤 {f['name'][:20]}", callback_data=f"f:view:{f['id']}")])
    rows.append([B("🔎 Search player", callback_data="f:search"), B("🕘 Recent opponents", callback_data="f:recent")])
    rows.append([B("🔗 My invite link", callback_data="f:link"), B("🏠 Menu", callback_data="m:home")])
    return M(rows)


def person_kb(uid: int, relation: str) -> M:
    rows = []
    if relation == "friend":
        rows.append([B("💔 Remove friend", callback_data=f"f:remove:{uid}")])
    elif relation == "none":
        rows.append([B("➕ Add friend", callback_data=f"f:add:{uid}")])
    rows.append([B("🚫 Block", callback_data=f"f:block:{uid}")])
    rows.append([B("⬅ Friends", callback_data="f:menu")])
    return M(rows)


def blocked_kb(blocked: list[dict]) -> M:
    rows = [[B(f"♻ Unblock {b['name'][:20]}", callback_data=f"f:unblock:{b['id']}")] for b in blocked]
    rows.append([B("⬅ Settings", callback_data="s:menu")])
    return M(rows)


def spectate_list_kb(items: list[tuple[int, str]]) -> M:
    rows = [[B(label[:40], callback_data=f"sp:{gid}")] for gid, label in items]
    rows.append([B("🏠 Menu", callback_data="m:home")])
    return M(rows)


def group_board_kb(active: str) -> M:
    return M([[B(("• " if active == "briscola" else "") + "🃏 Briscola", callback_data="gl:briscola"),
               B(("• " if active == "thirty_one" else "") + "🔥 31 Card Game", callback_data="gl:thirty_one")]])
