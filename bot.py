import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (ApplicationBuilder,ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, filters)

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

# Кнопки главного меню
def build_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎞 Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("🎭 Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("🔎 Найти фильмы", callback_data="search")],
    ])

# Кнопки у фильма
def build_movie_keyboard(movie_id, index):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📖 Описание", callback_data=f"desc|{movie_id}")],
        [InlineKeyboardButton("➡ Далее", callback_data=f"next|{index+1}")],
        [InlineKeyboardButton("🎞 Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("🎭 Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("🔎 Найти фильмы", callback_data="search")],
    ])

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Что хочешь сделать?",
        reply_markup=build_keyboard()
    )

# Обработка кнопок
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

# Сохранение жанров
async def genres_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["genres"] = update.message.text
    await update.message.reply_text("Жанры сохранены", reply_markup=build_keyboard())
    return ConversationHandler.END

# Сохранение актёров
async def actors_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["actors"] = update.message.text
    await update.message.reply_text("Актёры сохранены", reply_markup=build_keyboard())
    return ConversationHandler.END

# Поиск фильмов
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
        await update.callback_query.message.reply_text("Фильмы не найдены", reply_markup=build_keyboard())
        return

    context.user_data["movies"] = movies
    context.user_data["index"] = 0
    await send_movie(update, context, 0)

# Отправка фильма
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

    caption = (
        f"🎬 <b>{title}</b>\n"
        f"⭐ TMDB: <b>{tmdb_rating}</b>\n"
        f"🌐 IMDb: <b>{imdb_rating}</b>"
    )

    await update.callback_query.message.reply_photo(
        photo=photo_url,
        caption=caption,
        parse_mode="HTML",
        reply_markup=build_movie_keyboard(movie["id"], index)
    )

# Описание фильма
async def send_description(update: Update, context: ContextTypes.DEFAULT_TYPE, movie_id: str):
    url = f"https://api.themoviedb.org/3/movie/{movie_id}"
    params = {"api_key": TMDB_API_KEY, "language": "ru"}
    response = requests.get(url, params=params)
    movie = response.json()

    description = movie.get("overview", "Описание недоступно")
    await update.callback_query.message.reply_text(f"📖 {description}", reply_markup=build_keyboard())

# Жанры → ID
def get_genre_ids(genres_text):
    if not genres_text:
        return []
    genres = [g.strip().lower() for g in genres_text.split(",")]
    url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={TMDB_API_KEY}&language=ru"
    data = requests.get(url).json()
    genre_map = {g["name"].lower(): g["id"] for g in data.get("genres", [])}
    return [genre_map[g] for g in genres if g in genre_map]

# Актёры → ID
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

# IMDb рейтинг через OMDb
def get_imdb_rating(title):
    if not OMDB_API_KEY:
        return "—"
    url = f"http://www.omdbapi.com/?apikey={OMDB_API_KEY}&t={title}"
    try:
        res = requests.get(url)
        data = res.json()
        return data.get("imdbRating", "—")
    except Exception as e:
        logging.error(f"Ошибка IMDb: {e}")
        return "—"

# Запуск
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
    app.run_webhook(listen="0.0.0.0", port=port, webhook_url=os.environ.get("WEBHOOK_URL")
    )
