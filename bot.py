import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

logging.basicConfig(level=logging.DEBUG)

GENRES, ACTORS = range(2)

def build_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎞 Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("🎭 Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("🔎 Найти фильмы", callback_data="search")],
    ])

def build_movie_keyboard(movie_id, index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Описание", callback_data=f"desc|{movie_id}")],
        [InlineKeyboardButton("➡ Далее", callback_data=f"next|{index+1}")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Что хочешь сделать?",
        reply_markup=build_keyboard()
    )

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

async def search_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    genres = context.user_data.get("genres", "")
    actors = context.user_data.get("actors", "")

    genre_ids = get_genre_ids(genres)
    actor_ids = get_actor_ids(actors)

    url = "https://api.themoviedb.org/3/discover/movie"
    params = {
        "api_key": TMDB_API_KEY,
        "language": "ru",
        "sort_by": "popularity.desc",
        "vote_average.gte": 8,
        "with_genres": ",".join(map(str, genre_ids)) if genre_ids else None,
        "with_cast": ",".join(map(str, actor_ids)) if actor_ids else None
    }

    response = requests.get(url, params=params)
    data = response.json()
    movies = data.get("results", [])

    if not movies:
        await update.callback_query.message.reply_text("Фильмы не найдены")
        return

    context.user_data["movies"] = movies
    context.user_data["index"] = 0
    await send_movie(update, context, 0)

async def send_movie(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int):
    movies = context.user_data.get("movies", [])
    if index >= len(movies):
        await update.callback_query.message.reply_text("Фильмы закончились")
        return

    movie = movies[index]
    context.user_data["index"] = index

    photo_url = f"https://image.tmdb.org/t/p/w500{movie['poster_path']}"
    caption = f"🎬 <b>{movie['title']}</b>\n⭐ <b>{movie['vote_average']}</b>"

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
    await update.callback_query.message.reply_text(f"📖 {description}")

def get_genre_ids(genres_text):
    if not genres_text:
        return []
    genres = [g.strip().lower() for g in genres_text.split(",")]
    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=ru"
    data = requests.get(url).json()
    genre_map = {g["name"].lower(): g["id"] for g in data.get("genres", [])}
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

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler)],
        states={
            GENRES: [MessageHandler(filters.TEXT & ~filters.COMMAND, genres_input)],
            ACTORS: [MessageHandler(filters.TEXT & ~filters.COMMAND, actors_input)]
        },
        fallbacks=[],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))

    port = int(os.environ.get("PORT", 8080))
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=os.environ.get("WEBHOOK_URL")
    )
