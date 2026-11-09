# 🃏 Thirty One (@Deck31Bot)

**Thirty One** — premium multiplayer card games inside Telegram (**Briscola** and **31 Card Game**) — messages, inline buttons and images only (no Mini App, no website).
2-player and 4-player (2 vs 2) matches, private rooms, quick match, AI practice, tournaments, profiles, leaderboards,
missions, friends and an admin panel. Python 3.11+, python-telegram-bot 21+, SQLAlchemy 2 (SQLite or PostgreSQL),
Alembic, Pillow, Docker.

## How the game works in Telegram
* Your cards arrive **privately** in your chat with the bot (as an image or text — your choice in ⚙️ Settings).
  Card buttons only work for the player who owns that hand. Server-side validation + a move counter reject
  wrong turns, foreign cards and double-taps.
* In a **group**, one live table message (image or text) is edited after every move.
* Games are saved after every move. After a crash/restart the bot reloads unfinished matches and resends hands.

## Project layout
```
main.py  config.py  alembic.ini  Dockerfile  docker-compose.yml  .env.example
game/        Briscola engine (deck, cards, rules, scoring, state, engine, ai) + thirty_one/ (31 Card Game engine & AI)
             game/briscola/ is an alias package for the Briscola modules
database/    models, database (engine), repository, migrations/ (Alembic)
services/    game_manager (live matches, timers, AI, recovery), matchmaking (rooms+queue),
             tournament (knockout brackets), rewards, statistics, notifications
handlers/    start menu profile game matchmaking room leaderboard tournament rewards friends admin
keyboards/   inline keyboards          ui/  images.py (Pillow) + texts.py
utils/       logger validators helpers decorators      tests/   61 tests
```

## 1. Local setup on Windows + VS Code
1. Install Python 3.11+ from python.org (tick **Add to PATH**), and VS Code with the Python extension.
2. Open the project folder in VS Code → terminal:
   ```
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   ```
3. Create the bot: in Telegram open **@BotFather** → `/newbot` → name `Thirty One`, username `Deck31Bot`
   (must end in *bot*; pick another if taken and set `BOT_USERNAME`). Copy the token into `.env` as `BOT_TOKEN`.
4. Optional BotFather polish: `/setdescription`, `/setabouttext`, `/setuserpic`. For group play keep
   **Group Privacy ON** (default) — the bot only needs commands. The command menu is set automatically at startup.
5. Put your numeric Telegram ID(s) in `ADMIN_IDS` (get it from @userinfobot), comma-separated.
6. Run: `python main.py` → send `/start` to your bot.

## 🔥 31 Card Game (Thirty-One)
Open it from **🃏 CARD GAMES → 🔥 31 CARD GAME** (or `/thirtyone`). It is a second, fully separate game inside the
same bot: own engine (`game/thirty_one/`), rules, statistics, history and leaderboards; shared player profile
(XP/coins/level), friends, lobby, notifications and tournaments.
* 52 cards, 3 each, one card face-up. Score = best total of cards in **one suit** (A=11, K/Q/J/10=10). Turn: draw
  *or* take the top discard, then discard one (never the card you just took). **Knock** = everyone else gets one last turn.
  Reaching **31** ends the round. Optional **three of a kind = 30.5**.
* Modes: ❤️ Lives (default 3), 💀 Knockout (1 life), 🔢 Points (fixed number of rounds), 2–7 players, quick match,
  private rooms (`31-12345`, deep link, group or private), friends, AI practice (easy/medium/hard/expert), rematch,
  tournaments (`/create_tournament31 Name | capacity | start_min | deadline_min | description`, 1v1 knockout bracket).
* **Turn ping in groups (both games):** when it is a player's turn the bot posts a message that tags them
  (`tg://user?id=…` mention → real notification) with a **🃏 Open my cards** button that opens the bot chat via
  `t.me/<bot>?start=hand` (resends the hand if the old message was lost). The previous ping is deleted each turn, so the
  group stays clean. Players with turn notifications off are named without a tag. If the group message fails, a DM ping is used.
* Premium visuals: private hand image with a score gauge (cards that count glow gold, the picked-up card is tagged NEW),
  live table image (lives as neon hearts, piles, KNOCK badge), and a reveal image after every round.
  Names/emoji/Hindi render exactly like in Telegram. Images are optional (⚙️ Settings); text mode always works.
* Admin: `/t31config` (tap-to-cycle panel) or `/t31set <key> <value>`: min/max players, starting lives, turn timeout, knock
  on/off + failed-knock penalty, instant-31 rule (`lowest_loses` | `all_others_lose`), auto-declare, three-of-a-kind
  scoring, tie rule (`all_lose` | `none_lose` | `high_card`), points rounds, lives/points mode on/off. New games use the new values.
* Database: tables `thirty_one_games/players/moves/rounds/statistics/game_history` + `tournaments.game`
  (migration `0003`; also applied automatically at startup). Unfinished matches are persisted after every action and
  reloaded after a restart. Private cards are never written to chat messages or to the moves table (drawn cards are not logged).
* Tests: `tests/test_thirty_one.py` (engine) and `tests/test_thirty_one_manager.py` (live flow with a fake bot).
  Strength check: `python benchmark_31.py`.

