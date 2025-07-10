# bot.py — Telegram-бот через Webhook, рейтинг ≥ 8, с подсказками и навигацией
import os, requests, difflib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ConversationHandler, ContextTypes, filters


print("TELEGRAM_TOKEN =", TELEGRAM_TOKEN)
print("TMDB_API_KEY =", TMDB_API_KEY)
print("PORT =", os.getenv("PORT"))
print("WEBHOOK_URL =", os.getenv("WEBHOOK_URL"))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

GENRES, ACTORS = range(2)
available_genres = ["боевик","приключения","мультфильм","аниме","биография","комедия","криминал","документальный","драма","семейный","фэнтези","история","ужасы","музыка","детектив","мелодрама","фантастика","телевизионный фильм","триллер","военный","вестерн"]

def fix_genres(user_input):
    corrected = []
    for w in user_input:
        m = difflib.get_close_matches(w.lower().strip(), available_genres, n=1, cutoff=0.6)
        if m:
            corrected.append(m[0])
    return corrected

async def start(update, ctx):
    kb = [
        [InlineKeyboardButton("🎞 Указать жанры", callback_data="genres")],
        [InlineKeyboardButton("🎭 Указать актёров", callback_data="actors")],
        [InlineKeyboardButton("🔎 Найти фильмы", callback_data="search")]
    ]
    await update.message.reply_text("Привет! Что хочешь сделать?", reply_markup=InlineKeyboardMarkup(kb))

async def button_handler(update, ctx):
    q = update.callback_query; await q.answer()
    if q.data=="genres":
        text="Введи жанры (по одному, через запятую):\n\n📌 " + ", ".join(available_genres)
        await q.message.reply_text(text)
        return GENRES
    if q.data=="actors":
        await q.message.reply_text("Введи имена актёров через запятую:")
        return ACTORS
    if q.data=="search":
        await show_movie(update, ctx, 0)
        return ConversationHandler.END

async def genres_input(update, ctx):
    arr = update.message.text.split(",")
    ctx.user_data["genres"] = fix_genres(arr)
    await update.message.reply_text("✅ Жанры: " + ", ".join(ctx.user_data["genres"]))
    return ConversationHandler.END

async def actors_input(update, ctx):
    arr = [a.strip() for a in update.message.text.split(",")]
    ctx.user_data["actors"] = arr
    await update.message.reply_text("✅ Актёры: " + ", ".join(arr))
    return ConversationHandler.END

def get_genre_ids(lst):
    res = requests.get("https://api.themoviedb.org/3/genre/movie/list", params={"api_key":TMDB_API_KEY,"language":"ru"}).json()
    mp={g["name"].lower():g["id"] for g in res["genres"]}
    return [mp[g] for g in lst if g in mp]

def get_actor_ids(lst):
    ids=[]
    for name in lst:
        r=requests.get("https://api.themoviedb.org/3/search/person",params={"api_key":TMDB_API_KEY,"language":"ru","query":name}).json()
        if r.get("results"): ids.append(r["results"][0]["id"])
    return ids

def search_movies(genre_ids,actor_ids):
    r=requests.get("https://api.themoviedb.org/3/discover/movie", params={"api_key":TMDB_API_KEY,"language":"ru","sort_by":"popularity.desc","vote_average.gte":8,"with_genres":",".join(map(str,genre_ids)),"with_cast":",".join(map(str,actor_ids))}).json()
    return r.get("results",[])

async def show_movie(update, ctx, index):
    q=update.callback_query; await q.answer()
    if "movies" not in ctx.user_data:
        g=ctx.user_data.get("genres",[]); a=ctx.user_data.get("actors",[])
        ctx.user_data["movies"]=search_movies(get_genre_ids(g), get_actor_ids(a))
    arr=ctx.user_data["movies"]
    if index>=len(arr):
        await q.message.reply_text("😔 Больше нет!")
        return
    m=arr[index]
    pu=("https://image.tmdb.org/t/p/w500"+m["poster_path"]) if m.get("poster_path") else None
    cap=f"🎬 <b>{m['title']}</b>\n⭐ <b>{m['vote_average']}</b>"
    bt=[[InlineKeyboardButton("📖 Описание",callback_data=f"desc|{m['id']}")]]
    if index+1<len(arr): bt.append([InlineKeyboardButton("➡ Далее",callback_data=f"next|{index+1}")])
    await q.message.reply_photo(photo=pu,caption=cap,reply_markup=InlineKeyboardMarkup(bt),parse_mode="HTML")

async def show_description(update, ctx):
    q=update.callback_query; await q.answer()
    id_=q.data.split("|")[1]
    r=requests.get(f"https://api.themoviedb.org/3/movie/{id_}",params={"api_key":TMDB_API_KEY,"language":"ru"}).json()
    await q.message.reply_text(f"<b>{r['title']}</b>\n{r.get('overview','')}", parse_mode="HTML")

async def next_movie(update,ctx):
    idx=int(update.callback_query.data.split("|")[1])
    await show_movie(update,ctx,idx)

app=ApplicationBuilder().token(TELEGRAM_TOKEN).build()
conv=ConversationHandler(entry_points=[CallbackQueryHandler(button_handler)], states={GENRES:[MessageHandler(filters.TEXT & ~filters.COMMAND,genres_input)],ACTORS:[MessageHandler(filters.TEXT & ~filters.COMMAND,actors_input)]}, fallbacks=[], allow_reentry=True)
app.add_handler(CommandHandler("start",start))
app.add_handler(conv)
app.add_handler(CallbackQueryHandler(show_description,pattern=r"^desc\|"))
app.add_handler(CallbackQueryHandler(next_movie,pattern=r"^next\|"))
print("🤖 Bot started! webhook mode")
app.run_webhook(listen="0.0.0.0", port=int(os.getenv("PORT",3000)), webhook_url=os.getenv("WEBHOOK_URL"))
