"""Text for the 31 Card Game (Telegram HTML)."""
from __future__ import annotations

from game.thirty_one.cards import SYMBOL, label
from game.thirty_one.rules import ThirtyOneConfig
from utils.helpers import DIV, esc, fmt_num, header

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
MODE_NAME = {"lives": "Lives mode", "knockout": "Knockout (1 life)", "points": "Points mode"}


def games_menu_text() -> str:
    return "🎮 <b>SELECT YOUR GAME</b>\n\nTwo premium card games — one account, separate stats & rankings."


def menu_text(stats: dict) -> str:
    return (header("🔥", "31 CARD GAME", "Thirty-One") + "\n"
            f"🎮 Matches <b>{stats['matches']}</b> • ✅ <b>{stats['wins']}</b> wins • 🎯 31s <b>{stats['times_31']}</b>\n"
            f"⭐ 31 Rank points: <b>{fmt_num(stats['xp'])}</b>\n{DIV}\n"
            "Collect <b>31 points</b> with three cards of the <b>same suit</b>.")


def _on(v: bool) -> str:
    return "on" if v else "off"


def rules_text(cfg: ThirtyOneConfig) -> str:
    knock = "Knock to end the round — every other player gets one last turn." if cfg.knock_enabled else "Knocking is disabled."
    inst = ("everyone who doesn't hold 31 loses a life" if cfg.instant_31_rule == "all_others_lose"
            else "cards are scored normally and the lowest hand loses")
    tie = {"all_lose": "all tied lowest players lose", "none_lose": "nobody loses on a tie",
           "high_card": "the weaker high-card hand loses (still tied: all lose)"}[cfg.tie_rule]
    return ("📖 <b>31 CARD GAME — RULES</b>\n" + DIV + "\n"
            "🃏 52 cards, 3 cards each, one card face-up to start the discard pile.\n"
            "💯 A=11 • K/Q/J/10=10 • 9…2 = face value.\n"
            "🎯 Your score = the <b>best total of cards in ONE suit</b>. A+K+Q of ♥ = <b>31</b>.\n"
            + (f"🟰 Three of a kind counts <b>{cfg.three_kind_score:g}</b>.\n" if cfg.three_kind_enabled else "")
            + "\n<b>Your turn:</b> draw from the deck <i>or</i> take the top discard — then discard one card "
              "(not the one you just took).\n"
            f"✊ {knock}\n🎯 {'Reaching 31 ends the round immediately' if cfg.auto_declare_31 else 'Press DECLARE 31 when you hold 31'}: {inst}.\n\n"
            f"❤️ <b>Lives</b>: everyone starts with {cfg.start_lives}. Lowest hand loses a life"
            + (f" (a failed knock costs {cfg.knock_penalty_extra} extra)" if cfg.knock_penalty_extra else "")
            + f". Ties: {tie}. Last player standing wins.\n"
            f"💀 <b>Knockout</b>: 1 life. 🔢 <b>Points</b>: play {cfg.points_rounds} rounds, highest total wins.\n\n"
            f"⏱ <b>{cfg.turn_timeout}s per turn.</b> Miss one → your turn is skipped. Miss two in a row → you're removed from the match.")


def room_text(room, cfg: ThirtyOneConfig) -> str:
    mode = MODE_NAME[room.options.get("mode", "lives")]
    lines = [f"🔥 <b>31 CARD GAME ROOM</b>\n\n🔑 Room ID: <code>{room.code}</code>", f"🎮 Mode: <b>{mode}</b>",
             f"👥 Players: <b>{len(room.players)}/{room.mode}</b> (min {cfg.min_players})", "", "Players:"]
    for i in range(room.mode):
        if i < len(room.players):
            uid, name = room.players[i]
            lines.append(f"{i + 1}. {'👑' if uid == room.owner_id else ('🤖' if uid < 0 else '🟣')} {esc(name)}")
        else:
            lines.append(f"{i + 1}. 🟢 Waiting...")
    lines.append("\n💡 Start with 2+ players — add 🤖 AI to fill seats. Everyone must have started this bot privately.")
    return "\n".join(lines)


