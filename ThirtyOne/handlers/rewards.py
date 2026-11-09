from telegram.ext import CallbackQueryHandler, CommandHandler

from keyboards.misc_keyboard import missions_kb
from services.rewards import DAILY_MISSIONS, MISSIONS, WEEKLY_MISSIONS, day_key, week_key
from ui import texts
from utils.decorators import ack, deps, guard, respond


async def show(update, context):
    c, uid = deps(context), update.effective_user.id
    p = await c.repo.get_player(uid)
    prog = await c.repo.mission_progress(uid, day_key(), week_key())
    ready = p["last_daily"] != day_key()
    claimable = [(k, MISSIONS[k][1]) for k in MISSIONS
                 if prog.get(k, (0, False))[0] >= MISSIONS[k][2] and not prog.get(k, (0, False))[1]]
    await respond(update, context, texts.missions_text(prog, ready, p["daily_streak"]), missions_kb(claimable, ready))


@guard()
async def missions_cmd(update, context):
    await show(update, context)


@guard()
async def rewards_cb(update, context):
    c, uid = deps(context), update.effective_user.id
    parts = update.callback_query.data.split(":")
    if parts[1] == "daily":
        r = await c.rewards.claim_daily(uid)
        await ack(update, f"🎁 Day {r['streak']} bonus: +{r['coins']} coins, +{r['xp']} XP" if r else "Already collected today.", True)
    elif parts[1] == "claim":
        r = await c.rewards.claim_mission(uid, parts[2])
        await ack(update, f"✅ {r['title']}: +{r['coins']} coins, +{r['xp']} XP" if r else "Nothing to claim.", True)
    else:
        await ack(update)
    await show(update, context)


def register(app) -> None:
    app.add_handler(CommandHandler("missions", missions_cmd))
    app.add_handler(CallbackQueryHandler(rewards_cb, pattern=r"^d:"))
