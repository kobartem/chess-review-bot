"""
Chess.com -> Telegram game reviewer.

Watches a chess.com account, analyzes new games with Stockfish and sends
a move-by-move review to a Telegram chat. Informal, approximate analysis:
see README for limitations.
"""
import asyncio
import html
import io
import math
import os

import cairosvg
import chess
import chess.engine
import chess.pgn
import chess.svg
import requests
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

load_dotenv()  # reads .env if present; must run before reading os.environ

# ------------------------------------------------------------------
# Config (all values come from environment variables / .env)
# ------------------------------------------------------------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
USER_TELEGRAM_ID = int(os.environ["TG_ID"])
CHESS_USERNAME = os.environ["CHESS_USERNAME"]
STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "stockfish")
ANALYSIS_DEPTH = int(os.environ.get("ANALYSIS_DEPTH", "16"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "30"))  # seconds
MAX_SESSIONS = 50  # finished reviews kept in memory

HEADERS = {"User-Agent": f"ChessBot/1.0 ({os.environ.get('CONTACT', 'github project')})"}

# ------------------------------------------------------------------
# Texts (BOT_LANG=en or BOT_LANG=uk)
# ------------------------------------------------------------------
TEXTS = {
    "en": {
        "labels": {
            "brilliant": "💎 Brilliant",
            "best": "⭐ Best",
            "excellent": "👍 Excellent",
            "good": "✅ Good",
            "inaccuracy": "⚠️ Inaccuracy",
            "mistake": "❓ Mistake",
            "blunder": "‼️ Blunder",
        },
        "best_was": "Best was {san}.",
        "missed_mate": "Missed mate in {n}. ",
        "allows_mate": "This move allows mate in {n}. ",
        "played_best": "\n🔴 played, 🟢 best",
        "open_link": "Open on chess.com",
        "accuracy": "Accuracy",
        "opponent": "opponent",
        "eval": "Eval",
        "prev": "◀️ Previous",
        "next": "Next ▶️",
        "all_moves": "📋 All moves",
        "menu": "🍄 Menu",
        "review_moves": "▶️ Review moves",
        "review_title": "🔔 <b>Game review</b>",
        "summary_title": "🍄 <b>Game summary</b>",
        "list_title": "📋 <b>Game {gid}</b>",
        "list_legend": "\n\n💎 brilliant  ⭐ best  ⚠️ inaccuracy  ❓ mistake  ‼️ blunder",
        "expired": "Session expired. Use /analyze <ID> to open this game again.",
        "help": (
            "<b>Commands</b>\n"
            "/last — analyze the latest game\n"
            "/games — last 10 games with IDs\n"
            "/analyze &lt;link or ID&gt; — analyze a specific game\n"
            "/help — this list\n\n"
            "New chess.com games are analyzed automatically."
        ),
        "fetching_last": "⏳ Fetching the latest game and analyzing...",
        "no_games": "No games found.",
        "error": "Error: {e}",
        "recent_games": "🗂 <b>Recent games</b>",
        "analyze_hint": "Analyze: /analyze &lt;ID&gt;",
        "usage": "Usage: /analyze &lt;link or game ID&gt;",
        "searching": "⏳ Looking up the game and analyzing...",
        "not_found": "Game not found in this account's archives.",
        "poll_error": "Polling error: {e}",
        "started": "Bot started, watching for new games...",
        "cmds": [
            ("last", "Analyze the latest game"),
            ("games", "Recent games with IDs"),
            ("analyze", "Analyze a game by ID or link"),
            ("help", "List of commands"),
        ],
    },
    "uk": {
        "labels": {
            "brilliant": "💎 Блискучий",
            "best": "⭐ Найкращий",
            "excellent": "👍 Відмінний",
            "good": "✅ Добрий",
            "inaccuracy": "⚠️ Неточність",
            "mistake": "❓ Помилка",
            "blunder": "‼️ Груба помилка",
        },
        "best_was": "Краще було {san}.",
        "missed_mate": "Пропущено мат у {n}. ",
        "allows_mate": "Цей хід веде до мату у {n}. ",
        "played_best": "\n🔴 зіграно, 🟢 краще",
        "open_link": "Відкрити на chess.com",
        "accuracy": "Accuracy",
        "opponent": "суперник",
        "eval": "Оцінка",
        "prev": "◀️ Попередня",
        "next": "Наступна ▶️",
        "all_moves": "📋 Усі ходи",
        "menu": "🍄 Меню",
        "review_moves": "▶️ До ходів",
        "review_title": "🔔 <b>Розбір гри</b>",
        "summary_title": "🍄 <b>Підсумок гри</b>",
        "list_title": "📋 <b>Гра {gid}</b>",
        "list_legend": "\n\n💎 блискучий  ⭐ найкращий  ⚠️ неточність  ❓ помилка  ‼️ груба помилка",
        "expired": "Сесія застаріла. Відкрий гру знову через /analyze <ID>.",
        "help": (
            "<b>Команди</b>\n"
            "/last — розібрати останню гру\n"
            "/games — останні 10 ігор з ID\n"
            "/analyze &lt;посилання або ID&gt; — розібрати конкретну гру\n"
            "/help — цей список\n\n"
            "Нові партії з chess.com бот розбирає автоматично."
        ),
        "fetching_last": "⏳ Беру останню гру й аналізую...",
        "no_games": "Ігор не знайдено.",
        "error": "Помилка: {e}",
        "recent_games": "🗂 <b>Останні ігри</b>",
        "analyze_hint": "Розбір: /analyze &lt;ID&gt;",
        "usage": "Використання: /analyze &lt;посилання або ID гри&gt;",
        "searching": "⏳ Шукаю гру й аналізую...",
        "not_found": "Гру не знайдено в архівах цього акаунта.",
        "poll_error": "Помилка фонового опитування: {e}",
        "started": "Бот запущений та моніторить ігри...",
        "cmds": [
            ("last", "Розібрати останню гру"),
            ("games", "Останні ігри з ID"),
            ("analyze", "Розібрати гру за ID або посиланням"),
            ("help", "Список команд"),
        ],
    },
}
LANG = os.environ.get("BOT_LANG", "en")
if LANG not in TEXTS:
    LANG = "en"