def _score_msg(score: float) -> str:
    if score >= 31:
        return "🎯 <b>31 points!</b>"
    if score >= 27:
        return "🔥 So close to 31!"
    return "Target: 31 (best suit)"


def hand_text(*, room: str, names: list[str], seat: int, view: dict, hand: list[str], score: float, last_action: str,
              deadline: int | None, show_table: bool, taken: str | None, can_declare_manual: bool) -> str:
    cfg_mode = view["mode"]
    lives = f"❤️ {view['lives'][seat]}" if cfg_mode != "points" else f"🔢 {view['totals'][seat]:g} pts"
    lines = [f"🔥 <b>31 CARD GAME</b> • <code>{room}</code>", DIV, "<b>YOUR CARDS:</b>",
             "  ".join(f"[ <b>{label(c)}</b> ]" for c in hand), "",
             f"YOUR CURRENT SCORE: <b>{score:g}</b>", _score_msg(score), DIV,
             f"{lives} • 📦 Deck {view['draw_count']} • 🗑 Top: <b>{label(view['discard_top']) if view['discard_top'] else '—'}</b>"]
    if show_table:
        lines.append("👥 " + " · ".join(f"{esc(names[s])} {view['lives'][s] if cfg_mode != 'points' else format(view['totals'][s], 'g')}"
                                        f"{'' if view['active'][s] else ' ✖'}" for s in range(len(names))))
    if last_action:
        lines.append(f"📝 {esc(last_action)}")
    if view["knocker"] is not None:
        lines.append(f"✊ <b>{esc(names[view['knocker']])} knocked!</b> Final turns running.")
    if view["phase"] in ("draw", "discard") and view["turn"] == seat:
        if view["phase"] == "draw":
            lines.append("\n▶ <b>YOUR TURN</b> — draw, take the discard" + (", knock" if True else "") + f"{' or declare 31' if can_declare_manual else ''}"
                         + (f" (⏱ {deadline}s)" if deadline else ""))
        else:
            lines.append("\n🗑 <b>Discard one card</b>" + (f" — you can't throw back {label(taken)}" if taken else "")
                         + (f" (⏱ {deadline}s)" if deadline else ""))
    elif view["phase"] == "between":
        lines.append("\n⏭ Next round starting…")
    else:
        lines.append(f"\n⏳ Waiting for <b>{esc(names[view['turn']])}</b>")
    return "\n".join(lines)


def table_text(*, room: str, names: list[str], view: dict, last_action: str, deadline: int | None,
               winner: str | None = None) -> str:
    n = len(names)
    pm = view["mode"] == "points"
    head = (header("🔥", "31 CARD GAME", "Live match")
            + f"\n🏠 Room: <code>{room}</code>  •  🎯 {MODE_NAME[view['mode']]}  •  Round {view['round_no']}\n{DIV}\n")
    rows = "\n".join(
        f"👤 {esc(names[s])} — " + (f"{view['totals'][s]:g} pts" if pm else (f"{view['lives'][s]} ❤️" if view['active'][s] else "💀 OUT"))
        + (" ✊" if view["knocker"] == s else "") for s in range(n))
    body = (f"\n{DIV}\n📦 Draw pile: <b>{view['draw_count']}</b> cards\n"
            f"🗑 Discard pile: <b>{view['discard_count']}</b> cards" + (f" (top {label(view['discard_top'])})" if view["discard_top"] else "") + "\n")
    if winner:
        tail = f"{DIV}\n🏁 <b>GAME OVER</b>\n{esc(winner)}"
    else:
        tail = f"{DIV}\n"
        if last_action:
            tail += f"📝 {esc(last_action)}\n"
        if view["knocker"] is not None:
            tail += f"✊ <b>{esc(names[view['knocker']])} knocked!</b>\n"
        tail += (f"⏳ Current turn: <b>{esc(names[view['turn']])}</b>" + (f" • {deadline}s" if deadline else "")) if view["phase"] != "between" else "⏭ Next round starting…"
    return head + rows + body + tail


