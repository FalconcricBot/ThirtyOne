"""All user-facing text (Telegram HTML). Keep names HTML-escaped via esc()."""
from __future__ import annotations

from game.cards import card
from services.rewards import ACHIEVEMENTS, DAILY_MISSIONS, WEEKLY_MISSIONS
from services.statistics import level_for, rank_for
from utils.helpers import DIV, SUIT_LABELS, SUIT_SYMBOLS, bar, esc, fmt_num, header

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _c(code: str) -> str:
    return str(card(code))


def main_menu_text(p: dict, announcement: str = "") -> str:
    emoji, rank, *_ = rank_for(p["xp"])
    ann = f"\n📢 <i>{esc(announcement)}</i>\n" if announcement else ""
    return (header("🃏", "THIRTY ONE", "Premium card club") + "\n"
            f"👤 Player: <b>{esc(p['display_name'])}</b>\n{emoji} Rank: <b>{rank}</b> • Lv {level_for(p['xp'])}\n"
            f"⭐ XP: <b>{fmt_num(p['xp'])}</b>\n💰 Coins: <b>{fmt_num(p['coins'])}</b>\n{ann}\n{DIV}")


def help_text() -> str:
    return ("❓ <b>HOW TO PLAY</b>\n" + DIV + "\n"
            "1️⃣ Tap <b>PLAY</b> → Quick Match, Private Room or AI practice.\n"
            "2️⃣ Your cards arrive <b>privately</b> in this chat. Tap a card to play it.\n"
            "3️⃣ Highest card wins the trick; <b>Briscola (trump) beats everything</b>.\n"
            "4️⃣ Collect points: A=11 • 3=10 • K=4 • Q=3 • J=2. Total 120 — get 61+ to win.\n\n"
            "Commands: /menu /play /quickmatch /createroom /joinroom /hand /score /leaderboard "
            "/history /missions /tournaments /invite /settings /groupboard /rules /leave /cancel")


def rules_text() -> str:
    return ("📖 <b>BRISCOLA RULES</b>\n" + DIV + "\n"
            "• 40 cards: A 3 K Q J 7 6 5 4 2 in 4 suits.\n"
            "• Power order: <b>A &gt; 3 &gt; K &gt; Q &gt; J &gt; 7 &gt; 6 &gt; 5 &gt; 4 &gt; 2</b>\n"
            "• Points: A 11 • 3 10 • K 4 • Q 3 • J 2 • others 0 (120 total)\n"
            "• Everyone gets 3 cards. The bottom card of the deck shows the <b>Briscola</b> suit; "
            "the last player to draw takes it.\n"
            "• Each trick: every player plays one card. Any Briscola beats non-Briscola; "
            "otherwise the strongest card of the <b>led suit</b> wins. You are never forced to follow suit.\n"
            "• Winner collects the cards, draws first and leads next.\n"
            "• When the deck ends, play out your last cards.\n"
            "• 2 players: more than 60 points wins. 60-60 is a draw.\n"
            "• 4 players: seats 1+3 vs 2+4 — partners add their points together.")


def room_text(room, names_only: bool = False) -> str:
    lines = [f"🃏 <b>BRISCOLA ROOM</b>\n\n🔑 Room ID: <code>{room.code}</code>",
             f"🎮 Mode: <b>{'1 vs 1' if room.mode == 2 else '2 vs 2'}</b>", "", "Players:"]
    for i in range(room.mode):
        if i < len(room.players):
            uid, name = room.players[i]
            lines.append(f"{i + 1}. {'👑' if uid == room.owner_id else '🟣'} {esc(name)}")
        else:
            lines.append(f"{i + 1}. 🟢 Waiting...")
    if room.mode == 4:
        lines.append("\n<i>Seats 1+3 are Team A, seats 2+4 are Team B.</i>")
    lines.append("\n💡 Everyone must have started this bot privately to receive their cards.")
    return "\n".join(lines)


# ---------------------------------------------------------------- live game
def _plays(names, trick) -> str:
    return "\n".join(f"👤 {esc(names[s])}: <b>{_c(c)}</b>" for s, c in trick) or "—"