T = TEXTS[LANG]

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

MATE = 10000
PIECE_VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
BAD = ("inaccuracy", "mistake", "blunder")
LABELS = T["labels"]
ICONS = {
    "brilliant": "💎", "best": "⭐", "excellent": "", "good": "",
    "inaccuracy": "⚠️", "mistake": "❓", "blunder": "‼️",
}

# In-memory storage only: nothing is written to disk.
user_sessions = {}  # game_id -> analysis result


def game_id_from_url(url: str) -> str:
    return url.rstrip("/").split("?")[0].split("/")[-1]


def save_session(a):
    user_sessions[a["game_id"]] = a
    while len(user_sessions) > MAX_SESSIONS:
        user_sessions.pop(next(iter(user_sessions)))  # drop the oldest


def get_session(gid):
    return user_sessions.get(gid)


# ------------------------------------------------------------------
# Board
# ------------------------------------------------------------------
def generate_board_image(fen, last_move=None, arrows=(), flip=False) -> bytes:
    board = chess.Board(fen)
    arr = []
    for uci, color in arrows:
        m = chess.Move.from_uci(uci)
        arr.append(chess.svg.Arrow(m.from_square, m.to_square, color=color))
    svg = chess.svg.board(
        board,
        size=400,
        arrows=arr,
        lastmove=chess.Move.from_uci(last_move) if last_move else None,
        orientation=chess.BLACK if flip else chess.WHITE,
    )
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"))


# ------------------------------------------------------------------
# Analysis
# ------------------------------------------------------------------
def win_pct(cp):  # lichess formula
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_acc(drop):  # lichess per-move accuracy formula
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


def score_white(info, pos):
    if pos.is_checkmate():
        return -MATE if pos.turn == chess.WHITE else MATE
    if pos.is_game_over():
        return 0
    return info["score"].white().score(mate_score=MATE)


def fmt_eval(cp):
    if abs(cp) >= MATE - 500:
        return "M+" if cp > 0 else "M−"
    return f"{cp / 100:+.2f}"


def is_brilliant(pos, mv, wb, wa):
    # Heuristic: near-best move that sacrifices a piece while the position is still unsettled
    if wb > 85 or wa < 45 or wb - wa > 3:
        return False
    color = pos.turn
    piece = pos.piece_at(mv.from_square)
    if piece.piece_type in (chess.PAWN, chess.KING):
        return False
    cap = pos.piece_at(mv.to_square)
    gained = PIECE_VAL.get(cap.piece_type, 0) if cap else 0
    after = pos.copy()
    after.push(mv)
    attackers = after.attackers(not color, mv.to_square)
    if not attackers:
        return False
    cheapest = min(PIECE_VAL.get(after.piece_type_at(a), 100) for a in attackers)
    mine = PIECE_VAL[piece.piece_type]
    hanging = (not after.attackers(color, mv.to_square)) or cheapest < mine
    return hanging and mine > gained