def reason_line(info: dict, names: list[str], cfg: ThirtyOneConfig) -> str:
    t = esc(names[info["trigger"]])
    if info["reason"] == "declare31":
        base = f"🎯 <b>{t} has 31!</b>"
    else:
        base = f"✊ <b>{esc(names[info['knocker']])} knocked</b> — showdown!"
    if info["void"]:
        return base + "\n" + info["note"]
    if cfg.mode == "points":
        return base
    if info["losers"]:
        return base + "\n💔 " + ", ".join(f"{esc(names[s])} −{info['life_loss'][s]}❤️" for s in info["losers"] if info["life_loss"][s]) \
            + ("\n💀 Eliminated: " + ", ".join(esc(names[s]) for s in info["eliminated"]) if info["eliminated"] else "")
    return base + "\n🤝 Tie — nobody loses a life."


def standings_line(info: dict, names: list[str], cfg: ThirtyOneConfig) -> str:
    """Who has how many lives left (or the running point totals) after this round."""
    if cfg.mode == "points":
        return "🔢 <b>Totals:</b> " + " · ".join(f"{esc(names[s])} {info['totals'][s]:g}" for s in range(len(names)))
    return "❤️ <b>Lives left:</b> " + " · ".join(
        f"{esc(names[s])} {info['lives'][s] if info['lives'][s] > 0 else '💀'}" + ("" if info['lives'][s] <= 0 else " ❤️")
        for s in range(len(names)))


def round_caption(info: dict, names: list[str], cfg: ThirtyOneConfig, pause: int | None = None) -> str:
    """Short result (used under the reveal picture)."""
    out = f"🏁 <b>ROUND {info['no']} RESULT</b>\n{reason_line(info, names, cfg)}\n{DIV}\n{standings_line(info, names, cfg)}"
    return out + (f"\n\n⏭ Next round in {pause}s" if pause else "")


def reveal_text(info: dict, names: list[str], cfg: ThirtyOneConfig, pause: int | None = None) -> str:
    """Full text version (no pictures): everybody's cards and score, then the standings."""
    lines = [f"🏁 <b>ROUND {info['no']} RESULT</b>", reason_line(info, names, cfg), DIV]
    for s in range(len(names)):
        sc = info["scores"][s]
        if sc is None:
            lines.append(f"💀 {esc(names[s])} — out")
            continue
        mark = "💔" if s in info["losers"] and not info["void"] and cfg.mode != "points" else ("🎯" if sc >= 31 else "👤")
        lines.append(f"{mark} {esc(names[s])}: " + " ".join(label(c) for c in info["hands"][s]) + f" = <b>{sc:g}</b>")
    lines += [DIV, standings_line(info, names, cfg)]
    return "\n".join(lines) + (f"\n\n⏭ Next round in {pause}s" if pause else "")


def reveal_headline(info: dict, names: list[str], cfg: ThirtyOneConfig) -> str:
    """Plain (no HTML) one-liner for the reveal picture."""
    t = names[info["trigger"]]
    head = f"{t} has 31!" if info["reason"] == "declare31" else f"{names[info['knocker']]} knocked"
    if info["void"]:
        return head + " — no lives lost"
    if cfg.mode == "points":
        return head
    lost = [names[s] for s in info["losers"] if info["life_loss"][s]]
    return head + (" — " + ", ".join(lost) + " loses a life" if lost else " — tie, nobody loses")


