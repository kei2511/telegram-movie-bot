# telegram-movie-bot

Panduan Deployment di Render.com (Gratis)
Ikuti langkah-langkah ini dengan teliti.

Langkah 1: Siapkan Akun Anda
Buat Akun GitHub: Jika belum punya, daftar di github.com.
Buat Repositori Baru: Di GitHub, buat repositori baru (misalnya, telegram-movie-bot).
Upload File: Upload kedua file yang sudah Anda buat (bot.py dan requirements.txt) ke repositori tersebut.
Siapkan Token:
Telegram Bot Token: Dapatkan dari BotFather di Telegram.
TMDb API Key: Dapatkan setelah mendaftar di themoviedb.org.
Langkah 2: Buat Database Gratis di Render
Daftar Render: Buka render.com dan daftar menggunakan akun GitHub Anda.
Buat Database:
Di dashboard Render, klik New + > PostgreSQL.
Beri Nama (misal: movie-bot-db).
Pastikan Plan/Paket yang dipilih adalah Free.
Klik Create Database. Tunggu sekitar 1-2 menit hingga statusnya menjadi "Available".
Salin URL Database: Setelah database siap, masuk ke halamannya, cari bagian Connections, dan salin URL dari kolom Internal Connection URL. Simpan URL ini, kita akan membutuhkannya.
Langkah 3: Deploy Bot Anda
Buat Layanan Baru: Kembali ke dashboard Render, klik New + > Background Worker.
Hubungkan Repositori: Pilih repositori GitHub yang tadi Anda buat (telegram-movie-bot).
Isi Konfigurasi:
Name: Beri nama layanan Anda (misal: movie-bot-worker).
Region: Pilih Singapore (lebih dekat ke Indonesia).
Branch: Biarkan main atau master.
Runtime: Biarkan Python 3.
Build Command: Biarkan pip install -r requirements.txt.
Start Command: Ketik python bot.py.
Plan/Paket: Pastikan Anda memilih Free.
Tambahkan Environment Variables (PENTING!):
Scroll ke bawah ke bagian "Advanced".
Klik Add Environment Variable sebanyak 3 kali, lalu isi:
Key: BOT_TOKEN | Value: (paste token bot Telegram Anda di sini)
Key: TMDB_API_KEY | Value: (paste API key TMDb Anda di sini)
Key: DATABASE_URL | Value: (paste Internal Connection URL database yang Anda salin tadi)
Deploy: Klik tombol Create Background Worker di bagian paling bawah.
Render akan mulai membangun dan menjalankan bot Anda. Anda bisa melihat prosesnya di tab "Logs". Jika semua berjalan lancar, dalam beberapa menit bot Anda akan online dan siap digunakan 24/7!
