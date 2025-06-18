import asyncio
import json
import logging
import os
import nest_asyncio
import requests
import psycopg2
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Aktifkan nest_asyncio
nest_asyncio.apply()

# --- [WAJIB] Ambil Konfigurasi dari Environment Variables ---
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# --- Fungsi Database (Pengganti favorites.json) ---

def get_db_connection():
    """Membuka koneksi ke database PostgreSQL."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.OperationalError as e:
        logger.error(f"Error connecting to database: {e}")
        return None

def setup_database():
    """Membuat tabel favorites jika belum ada."""
    conn = get_db_connection()
    if conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS favorites (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    movie_id INTEGER NOT NULL,
                    movie_title VARCHAR(255) NOT NULL,
                    UNIQUE(user_id, movie_id)
                );
            """)
            conn.commit()
        conn.close()
        logger.info("Database table 'favorites' is ready.")

def add_favorite_to_db(user_id, movie_id, movie_title):
    """Menambahkan film favorit ke database untuk user tertentu."""
    conn = get_db_connection()
    if not conn: return False, "Database connection error."
    
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO favorites (user_id, movie_id, movie_title) VALUES (%s, %s, %s) ON CONFLICT (user_id, movie_id) DO NOTHING;",
                (user_id, movie_id, movie_title)
            )
            # a `rowcount` of 0 means the movie was already in the favorites
            was_inserted = cur.rowcount > 0
            conn.commit()
        return was_inserted, f"'{movie_title}' berhasil ditambahkan ke favorit!" if was_inserted else f"'{movie_title}' sudah ada di favorit Anda."
    except Exception as e:
        logger.error(f"Error adding favorite to DB: {e}")
        return False, "Gagal menambahkan favorit."
    finally:
        if conn: conn.close()

def get_favorites_from_db(user_id):
    """Mengambil daftar film favorit dari database untuk user tertentu."""
    conn = get_db_connection()
    if not conn: return []
    
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT movie_title FROM favorites WHERE user_id = %s ORDER BY movie_title;", (user_id,))
            favorites = [row[0] for row in cur.fetchall()]
        return favorites
    except Exception as e:
        logger.error(f"Error getting favorites from DB: {e}")
        return []
    finally:
        if conn: conn.close()

# --- Fungsi API & Helper (sedikit modifikasi) ---

GENRES = {} # Akan diisi saat bot start

def load_genres():
    """Load genres from TMDb."""
    data = tmdb_request("genre/movie/list")
    if data and "genres" in data:
        return {genre['name'].lower(): genre['id'] for genre in data["genres"]}
    return {}

def tmdb_request(endpoint, params=None):
    """Melakukan request ke TMDb API."""
    if not TMDB_API_KEY:
        logger.error("TMDb API key not set.")
        return {}
    base_params = {"api_key": TMDB_API_KEY, "language": "en-US"}
    if params:
        base_params.update(params)
    try:
        response = requests.get(f"https://api.themoviedb.org/3/{endpoint}", params=base_params)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error in TMDb request: {e}")
        return {}

def create_movie_keyboard(movies, callback_prefix="detail"):
    """Membuat keyboard inline untuk daftar film."""
    keyboard = []
    for movie in movies[:5]:  # Limit to 5 results
        movie_id = movie["id"]
        movie_title = movie["title"]
        release_year = movie.get("release_date", "Unknown")[:4] if movie.get("release_date") else "N/A"
        display_name = f"{movie_title} ({release_year})"
        keyboard.append([InlineKeyboardButton(display_name, callback_data=f"{callback_prefix}_{movie_id}")])
    keyboard.append([InlineKeyboardButton("🎛️ Tampilkan Menu Utama", callback_data="menu_menu")])
    return InlineKeyboardMarkup(keyboard)