def final_text(*, names: list[str], res: dict, cfg_mode: str, summary: dict | None, forfeit_names: list[str]) -> str:
    pl = res["placements"]
    order = sorted(range(len(names)), key=lambda s: (pl[s], s))
    lines = ["🏁 <b>GAME OVER</b>"]
    winners = res["winner_sides"]
    lines.append("🤝 <b>DRAW!</b>" if res["draw"] else f"🏆 <b>{esc(names[winners[0]])} WINS!</b>")
    if forfeit_names:
        lines.append(f"<i>{', '.join(esc(n) for n in forfeit_names)} left the match.</i>")
    lines.append(DIV)
    for s in order:
        score = f"{res['scores'][s]:g} pts" if cfg_mode == "points" else f"{res['scores'][s]} ❤️"
        lines.append(f"{MEDALS.get(pl[s], str(pl[s]) + '.')} {esc(names[s])} — {score}")
    if summary:
        verb = {"win": "🎉 You won!", "loss": "Good fight — rematch?", "draw": "You drew."}[summary["result"]]
        lines += [DIV, verb, f"⭐ +{summary['xp']} XP   💰 +{summary['coins']} coins"]
        if summary.get("level_up"):
            lines.append(f"🆙 <b>LEVEL UP → {summary['level_up'][0]}</b> (+{summary['level_up'][1]} coins)")
        for m in summary.get("missions_done", []):
            lines.append(f"🎯 Mission complete: <b>{esc(m)}</b>")
    return "\n".join(lines)


def stats_text(s: dict) -> str:
    pct = s["wins"] * 100 // s["matches"] if s["matches"] else 0
    return ("📊 <b>31 CARD GAME — MY STATS</b>\n" + DIV +
            f"\n🎮 Matches <b>{s['matches']}</b> • ✅ {s['wins']} • ❌ {s['losses']} • 🤝 {s['draws']} • {pct}% wins"
            f"\n🔁 Rounds played <b>{s['rounds']}</b>\n🎯 Times reached 31: <b>{s['times_31']}</b>"
            f"\n✊ Knock wins <b>{s['knock_wins']}</b> • Knock losses <b>{s['knock_losses']}</b>"
            f"\n💯 Best score <b>{s['best_score']:g}</b>\n🔥 Win streak {s['win_streak']} (best {s['best_streak']})"
            f"\n⭐ 31 rank points <b>{fmt_num(s['xp'])}</b>\n🤖 Practice matches {s['practice_matches']}")


def profile_line(s: dict) -> str:
    return f"🔥 31 Game: {s['matches']} matches • {s['wins']} wins • best {s['best_score']:g} • 31s {s['times_31']}"


LB_TITLES = {"global": "🌍 31 GLOBAL LEADERBOARD", "week": "📅 31 WEEKLY LEADERBOARD", "month": "🗓 31 MONTHLY LEADERBOARD",
             "friends": "👥 31 FRIENDS LEADERBOARD"}


def lb_text(kind: str, rows: list[dict], page: int, total: int, per_page: int, me: int) -> str:
    lines = [f"<b>{LB_TITLES[kind]}</b>", ""]
    if not rows:
        lines.append("Nobody here yet — win a 31 match to get on the board!")
    for i, r in enumerate(rows):
        pos = page * per_page + i + 1
        lines.append(f"{MEDALS.get(pos, f'{pos}.')} {esc(r['name'])} — {fmt_num(r['value'])} XP{' ← you' if r['id'] == me else ''}")
    lines.append(f"\nPage {page + 1}/{max(1, -(-total // per_page))}")
    return "\n".join(lines)


def history_text(rows: list[dict], page: int, total: int, per_page: int) -> str:
    lines = ["📜 <b>31 MATCH HISTORY</b>", ""]
    if not rows:
        lines.append("No 31 matches yet.")
    icon = {"win": "✅", "loss": "❌", "draw": "🤝"}
    for r in rows:
        lines.append(f"{icon[r['result']]} #{r['game_id']} • {r['at']:%d %b %H:%M} • {r['players']}P {r['mode']} {r['kind']} • "
                     f"#{r['placement']} place • {r['rounds']} rounds • ⭐+{r['xp']}")
    lines.append(f"\nPage {page + 1}/{max(1, -(-total // per_page))}")
    return "\n".join(lines)


def config_text(cfg: dict) -> str:
    return ("🛠 <b>31 GAME CONFIGURATION</b>\n" + DIV + "\nTap a setting to switch to its next value. Applies to NEW games.\n"
            "Fine control: <code>/t31set key value</code>  (e.g. <code>/t31set three_kind_score 30.5</code>)")