def classify(drop, is_best, brilliant):
    if brilliant:
        return "brilliant"
    if drop >= 15:
        return "blunder"
    if drop >= 10:
        return "mistake"
    if drop >= 5:
        return "inaccuracy"
    if is_best:
        return "best"
    return "excellent" if drop <= 2 else "good"


def analyze_game(pgn_string: str, player_username: str):
    game = chess.pgn.read_game(io.StringIO(pgn_string))
    user_white = game.headers.get("White", "").lower() == player_username.lower()
    user_color = chess.WHITE if user_white else chess.BLACK
    moves = list(game.mainline_moves())

    board = game.board()
    positions = [board.copy()]
    for mv in moves:
        board.push(mv)
        positions.append(board.copy())

    limit = chess.engine.Limit(depth=ANALYSIS_DEPTH)
    with chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH) as engine:
        infos = [None if p.is_game_over() else engine.analyse(p, limit) for p in positions]
    evals = [score_white(i, p) for i, p in zip(infos, positions)]

    counts = dict.fromkeys(LABELS, 0)
    accs = {chess.WHITE: [], chess.BLACK: []}
    history = []

    for i, mv in enumerate(moves):
        pos = positions[i]
        color = pos.turn
        sign = 1 if color == chess.WHITE else -1
        wb, wa = win_pct(sign * evals[i]), win_pct(sign * evals[i + 1])
        drop = max(0.0, wb - wa)
        best = infos[i]["pv"][0]

        # If the position is still clearly winning after the move, don't penalize the label
        # (accuracy is still computed from the real drop)
        label_drop = 0.0 if wa >= 90 else drop
        label = classify(label_drop, mv == best, is_brilliant(pos, mv, wb, wa))
        accs[color].append(move_acc(drop))
        if color == user_color:
            counts[label] += 1

        expl = ""
        if label in BAD:
            expl = T["best_was"].format(san=pos.san(best))
            mate_b = infos[i]["score"].pov(color).mate()
            nxt = infos[i + 1]
            mate_a = nxt["score"].pov(color).mate() if nxt else None
            if mate_b and 0 < mate_b <= 5 and not (mate_a and mate_a > 0):
                expl = T["missed_mate"].format(n=mate_b) + expl
            elif mate_a and mate_a < 0 and -mate_a <= 5:
                expl = T["allows_mate"].format(n=-mate_a) + expl
            expl += T["played_best"]

        history.append({
            "fen_before": pos.fen(),
            "fen": positions[i + 1].fen(),
            "uci": mv.uci(),
            "best_uci": best.uci(),
            "san": pos.san(mv),
            "ply": i,
            "color": color,
            "label": label,
            "eval": fmt_eval(evals[i + 1]),
            "explanation": expl,
        })

    avg = lambda xs: round(sum(xs) / max(1, len(xs)), 1)
    h = game.headers
    url = h.get("Link", "")
    gid = game_id_from_url(url) if url else str(abs(hash(pgn_string)) % 10**10)
    return {
        "accuracy": avg(accs[user_color]),
        "opp_accuracy": avg(accs[not user_color]),
        "counts": counts,
        "history": history,
        "user_white": user_white,
        "game_id": gid,
        "url": url,
        "white": h.get("White", "?"),
        "black": h.get("Black", "?"),
        "result": h.get("Result", "*"),
    }


# ------------------------------------------------------------------
# Texts and keyboards
# ------------------------------------------------------------------
def summary_text(a):
    c = a["counts"]
    link = f'<a href="{a["url"]}">{T["open_link"]}</a>\n\n' if a["url"] else "\n"
    return (
        f"🆔 <code>{a['game_id']}</code>\n"
        f"{html.escape(a['white'])} — {html.escape(a['black'])} · {a['result']}\n"
        f"{link}"
        f"🎯 {T['accuracy']}: <b>{a['accuracy']}%</b> ({T['opponent']}: {a['opp_accuracy']}%)\n"
        f"💎 {c['brilliant']}  ⭐ {c['best']}  👍 {c['excellent']}  ✅ {c['good']}\n"
        f"⚠️ {c['inaccuracy']}  ❓ {c['mistake']}  ‼️ {c['blunder']}"
    )