def _score_lines(names, scores, team_mode) -> str:
    if team_mode:
        return (f"Team A ({esc(names[0])} + {esc(names[2])}): <b>{scores[0]}</b>\n"
                f"Team B ({esc(names[1])} + {esc(names[3])}): <b>{scores[1]}</b>")
    return "\n".join(f"{esc(names[i])}: <b>{scores[i]}</b>" for i in range(len(names)))


def table_text(*, room: str, names: list[str], view: dict, last_trick: dict | None, deadline: int | None,
               winner: str | None = None) -> str:
    n = len(names)
    team = n == 4
    head = (header("🃏", "BRISCOLA", "Live match")
            + f"\n🏠 Room: <code>{room}</code>  •  🎮 {'2 vs 2' if team else '1 vs 1'}\n{DIV}\n")
    seats = "\n".join(f"👤 PLAYER {i + 1}: {esc(names[i])}" for i in range(n))
    tr = view["trump_card"]
    body = (f"\n{DIV}\n🃏 BRISCOLA: <b>{SUIT_LABELS[view['trump_suit']].upper()}</b>"
            + (f" ({_c(tr)})" if tr and view["stock_count"] > 0 else "")
            + f"\n📦 DECK: <b>{view['stock_count']}</b> CARDS\n{DIV}\n")
    if winner:
        mid = f"🏁 <b>GAME OVER</b>\n{esc(winner)}\n"
    else:
        mid = "CURRENT TRICK\n" + _plays(names, view["trick"]) + "\n"
        if not view["trick"] and last_trick:
            mid = (f"LAST TRICK → <b>{esc(names[last_trick['winner']])}</b> (+{last_trick['points']})\n"
                   + _plays(names, last_trick["plays"]) + "\n")
        mid += f"\n⏳ Turn: <b>{esc(names[view['turn']])}</b>" + (f" • {deadline}s" if deadline else "") + "\n"
    return head + seats + body + mid + f"{DIV}\n🏆 SCORE\n" + _score_lines(names, view["scores"], team)


def hand_text(*, room: str, names: list[str], seat: int, view: dict, hand: list[str], last_trick: dict | None,
              deadline: int | None, show_table: bool) -> str:
    team = len(names) == 4
    mine = view["scores"][seat % 2 if team else seat]
    other = [s for i, s in enumerate(view["scores"]) if i != (seat % 2 if team else seat)]
    t = view["trump_card"]
    lines = [f"🃏 <b>YOUR HAND</b> • <code>{room}</code>", DIV,
             "  ".join(f"[ <b>{_c(c)}</b> ]" for c in hand) or "(no cards)", DIV,
             f"🃏 Briscola: <b>{SUIT_LABELS[view['trump_suit']]}</b>" + (f" ({_c(t)})" if t and view["stock_count"] > 0 else ""),
             f"🏆 Score: <b>{mine}</b> – {' / '.join(map(str, other))}   📦 Deck: {view['stock_count']}"]
    if show_table:
        tr = " · ".join(f"{esc(names[s])} {_c(c)}" for s, c in view["trick"]) or "—"
        lines.append(f"🎴 Table: {tr}")
        if last_trick and not view["trick"]:
            lines.append(f"↩ Last: {esc(names[last_trick['winner']])} won +{last_trick['points']}")
    if view["turn"] == seat:
        lines.append("\n▶ <b>YOUR TURN</b> — select a card" + (f" (⏱ {deadline}s)" if deadline else ""))
    else:
        lines.append(f"\n⏳ Waiting for <b>{esc(names[view['turn']])}</b>")
    return "\n".join(lines)


def result_text(*, names, game_result: dict, seat: int | None, team_mode: bool, summary: dict | None,
                forfeit_name: str | None) -> str:
    sc = game_result["scores"]
    if game_result["draw"]:
        head = "🤝 <b>DRAW!</b>"
    else:
        ws = game_result["winner_sides"][0]
        if team_mode:
            head = f"🏆 <b>TEAM {'AB'[ws]} WINS!</b> ({esc(names[ws])} & {esc(names[ws + 2])})"
        else:
            head = f"🏆 <b>{esc(names[ws])} WINS!</b>"
    lines = [f"🏁 <b>GAME OVER</b>\n{head}"]
    if forfeit_name:
        lines.append(f"<i>{esc(forfeit_name)} left the match.</i>")
    lines += [DIV, _score_lines(names, sc, team_mode)]
    if summary:
        verb = {"win": "🎉 You won!", "loss": "You lost — good fight!", "draw": "You drew."}[summary["result"]]
        lines += [DIV, verb, f"⭐ +{summary['xp']} XP   💰 +{summary['coins']} coins"]
        if summary.get("level_up"):
            lines.append(f"🆙 <b>LEVEL UP → {summary['level_up'][0]}</b> (+{summary['level_up'][1]} coins)")
        for code in summary.get("achievements", []):
            e, t, _ = ACHIEVEMENTS[code]
            lines.append(f"{e} Achievement: <b>{t}</b> (+50 coins)")
        for m in summary.get("missions_done", []):
            lines.append(f"🎯 Mission complete: <b>{esc(m)}</b> — claim it in /missions")
    return "\n".join(lines)