## Extras
* **Flood protection:** more than 12 actions in 6 s from one user are ignored (one polite warning; admins exempt) — stops button-mashing from loading the bot.
* **Admin error alerts:** `ERROR` log lines are collected and DM'd to every `ADMIN_IDS` user (merged, token-masked, max one alert / 5 min). Details: `/logs`.
* **31 missions:** daily *Play 2 matches of 31* and *Reach 31 in a 31 match*, weekly *Win 5 matches of 31* (practice never counts for wins/31s). See `/missions`.
* **Group leaderboard:** `/groupboard` inside a group ranks the players who played matches *in that group* (tabs: Briscola / 31).

## Profile cards (3 styles)
`/profile` shows a game-style image card with the player's real Telegram photo, name and @username exactly as in
Telegram (Latin, Hindi/Devanagari, Cyrillic, colour emoji). Players pick **Face Card / Arena / VIP Pass** in
⚙️ Settings (👁 Preview shows it instantly). Hindi needs Pillow's Raqm layout: it is included in the Docker image
(`libraqm0`); on a Linux VPS run `apt install libraqm0`; Windows/macOS Pillow wheels already bundle it.
The bot logs a warning at startup if Raqm is missing.
**Owner card:** the bot owner (`OWNER_IDS`, or the only admin) gets two exclusive black-&-gold designs — *Owner Pass* (landscape) and
*Owner Card* (portrait king card) with crown, sunburst and gold-gradient name; chosen in ⚙️ Settings (extra buttons only the owner sees). `python make_demo_cards.py out_dir` renders demo cards.

## 2. Database
* **SQLite (default):** `DATABASE_URL=sqlite+aiosqlite:///briscola.db` — nothing to install; WAL mode is enabled.
* **PostgreSQL (production):** `DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/briscola`
  (hosts that give `postgres://…` are converted automatically).
* **Migrations:** `alembic upgrade head` creates/updates the schema (the Docker image runs it on every start).
  After changing `database/models.py`: `alembic revision --autogenerate -m "what changed"`.
  The bot also creates missing tables/columns on startup, so `python main.py` works without running Alembic first
  (migration `0002` adds the profile-card style column and is safe to run on a fresh or existing database).

## 3. Docker / VPS (runs 24/7 even when your laptop is off)
```
cp .env.example .env        # fill BOT_TOKEN, ADMIN_IDS, POSTGRES_PASSWORD
docker compose up -d --build
docker compose logs -f bot
```
Any small VPS (1 vCPU / 1 GB) is enough for hundreds of concurrent matches. Update: `git pull && docker compose up -d --build`.
Without Docker on a Linux VPS, use a systemd unit:
```
[Service]
WorkingDirectory=/opt/ThirtyOne
ExecStart=/opt/ThirtyOne/.venv/bin/python main.py
Restart=always
```
**Free hosting:** the bot uses long polling and must stay awake. Platforms that put free apps to sleep will make it
unresponsive. Oracle Cloud "Always Free" VMs or a small paid plan on Railway / Render / Fly.io / Hetzner work well;
free tiers change often, so check current terms. Use PostgreSQL (or a persistent volume for SQLite) so data survives redeploys.
Only run **one** instance per token (two instances cause a `Conflict` error).

## 4. Restart & recovery
* Crash, deploy or reboot → `restart: unless-stopped` / systemd restarts the bot → unfinished matches are reloaded
  from the database, players get a fresh hand message ("♻️ The bot restarted"), turn timers restart.
* Lost your hand message? `/hand`. Old buttons are rejected safely and refresh your hand.
* Rooms and quick-match searches are short-lived and are *not* persisted (players just create/search again).
* Logs: `logs/bot.log` (also `/logs` for admins). Back up the database regularly (`pg_dump` / copy the `.db` file).

## 5. Admin commands
`/admin /stats /playerinfo <id|@user> /ban <id> [reason] /unban /announcement <text|off> /maintenance on|off
/broadcast <text> /create_tournament Name | capacity | start_min | deadline_min | description
/end_tournament <id> /remove_player <tournament_id> <user> /logs`

## 6. Settings (.env)
`TURN_TIMEOUT` (seconds, default 45) • `TIMEOUT_POLICY` = `auto_play` | `forfeit` • `AFK_STRIKES_LIMIT` (default 2) •
(**31 game:** no auto-play ever — a missed turn is *skipped* (cards unchanged), `AFK_STRIKES_LIMIT` misses in a row remove the player;
`TIMEOUT_POLICY=forfeit` removes on the first miss. Briscola keeps auto-play because a trick cannot be skipped.) •
`TRUMP_MODE` = `bottom_card` (traditional) | `random_suit` • `ROOM_TTL_MINUTES` • `DEFAULT_IMAGES` = 1|0

## 7. Tests
`python -m unittest discover -s tests -t . -v` (no extra packages needed; `pytest` also works).
`python benchmark_ai.py` compares AI levels.

## Rules implemented
40 cards (no 8/9/10) • power A>3>K>Q>J>7>6>5>4>2 • points A11 3→10 K4 Q3 J2 (120 total) • 3 cards each •
bottom card shows the Briscola, last drawer takes it • trump beats all, otherwise highest of led suit wins, no obligation to follow suit •
winner draws first and leads • more than 60 wins, 60-60 draw • 4 players: seats 1+3 vs 2+4, points are pooled.