def move_caption(m):
    dots = "." if m["color"] == chess.WHITE else "..."
    t = (f"<b>{m['ply'] // 2 + 1}{dots} {m['san']}</b> — {LABELS[m['label']]}\n"
         f"{T['eval']}: {m['eval']}")
    return t + ("\n" + m["explanation"] if m["explanation"] else "")


def get_navigation_keyboard(gid: str, idx: int, total: int):
    nav = []
    if idx > 0:
        nav.append(InlineKeyboardButton(text=T["prev"], callback_data=f"nav_{gid}_{idx - 1}"))
    if idx < total - 1:
        nav.append(InlineKeyboardButton(text=T["next"], callback_data=f"nav_{gid}_{idx + 1}"))
    rows = [nav] if nav else []
    rows.append([
        InlineKeyboardButton(text=T["all_moves"], callback_data=f"list_{gid}"),
        InlineKeyboardButton(text=T["menu"], callback_data=f"menu_{gid}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def start_keyboard(gid: str):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=T["review_moves"], callback_data=f"nav_{gid}_0"),
        InlineKeyboardButton(text=T["all_moves"], callback_data=f"list_{gid}"),
    ]])


def moves_text(a):
    out = []
    for m in a["history"]:
        if m["color"] == chess.WHITE:
            out.append(f"{m['ply'] // 2 + 1}.")
        out.append(f"{m['san']}{ICONS[m['label']]}")
    return " ".join(out)


async def send_review(a):
    save_session(a)
    img = generate_board_image(a["history"][-1]["fen"], flip=not a["user_white"])
    await bot.send_photo(
        USER_TELEGRAM_ID,
        BufferedInputFile(img, "board.png"),
        caption=T["review_title"] + "\n\n" + summary_text(a),
        reply_markup=start_keyboard(a["game_id"]),
    )


# ------------------------------------------------------------------
# Chess.com API
# ------------------------------------------------------------------
def fetch_recent_games():
    r = requests.get(
        f"https://api.chess.com/pub/player/{CHESS_USERNAME}/games/archives",
        headers=HEADERS, timeout=15,
    )
    r.raise_for_status()
    games = []
    for url in r.json().get("archives", [])[-2:]:  # 2 months, so games at month boundaries aren't lost
        g = requests.get(url, headers=HEADERS, timeout=15)
        g.raise_for_status()
        games += [x for x in g.json().get("games", []) if x.get("rules") == "chess" and "pgn" in x]
    return games


def find_game(gid: str):
    r = requests.get(
        f"https://api.chess.com/pub/player/{CHESS_USERNAME}/games/archives",
        headers=HEADERS, timeout=15,
    )
    r.raise_for_status()
    for url in reversed(r.json().get("archives", [])):
        g = requests.get(url, headers=HEADERS, timeout=15)
        g.raise_for_status()
        for x in g.json().get("games", []):
            if x.get("url", "").rstrip("/").endswith("/" + gid) and "pgn" in x:
                return x
    return None


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------
@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await message.answer(T["help"])


@dp.message(Command("last"))
async def cmd_last(message: types.Message):
    if message.from_user.id != USER_TELEGRAM_ID:
        return
    await message.answer(T["fetching_last"])
    try:
        games = await asyncio.to_thread(fetch_recent_games)
        if not games:
            return await message.answer(T["no_games"])
        g = games[-1]
        gid = game_id_from_url(g["url"])
        a = get_session(gid) or await asyncio.to_thread(analyze_game, g["pgn"], CHESS_USERNAME)
        await send_review(a)
    except Exception as e:
        await message.answer(T["error"].format(e=html.escape(str(e))))


@dp.message(Command("games"))
async def cmd_games(message: types.Message):
    if message.from_user.id != USER_TELEGRAM_ID:
        return
    try:
        games = await asyncio.to_thread(fetch_recent_games)
    except Exception as e:
        return await message.answer(T["error"].format(e=html.escape(str(e))))
    if not games:
        return await message.answer(T["no_games"])
    lines = []
    for g in games[-10:][::-1]:
        me = g["white"] if g["white"]["username"].lower() == CHESS_USERNAME.lower() else g["black"]
        opp = g["black"] if me is g["white"] else g["white"]
        lines.append(
            f"<code>{game_id_from_url(g['url'])}</code> · {g.get('time_class', '?')} · "
            f"{html.escape(opp['username'])} · {me['result']}"
        )
    await message.answer(
        T["recent_games"] + "\n\n" + "\n".join(lines) + "\n\n" + T["analyze_hint"]
    )