def create_main_menu():
    """Membuat pesan dan keyboard menu utama."""
    start_message = """
🎥 **Selamat datang di Movie Search Bot!** 🍿

Siap menjelajahi dunia film? Gunakan tombol di bawah untuk memulai:

- **Cari Film**: Temukan film berdasarkan judul.
- **Cari Aktor**: Lihat film populer dari aktor favorit.
- **Film Trending**: Lihat apa yang sedang populer saat ini.
- **Simpan Favorit**: Buat daftar tontonan pribadimu.

Klik tombol di bawah untuk beraksi!
    """
    keyboard = [
        [InlineKeyboardButton("🔍 Cari Film", callback_data="menu_search"), InlineKeyboardButton("🎭 Cari Aktor", callback_data="menu_actor")],
        [InlineKeyboardButton("🎬 Film Trending", callback_data="menu_trending"), InlineKeyboardButton("🏷️ Genre Film", callback_data="menu_genres")],
        [InlineKeyboardButton("⭐ Tambah Favorit", callback_data="menu_favorite"), InlineKeyboardButton("📜 List Favorit", callback_data="menu_favorites")],
        [InlineKeyboardButton("🎫 Cari Bioskop", callback_data="menu_cinema"), InlineKeyboardButton("❓ Bantuan", callback_data="menu_help")],
    ]
    return start_message, InlineKeyboardMarkup(keyboard)

def create_error_keyboard():
    """Membuat keyboard untuk kembali ke menu saat terjadi error."""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🎛️ Kembali ke Menu", callback_data="menu_menu")]])

