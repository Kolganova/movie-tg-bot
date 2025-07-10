import os
import random
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
    years = context.user_data.get("years", "")

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

    # Парсим years, чтобы получить gte и lte
    if years:
        years = years.replace(" ", "")
        if "-" in years:
            parts = years.split("-")
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                start_year = parts[0]
                end_year = parts[1]
                params["primary_release_date.gte"] = f"{start_year}-01-01"
                params["primary_release_date.lte"] = f"{end_year}-12-31"
        elif years.isdigit():
            params["primary_release_date.gte"] = f"{years}-01-01"
            params["primary_release_date.lte"] = f"{years}-12-31"

    logging.debug(f"[TMDb search] Params: {params}")

    url = "https://api.themoviedb.org/3/discover/movie"
    response = requests.get(url, params=params)
    data = response.json()

    movies = data.get("results", [])

    if not movies:
        await update.callback_query.message.reply_text("Фильмы не найдены по заданным фильтрам", reply_markup=build_keyboard())
        return

    random.shuffle(movies)  # перемешиваем фильмы для рандома

    context.user_data["movies"] = movies
    context.user_data["index"] = 0
    await send_movie(update, context, 0)

# Функция для очистки суррогатных пар
def clean_text(text: str) -> str:
    return text.encode('utf-16', 'surrogatepass').decode('utf-16')

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
    release_date = movie.get("release_date", "")
    year = release_date.split("-")[0] if release_date else "—"
    countries = movie.get("production_countries", [])
    # production_countries не приходит в discover, надо дополнительно запросить детали фильма, либо сделать пустой список:
    country_names = []
    # Для ускорения можно подгружать детали фильма один раз при отправке, например:
    # Но чтобы не менять логику сильно, будем делать запрос при отправке:
    # -- см. ниже исправленный send_movie --

    imdb_rating = get_imdb_rating(title)

    # Для country_names запросим детали фильма:
    url = f"https://api.themoviedb.org/3/movie/{movie['id']}"
    params = {"api_key": TMDB_API_KEY, "language": "ru"}
    resp = requests.get(url, params=params)
    if resp.status_code == 200:
        details = resp.json()
        country_names = [c.get("name") for c in details.get("production_countries", [])]

    countries_str = ", ".join(country_names) if country_names else "—"

    caption = (
        f"🎬 <b>{title}</b> ({year})\n"
        f"⭐ TMDB: <b>{tmdb_rating}</b>\n"
        f"🌐 IMDb: <b>{imdb_rating}</b>\n"
        f"🌍 Страны: {countries_str}"
    )

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
    description = clean_text(description)  # очищаем от суррогатов

    await update.callback_query.message.reply_text(f"📖 {description}", reply_markup=build_keyboard())

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