@dp.message(Command("analyze"))
async def cmd_analyze(message: types.Message, command: CommandObject):
    if message.from_user.id != USER_TELEGRAM_ID:
        return
    arg = (command.args or "").strip()
    gid = game_id_from_url(arg) if arg else ""
    if not gid.isdigit():
        return await message.answer(T["usage"])
    cached = get_session(gid)
    if cached:
        return await send_review(cached)
    await message.answer(T["searching"])
    try:
        game = await asyncio.to_thread(find_game, gid)
        if not game:
            return await message.answer(T["not_found"])
        a = await asyncio.to_thread(analyze_game, game["pgn"], CHESS_USERNAME)
        await send_review(a)
    except Exception as e:
        await message.answer(T["error"].format(e=html.escape(str(e))))


@dp.callback_query(F.data.startswith("menu_"))
async def handle_menu(cb: types.CallbackQuery):
    if cb.from_user.id != USER_TELEGRAM_ID:
        return await cb.answer()
    gid = cb.data.split("_", 1)[1]
    s = get_session(gid)
    if not s:
        return await cb.answer(T["expired"], show_alert=True)
    img = generate_board_image(s["history"][-1]["fen"], flip=not s["user_white"])
    await cb.message.edit_media(
        media=types.InputMediaPhoto(
            media=BufferedInputFile(img, "board.png"),
            caption=T["summary_title"] + "\n\n" + summary_text(s),
        ),
        reply_markup=start_keyboard(gid),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("list_"))
async def handle_list(cb: types.CallbackQuery):
    if cb.from_user.id != USER_TELEGRAM_ID:
        return await cb.answer()
    gid = cb.data.split("_", 1)[1]
    s = get_session(gid)
    if not s:
        return await cb.answer(T["expired"], show_alert=True)
    chunks, cur = [], ""
    for word in moves_text(s).split(" "):
        if len(cur) + len(word) > 3500:
            chunks.append(cur)
            cur = ""
        cur += word + " "
    chunks.append(cur)
    for i, ch in enumerate(chunks):
        tail = T["list_legend"] if i == len(chunks) - 1 else ""
        await cb.message.answer(
            T["list_title"].format(gid=gid) + "\n\n" + html.escape(ch.strip()) + tail
        )
    await cb.answer()


@dp.callback_query(F.data.startswith("nav_"))
async def handle_navigation(cb: types.CallbackQuery):
    if cb.from_user.id != USER_TELEGRAM_ID:
        return await cb.answer()
    _, gid, i = cb.data.split("_")
    s = get_session(gid)
    if not s:
        return await cb.answer(T["expired"], show_alert=True)
    idx = int(i)
    if not 0 <= idx < len(s["history"]):
        return await cb.answer()
    m = s["history"][idx]
    flip = not s["user_white"]
    if m["label"] in BAD:  # position BEFORE the move: red arrow = played, green = best
        img = generate_board_image(
            m["fen_before"], flip=flip,
            arrows=[(m["uci"], "#CC3333"), (m["best_uci"], "#15781B")],
        )
    else:
        img = generate_board_image(m["fen"], last_move=m["uci"], flip=flip)
    await cb.message.edit_media(
        media=types.InputMediaPhoto(media=BufferedInputFile(img, "board.png"), caption=move_caption(m)),
        reply_markup=get_navigation_keyboard(gid, idx, len(s["history"])),
    )
    await cb.answer()


# ------------------------------------------------------------------
# New game monitoring
# ------------------------------------------------------------------
async def auto_poll_chess_games():
    seen = None  # filled by the first successful fetch
    while True:
        try:
            games = await asyncio.to_thread(fetch_recent_games)
            if seen is None:
                # Startup: everything already in the archive counts as seen,
                # but the most recent game is analyzed once.
                seen = {g["url"] for g in games}
                if games:
                    a = await asyncio.to_thread(analyze_game, games[-1]["pgn"], CHESS_USERNAME)
                    await send_review(a)
            else:
                for g in games:
                    if g["url"] in seen:
                        continue
                    seen.add(g["url"])
                    a = await asyncio.to_thread(analyze_game, g["pgn"], CHESS_USERNAME)
                    await send_review(a)
        except Exception as e:
            print(T["poll_error"].format(e=e))
        await asyncio.sleep(POLL_INTERVAL)


async def main():
    try:
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in T["cmds"]])
        poll_task = asyncio.create_task(auto_poll_chess_games())
        print(T["started"])
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())