# --- Handler untuk Perintah dan Tombol ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /start."""
    start_message, reply_markup = create_main_menu()
    await update.message.reply_text(start_message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_movie_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan detail film yang dipilih."""
    query = update.callback_query
    await query.answer()
    movie_id = query.data.split("_")[1]
    
    movie = tmdb_request(f"movie/{movie_id}")
    if not movie:
        await query.edit_message_text("❌ Detail film tidak ditemukan.", reply_markup=create_error_keyboard())
        return

    title = movie.get("title", "N/A")
    overview = movie.get("overview") or "Sinopsis tidak tersedia."
    rating = f"{movie.get('vote_average', 0):.1f}"
    release_date = movie.get("release_date", "N/A")

    credits = tmdb_request(f"movie/{movie_id}/credits")
    cast_list = ", ".join([actor["name"] for actor in credits.get("cast", [])[:5]]) if credits else "Info pemeran tidak tersedia."
    
    message = (
        f"🎬 **{title}**\n\n"
        f"📅 **Rilis**: {release_date}\n"
        f"⭐ **Rating**: {rating} / 10\n\n"
        f"📝 **Sinopsis**:\n{overview}\n\n"
        f"👥 **Pemeran**:\n{cast_list}"
    )
    
    keyboard = [[InlineKeyboardButton("⭐ Tambah ke Favorit", callback_data=f"save_{movie_id}")],
                [InlineKeyboardButton("🎛️ Kembali ke Menu", callback_data="menu_menu")]]
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def save_favorite_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menyimpan film ke favorit (dari tombol)."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    movie_id = int(query.data.split("_")[1])
    
    movie = tmdb_request(f"movie/{movie_id}")
    if not movie:
        await query.edit_message_text("❌ Gagal mendapatkan detail film.", reply_markup=create_error_keyboard())
        return

    movie_title = movie.get("title", "Unknown")
    success, message = add_favorite_to_db(user_id, movie_id, movie_title)
    
    await query.edit_message_text(f"✅ {message}" if success else f"❌ {message}", reply_markup=create_error_keyboard())

async def add_favorite_by_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai proses penambahan favorit berdasarkan judul."""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("⚠️ Masukkan judul film setelah perintah.\nContoh: `/favorite Inception`", reply_markup=create_error_keyboard())
        return
        
    data = tmdb_request("search/movie", {"query": query})
    movies = data.get("results", [])
    if not movies:
        await update.message.reply_text(f"❌ Tidak ada film yang ditemukan untuk '{query}'.", reply_markup=create_error_keyboard())
        return

    reply_markup = create_movie_keyboard(movies, callback_prefix="save")
    await update.message.reply_text("🎬 Pilih film yang ingin Anda simpan ke favorit:", reply_markup=reply_markup)


async def view_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menampilkan daftar film favorit pengguna."""
    user_id = update.message.from_user.id
    favorites_list = get_favorites_from_db(user_id)
    
    if not favorites_list:
        await update.message.reply_text("❌ Anda belum memiliki film favorit. Tambahkan dengan perintah /favorite.", reply_markup=create_error_keyboard())
        return
        
    message = "⭐ **Daftar Film Favorit Anda:**\n"
    for movie in favorites_list:
        message += f"- {movie}\n"
        
    await update.message.reply_text(message, reply_markup=create_error_keyboard(), parse_mode='Markdown')

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk pesan teks, berfungsi sebagai state machine sederhana."""
    state = context.user_data.pop('state', None)
    text = update.message.text
    
    # Fungsi pembantu untuk memanggil handler sebenarnya
    async def call_search_movie(query_text):
        context.args = query_text.split()
        data = tmdb_request("search/movie", {"query": query_text})
        movies = data.get("results", [])
        if not movies:
            await update.message.reply_text(f"❌ Tidak ada film yang ditemukan untuk '{query_text}'.", reply_markup=create_error_keyboard())
            return
        reply_markup = create_movie_keyboard(movies, callback_prefix="detail")
        await update.message.reply_text("🎬 Hasil pencarian:", reply_markup=reply_markup)

    async def call_search_actor(query_text):
        context.args = query_text.split()
        data = tmdb_request("search/person", {"query": query_text})
        actors = data.get("results", [])
        if not actors or not actors[0].get("known_for"):
            await update.message.reply_text(f"❌ Tidak ada aktor/aktris yang ditemukan untuk '{query_text}'.", reply_markup=create_error_keyboard())
            return
        
        actor = actors[0]
        name = actor["name"]
        known_for = [movie for movie in actor.get("known_for", []) if movie.get('media_type') == 'movie']
        
        await update.message.reply_text(f"🎬 Film populer yang dibintangi **{name}**:", reply_markup=create_movie_keyboard(known_for), parse_mode='Markdown')

    async def call_add_favorite(query_text):
        context.args = query_text.split()
        await add_favorite_by_title(update, context)

    # Logika state machine
    if state == 'search':
        await call_search_movie(text)
    elif state == 'actor':
        await call_search_actor(text)
    elif state == 'favorite':
        await call_add_favorite(text)
    else:
        # Jika tidak ada state, balas dengan menu utama
        start_message, reply_markup = create_main_menu()
        await update.message.reply_text("Maaf, saya tidak mengerti. Silakan gunakan tombol di bawah ini:", reply_markup=reply_markup)

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk semua tombol dari menu utama."""
    query = update.callback_query
    await query.answer()
    action = query.data.split("_", 1)[1] # Split only on the first underscore

    # Hapus pesan keyboard sebelumnya agar UI bersih
    await query.message.delete()

    if action == "search":
        context.user_data['state'] = 'search'
        await query.message.reply_text("🔍 Silakan ketik judul film yang ingin Anda cari:")
    elif action == "actor":
        context.user_data['state'] = 'actor'
        await query.message.reply_text("🎭 Silakan ketik nama aktor atau aktris:")
    elif action == "favorite":
        context.user_data['state'] = 'favorite'
        await query.message.reply_text("⭐ Silakan ketik judul film untuk ditambahkan ke favorit:")
    elif action == "favorites":
        user_id = query.from_user.id
        favorites_list = get_favorites_from_db(user_id)
        if not favorites_list:
            await query.message.reply_text("❌ Anda belum memiliki film favorit.", reply_markup=create_error_keyboard())
            return
        message = "⭐ **Daftar Film Favorit Anda:**\n" + "\n".join(f"- {movie}" for movie in favorites_list)
        await query.message.reply_text(message, reply_markup=create_error_keyboard(), parse_mode='Markdown')
    elif action == "trending":
        data = tmdb_request("trending/movie/day")
        movies = data.get("results", [])
        if not movies:
            await query.message.reply_text("❌ Gagal mengambil film trending.", reply_markup=create_error_keyboard())
            return
        await query.message.reply_text("🎬 **Film Paling Populer Hari Ini:**", reply_markup=create_movie_keyboard(movies), parse_mode='Markdown')
    elif action == "genres":
        genres_list = list(GENRES.keys())[:10]
        keyboard = [
            [InlineKeyboardButton(g.capitalize(), callback_data=f"genre_{g}")] for g in genres_list
        ]
        keyboard.append([InlineKeyboardButton("🎛️ Kembali ke Menu", callback_data="menu_menu")])
        await query.message.reply_text("🏷️ **Pilih Genre:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    elif action == "cinema":
        keyboard = [[KeyboardButton("📍 Kirim Lokasimu Sekarang", request_location=True)]]
        await query.message.reply_text(
            "Untuk mencari bioskop terdekat, saya butuh lokasi Anda. Silakan klik tombol di bawah.",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        )
    elif action == "help":
        help_text = """
❓ **Bantuan**

- **/start**: Menampilkan menu utama.
- **/favorite [judul]**: Menambahkan film ke daftar favorit.
- **/favorites**: Melihat daftar film favorit.

Anda juga bisa menggunakan tombol-tombol interaktif pada menu utama untuk semua fitur.
        """
        await query.message.reply_text(help_text, reply_markup=create_error_keyboard(), parse_mode='Markdown')
    elif action == "menu":
        start_message, reply_markup = create_main_menu()
        await query.message.reply_text(start_message, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_genre_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler saat tombol genre dipilih."""
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    genre_name = query.data.split("_", 1)[1]
    genre_id = GENRES.get(genre_name)
    if not genre_id:
        await query.message.reply_text(f"❌ Genre '{genre_name}' tidak valid.", reply_markup=create_error_keyboard())
        return
    data = tmdb_request("discover/movie", {"with_genres": genre_id, "sort_by": "popularity.desc"})
    movies = data.get("results", [])
    if not movies:
        await query.message.reply_text(f"❌ Tidak ada film yang ditemukan untuk genre {genre_name.capitalize()}.", reply_markup=create_error_keyboard())
        return
    await query.message.reply_text(f"🎬 Film Populer Genre **{genre_name.capitalize()}**:", reply_markup=create_movie_keyboard(movies), parse_mode='Markdown')

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler saat menerima lokasi untuk mencari bioskop."""
    location = update.message.location
    lat = location.latitude
    lon = location.longitude
    maps_url = f"https://www.google.com/maps/search/bioskop/@{lat},{lon},15z"
    await update.message.reply_text(
        f"✅ Lokasi diterima! Klik link di bawah untuk melihat bioskop terdekat di Google Maps:\n\n{maps_url}",
        reply_markup=ReplyKeyboardRemove() # Menghapus tombol lokasi
    )
    # Tampilkan kembali menu utama setelah beberapa saat
    await asyncio.sleep(2)
    start_message, reply_markup = create_main_menu()
    await update.message.reply_text("Ada lagi yang bisa saya bantu?", reply_markup=reply_markup, parse_mode='Markdown')


# --- Fungsi Utama untuk Menjalankan Bot ---

def main():
    """Fungsi utama untuk inisialisasi dan menjalankan bot."""
    if not all([BOT_TOKEN, TMDB_API_KEY, DATABASE_URL]):
        logger.critical("FATAL: Environment variables (BOT_TOKEN, TMDB_API_KEY, DATABASE_URL) not set. Exiting.")
        return

    # Inisialisasi database dan genre
    setup_database()
    global GENRES
    GENRES = load_genres()

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("favorite", add_favorite_by_title))
    application.add_handler(CommandHandler("favorites", view_favorites))
    
    application.add_handler(CallbackQueryHandler(show_movie_details, pattern=r"^detail_"))
    application.add_handler(CallbackQueryHandler(save_favorite_movie, pattern=r"^save_"))
    application.add_handler(CallbackQueryHandler(handle_menu_button, pattern=r"^menu_"))
    application.add_handler(CallbackQueryHandler(handle_genre_button, pattern=r"^genre_"))
    
    application.add_handler(MessageHandler(filters.LOCATION, handle_location))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    logger.info("Starting bot polling...")
    application.run_polling()

if __name__ == "__main__":
    main()