# ---------------------------------------------------------------- profile etc.
def profile_text(p: dict, achievements: list[str], s31: dict | None = None) -> str:
    emoji, rank, floor, nxt = rank_for(p["xp"])
    pct = p["wins"] * 100 / p["matches"] if p["matches"] else 0
    ach = " ".join(ACHIEVEMENTS[a][0] for a in achievements if a in ACHIEVEMENTS) or "—"
    return (f"👤 <b>{esc(p['display_name'])}</b>" + (f" (@{esc(p['username'])})" if p["username"] else "") + "\n"
            f"🆔 Player ID: <code>#{p['player_no']}</code>\n📅 Joined: {p['created_at']:%d %b %Y}\n{DIV}\n"
            f"{emoji} <b>{rank}</b> • Level {level_for(p['xp'])}\n⭐ XP {fmt_num(p['xp'])}"
            + (f" / {fmt_num(nxt)}  {bar(p['xp'] - floor, nxt - floor)}" if nxt else " (MAX)") + f"\n💰 Coins {fmt_num(p['coins'])}\n{DIV}\n"
            f"🎮 Matches {p['matches']} • ✅ {p['wins']} • ❌ {p['losses']} • 🤝 {p['draws']}\n"
            f"📈 Win rate {pct:.0f}% • 🔥 Streak {p['win_streak']} (best {p['best_streak']})\n"
            f"🎯 Points {fmt_num(p['total_points'])} • Best score {p['highest_score']}\n"
            f"🏟 Tournament wins {p['tournament_wins']}\n"
            + (f"🔥 31 Game: {s31['matches']} matches • {s31['wins']} wins • best {s31['best_score']:g} • 31s {s31['times_31']}\n" if s31 else "")
            + f"{DIV}\n🏅 {ach}")


def achievements_text(unlocked: list[str]) -> str:
    lines = ["🏅 <b>ACHIEVEMENTS</b>", DIV]
    for code, (e, t, d) in ACHIEVEMENTS.items():
        lines.append(f"{e if code in unlocked else '🔒'} <b>{t}</b> — {d}")
    return "\n".join(lines)


LB_TITLES = {"global": "🌍 GLOBAL LEADERBOARD", "week": "📅 WEEKLY LEADERBOARD", "month": "🗓 MONTHLY LEADERBOARD",
             "friends": "👥 FRIENDS LEADERBOARD", "tour": "🏟 TOURNAMENT CHAMPIONS",
             "winpct": "📈 HIGHEST WIN % (min 10 games)", "streak": "🔥 LONGEST WIN STREAK"}
LB_UNIT = {"global": "XP", "week": "XP", "month": "XP", "friends": "XP", "tour": "titles", "winpct": "%", "streak": "wins"}


