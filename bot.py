import os
import random
import re
import time
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, filters)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")

print("TELEGRAM_TOKEN =", TELEGRAM_TOKEN)
print("TMDB_API_KEY =", TMDB_API_KEY)
print("OMDB_API_KEY =", OMDB_API_KEY)
print("PORT =", os.getenv("PORT"))
print("WEBHOOK_URL =", os.getenv("WEBHOOK_URL"))
# logging.basicConfig(level=logging.DEBUG)

# Стейты
GENRES, ACTORS, YEARS = range(3)

# Логгинг
logging.basicConfig(level=logging.DEBUG)

cached_genres = {}

def build_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎞 Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("🎭 Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("📅 Указать год/период", callback_data="years")],
        [InlineKeyboardButton("🔄 Сбросить фильтры", callback_data="reset")],
        [InlineKeyboardButton("🔎 Найти фильмы", callback_data="search")],
    ])

def build_movie_keyboard(movie_id, index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u27a1 Далее", callback_data=f"next|{index+1}")],
        [InlineKeyboardButton("\U0001F39E Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("\U0001F3AD Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("\U0001F50E Найти фильмы", callback_data="search")],
        [InlineKeyboardButton("\u274C Сбросить фильтры", callback_data="reset")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет <3 Что хочешь сделать?", reply_markup=build_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "genres":
        await query.message.reply_text("Введи жанры через запятую")
        return GENRES
    elif data == "actors":
        await query.message.reply_text("Введи имена актёров через запятую")
        return ACTORS
    elif data == "years":
        await query.message.reply_text("Введи год или диапазон годов через дефис. Например:\n2023\n2020-2023")
        return YEARS
    elif data == "reset":
        context.user_data.clear()
        await query.message.reply_text("Фильтры сброшены", reply_markup=build_keyboard())
        return ConversationHandler.END
    elif data == "search":
        await search_movies(update, context)
    elif data.startswith("desc|"):
        movie_id = data.split("|")[1]
        await send_description(update, context, movie_id)
    elif data.startswith("next|"):
        index = int(data.split("|")[1])
        await send_movie(update, context, index)

    return ConversationHandler.END

async def genres_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["genres"] = update.message.text
    await update.message.reply_text("Жанры сохранены", reply_markup=build_keyboard())
    return ConversationHandler.END

async def actors_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["actors"] = update.message.text
    await update.message.reply_text("Актёры сохранены", reply_markup=build_keyboard())
    return ConversationHandler.END

async def years_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["years"] = text
    await update.message.reply_text(f"Год(ы) сохранены: {text}", reply_markup=build_keyboard())
    return ConversationHandler.END

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    genres = context.user_data.get("genres", "")
    actors = context.user_data.get("actors", "")
    years  = context.user_data.get("years", "")

    genre_ids = get_genre_ids(genres)
    actor_ids = get_actor_ids(actors)

    base_params = {
        "api_key": TMDB_API_KEY,
        "language": "ru",
        "sort_by": "popularity.desc",
        "vote_average.gte": 8,
    }
    if genre_ids:
        base_params["with_genres"] = ",".join(map(str, genre_ids))
    if actor_ids:
        base_params["with_cast"] = ",".join(map(str, actor_ids))
    if years:
        # твоя логика разбора years → primary_release_date.gte/​lte
        # например:
        start, end = parse_years(years)
        base_params["primary_release_date.gte"] = f"{start}-01-01"
        base_params["primary_release_date.lte"] = f"{end}-12-31"

    url = "https://api.themoviedb.org/3/discover/movie"
    found = []
    # Перебираем до 5 страниц, чтобы найти хотя бы один фильм с IMDb ≥ 8.0
    for page in range(1, 10):
        params = dict(base_params, page=page)
        logging.debug(f"[TMDb] discover page={page} params={params}")
        resp = requests.get(url, params=params)
        data = resp.json()
        results = data.get("results", [])
        if not results:
            continue

        # Перемешиваем, чтобы не всегда в порядке TMDb
        random.shuffle(results)

        logging.info(f"Searching movies with params: {params}")

        # Проверяем каждый фильм на IMDb
        for m in results:
            title = m.get("title") or m.get("name")
            imdb_raw = get_imdb_rating(title)
            try:
                if float(imdb_raw) >= 8.0:
                    found.append(m)
                    break  # нашёл один — выходим из цикла results
            except:
                continue
        if found:
            break  # нашёл — выходим из цикла страниц
        # Чтобы не превысить rate limit OMDb
        time.sleep(0.3)

    if not found:
        await update.callback_query.message.reply_text(
            "Не нашлось фильмов с IMDb ≥ 8.0 по заданным фильтрам",
            reply_markup=build_keyboard()
        )
        return

    # Сохраняем только этот фильм в очередь
    context.user_data["movies"] = found
    context.user_data["index"] = 0
    await send_movie(update, context, 0)
    
# Функция для очистки суррогатных пар
def clean_text(text: str) -> str:
    return text.encode('utf-16', 'surrogatepass').decode('utf-16')

def escape_markdown(text):
    if not text:
        return ''
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

async def send_movie(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int):
    movies = context.user_data.get("movies", [])
    if index >= len(movies):
        await update.callback_query.message.reply_text("Фильмы закончились", reply_markup=build_keyboard())
        return

    movie = movies[index]
    context.user_data["index"] = index
    
    poster_path = movie.get("poster_path")
    photo_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
    title = movie.get("title", "Без названия")
    description = movie.get("overview", "Описание недоступно")
    tmdb_rating = movie.get("vote_average", "—")
    imdb_rating = get_imdb_rating(title)

    # Экранируем всё
    escaped_title = escape_markdown(title)
    escaped_description = escape_markdown(description)
    escaped_tmdb = escape_markdown(str(tmdb_rating))
    escaped_imdb = escape_markdown(str(imdb_rating))

    spoiler_description = f"||{escaped_description}||"

    caption = (
        f"*🎬 {escaped_title}*\n"
        f"⭐ TMDb: *{escaped_tmdb}*\n"
        f"🌐 IMDb: *{escaped_imdb}*\n\n"
        f"{spoiler_description}"
    )

    await update.callback_query.message.reply_photo(
        photo=photo_url,
        caption=caption,
        parse_mode="MarkdownV2",
        reply_markup=build_movie_keyboard(movie["id"], index)
)

async def send_description(update: Update, context: ContextTypes.DEFAULT_TYPE, movie_id: str):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"api_key": TMDB_API_KEY, "language": "ru"}
    response = requests.get(url, params=params)
    movie = response.json()

    description = movie.get("overview", "Описание недоступно")
    escaped_description = escape_markdown(description)
    spoiler_text = f"||{escaped_description}||"  # спойлер обёртка

    await update.callback_query.message.reply_text(
        spoiler_text,
        parse_mode="MarkdownV2",
        reply_markup=build_keyboard()
    )

def parse_years(text: str):
    text = text.strip()
    if "-" in text:
        a, b = text.split("-", 1)
        return a, b
    return text, text
    
def get_all_genres():
    global cached_genres
    if cached_genres:
        return cached_genres
    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=ru"
    data = requests.get(url).json()
    cached_genres = {g["name"].lower(): g["id"] for g in data.get("genres", [])}
    return cached_genres

def get_genre_ids(genres_text):
    if not genres_text:
        return []
    genres = [g.strip().lower() for g in genres_text.split(",")]
    genre_map = get_all_genres()
    return [genre_map[g] for g in genres if g in genre_map]

def get_actor_ids(actors_text):
    if not actors_text:
        return []
    actor_ids = []
    for name in [a.strip() for a in actors_text.split(",")]:
        url = f"https://api.themoviedb.org/3/search/person?api_key={TMDB_API_KEY}&language=ru&query={name}"
        res = requests.get(url).json()
        if res["results"]:
            actor_ids.append(res["results"][0]["id"])
    return actor_ids

def get_imdb_rating(title):
    if not OMDB_API_KEY:
        return "—"
    url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={title}"
    try:
        res = requests.get(url)
        data = res.json()
        return data.get("imdbRating", "—")
    except Exception as e:
        logging.error(f"IMDb error: {e}")
        return "—"

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(button_handler)],
    states={
        GENRES: [MessageHandler(filters.TEXT & ~filters.COMMAND, genres_input)],
        ACTORS: [MessageHandler(filters.TEXT & ~filters.COMMAND, actors_input)],
        YEARS: [MessageHandler(filters.TEXT & ~filters.COMMAND, years_input)],
    },
    fallbacks=[],
    allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))

    port = int(os.environ.get("PORT", 8080))
    app.run_webhook(listen="0.0.0.0", port=port, webhook_url=os.environ.get("WEBHOOK_URL"))
