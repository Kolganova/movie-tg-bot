import os
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
logging.basicConfig(level=logging.DEBUG)

# Стейты
GENRES, ACTORS = range(2)

# Логгинг
logging.basicConfig(level=logging.DEBUG)

cached_genres = {}

def build_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\U0001F39E Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("\U0001F3AD Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("\U0001F50E Найти фильмы", callback_data="search")],
        [InlineKeyboardButton("\u274C Сбросить фильтры", callback_data="reset")]
    ])

def build_movie_keyboard(movie_id, index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\ud83d\udcd6 Описание", callback_data=f"desc|{movie_id}")],
        [InlineKeyboardButton("\u27a1 Далее", callback_data=f"next|{index+1}")],
        [InlineKeyboardButton("\U0001F39E Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("\U0001F3AD Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("\U0001F50E Найти фильмы", callback_data="search")],
        [InlineKeyboardButton("\u274C Сбросить фильтры", callback_data="reset")]
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привет! Что хочешь сделать?", reply_markup=build_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "genres":
        genres = get_all_genres()
        genre_list = "\n".join(f"\u2022 {name}" for name in genres.keys())
        await query.message.reply_text(f"Выбери жанры из списка, введи через запятую:\n{genre_list}")
        return GENRES
    elif data == "actors":
        await query.message.reply_text("Введи имена актёров через запятую")
        return ACTORS
    elif data == "search":
        await search_movies(update, context)
    elif data == "reset":
        context.user_data.clear()
        await query.message.reply_text("Фильтры сброшены", reply_markup=build_keyboard())
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

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    genres = context.user_data.get("genres", "")
    actors = context.user_data.get("actors", "")

    genre_ids = get_genre_ids(genres)
    actor_ids = get_actor_ids(actors)

    params = {
        "api_key": TMDB_API_KEY,
        "language": "ru",
        "sort_by": "popularity.desc",
        "vote_average.gte": 8,
    }

    if genre_ids:
        params["with_genres"] = ",".join(map(str, genre_ids))
    if actor_ids:
        params["with_cast"] = ",".join(map(str, actor_ids))

    url = "https://api.themoviedb.org/3/discover/movie"
    response = requests.get(url, params=params)
    data = response.json()

    if not data.get("results"):
        await update.callback_query.message.reply_text("Фильмы не найдены по заданным фильтрам", reply_markup=build_keyboard())
        return

    context.user_data["movies"] = data["results"]
    context.user_data["index"] = 0
    await send_movie(update, context, 0)

async def send_movie(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int):
    movies = context.user_data.get("movies", [])
    if index >= len(movies):
        await update.callback_query.message.reply_text("Фильмы закончились", reply_markup=build_keyboard())
        return

    movie = movies[index]
    context.user_data["index"] = index

    title = movie.get("title", "Без названия")
    poster_path = movie.get("poster_path")
    photo_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
    tmdb_rating = movie.get("vote_average", "—")
    imdb_rating = get_imdb_rating(title)

    caption = f"\U0001F3AC <b>{title}</b>\n\u2B50 TMDB: <b>{tmdb_rating}</b>\n\U0001F310 IMDb: <b>{imdb_rating}</b>"

    await update.callback_query.message.reply_photo(
        photo=photo_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=build_movie_keyboard(movie["id"], index)
    )

async def send_description(update: Update, context: ContextTypes.DEFAULT_TYPE, movie_id: str):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"api_key": TMDB_API_KEY, "language": "ru"}
    response = requests.get(url, params=params)
    movie = response.json()

    description = movie.get("overview", "Описание недоступно")
    await update.callback_query.message.reply_text(f"\ud83d\udcd6 {description}", reply_markup=build_keyboard())

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
        },
        fallbacks=[],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))

    port = int(os.environ.get("PORT", 8080))
    app.run_webhook(listen="0.0.0.0", port=port, webhook_url=os.environ.get("WEBHOOK_URL"))