def leaderboard_text(kind: str, rows: list[dict], page: int, total: int, per_page: int, me: int) -> str:
    lines = [f"<b>{LB_TITLES[kind]}</b>", ""]
    if not rows:
        lines.append("Nobody here yet — be the first!")
    for i, r in enumerate(rows):
        pos = page * per_page + i + 1
        val = f"{r['value']:.0f}" if kind == "winpct" else fmt_num(r["value"])
        mark = " ← you" if r["id"] == me else ""
        lines.append(f"{MEDALS.get(pos, f'{pos}.')} {esc(r['name'])} — {val} {LB_UNIT[kind]}{mark}")
    pages = max(1, -(-total // per_page))
    lines.append(f"\nPage {page + 1}/{pages}")
    return "\n".join(lines)


def history_text(rows: list[dict], page: int, total: int, per_page: int) -> str:
    lines = ["📜 <b>GAME HISTORY</b>", ""]
    if not rows:
        lines.append("No games yet. Tap PLAY!")
    icon = {"win": "✅", "loss": "❌", "draw": "🤝"}
    for r in rows:
        lines.append(f"{icon[r['result']]} #{r['game_id']} • {r['at']:%d %b %H:%M} • {r['mode']}P {r['kind']} • "
                     f"{r['points']} pts • vs {esc(r['opponents'] or 'AI')}\n   /replay_{r['game_id']}  ⭐+{r['xp']}")
    lines.append(f"\nPage {page + 1}/{max(1, -(-total // per_page))}")
    return "\n".join(lines)


def missions_text(progress: dict, daily_ready: bool, streak: int) -> str:
    lines = ["🎯 <b>MISSIONS</b>", DIV]
    lines.append(("🎁 Daily bonus ready!" if daily_ready else "✅ Daily bonus collected") + f" • login streak {streak}🔥")
    for title, items in (("\n<b>Daily</b>", DAILY_MISSIONS), ("\n<b>Weekly</b>", WEEKLY_MISSIONS)):
        lines.append(title)
        for key, name, target, _m, coins, xp in items:
            prog, claimed = progress.get(key, (0, False))
            prog = min(prog, target)
            state = "✔ claimed" if claimed else ("🎁 ready" if prog >= target else f"{prog}/{target}")
            lines.append(f"{'✅' if prog >= target else '▫️'} {name} {bar(prog, target, 6)} {state}  (+{coins}💰 +{xp}⭐)")
    return "\n".join(lines)


def tournament_text(t: dict, players: list[dict], names: dict[int, str] | None = None) -> str:
    icon = {"registration": "📝 Registration open", "running": "⚔ In progress", "finished": "🏁 Finished",
            "cancelled": "❌ Cancelled"}[t["status"]]
    game = "🔥 31 Card Game" if t.get("game") == "thirty_one" else "🃏 Briscola"
    lines = [f"🏟 <b>{esc(t['name'])}</b>  #{t['id']}", f"{game} • {icon}", esc(t["description"]) if t["description"] else "", DIV,
             f"👥 Players: {t['players']}/{t['capacity']}",
             f"⏰ Register until: {t['register_until']:%d %b %H:%M} UTC", f"▶ Starts: {t['starts_at']:%d %b %H:%M} UTC"]
    if t["status"] == "finished" and t["winner_id"]:
        lines.append(f"👑 Champion: <b>{esc((names or {}).get(t['winner_id'], str(t['winner_id'])))}</b>")
    if t["bracket"] and names:
        from services.tournament import round_name
        for r, rnd in enumerate(t["bracket"]["rounds"]):
            lines.append(f"\n<b>{round_name(t['bracket'], r)}</b>")
            for m in rnd:
                a, b = names.get(m["a"], "TBD") if m["a"] else "TBD", names.get(m["b"], "TBD") if m["b"] else "bye"
                if m["a"] is None and m["b"] is None:
                    a, b = "TBD", "TBD"
                w = f" → 🏆 {esc(names.get(m['winner'], '?'))}" if m["winner"] else ""
                lines.append(f"• {esc(a)} vs {esc(b)}{w}")
    elif players:
        lines.append("\n" + ", ".join(esc(p["name"]) for p in players[:30]))
    return "\n".join(l for l in lines if l is not None)


def group_board_text(title: str, game: str, rows: list[dict], me: int) -> str:
    name = "🔥 31 Card Game" if game == "thirty_one" else "🃏 Briscola"
    lines = [f"🏆 <b>{esc(title or 'This group')}</b> — group leaderboard", f"<i>{name} • matches played in this group</i>", DIV]
    if not rows:
        lines.append("No matches yet — start one here with /thirtyone or /createroom!")
    for i, r in enumerate(rows, 1):
        lines.append(f"{MEDALS.get(i, f'{i}.')} {esc(r['name'])} — <b>{fmt_num(r['xp'])}</b> XP • {r['wins']}/{r['games']} wins"
                     + (" ← you" if r["id"] == me else ""))
    return "\n".join(lines)
