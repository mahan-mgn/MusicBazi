#!/data/data/com.termux/files/usr/bin/bash
#
# بک‌اند موزیک بازی روی خودِ گوشی — داخل Termux اجرا می‌شود.
#
# چرا Termux و نه جاسازیِ پایتون داخل APK:
# FastAPI روی `pydantic-core` می‌دود و آن یک افزونه‌ی Rust است. برای اندروید هیچ
# ویلِ آماده‌ای ندارد (نه روی PyPI، نه در مخزنِ ویل‌های Chaquopy) و bionic را هم
# نمی‌شناسد. داخل Termux اما همین یک پکیج است که با `rust`ِ خودِ Termux یک‌بار
# کامپایل می‌شود — و در عوض *هیچ خطی* از بک‌اند عوض نمی‌شود. همان کدِ لپ‌تاپ،
# روی گوشی.
#
# کتابخانه‌ها چرا جدا می‌مانند: دیتابیس و فایل‌ها در `$HOME/musicbazi/` گوشی
# می‌نشینند و سرور فقط روی `127.0.0.1` گوش می‌دهد. هیچ مسیری بین آرشیوِ گوشی و
# آرشیوِ لپ‌تاپ وجود ندارد — نه همگام‌سازی، نه هم‌نام‌سازی. دو کتابخانه‌ی مستقل.
#
# ---------------------------------------------------------------------------
# یک‌بار روی گوشی:
#
#   1. «Termux» را از F-Droid نصب کن (نه از Google Play — نسخه‌ی Play منسوخ است
#      و پکیج‌هایش آپدیت نمی‌شوند). اختیاری ولی توصیه‌شده: «Termux:Boot» برای
#      بالا آمدن خودکار بعد از روشن‌شدنِ گوشی.
#   2. پوشه‌ی این پروژه (یا دست‌کم `server/` و `scripts/`) را به گوشی ببر —
#      USB، یا زیپ‌شده در «Saved Messages» تلگرام — و در Download/ باز کن.
#   3. در Termux:
#
#        termux-setup-storage      # اجازه‌ی خواندنِ Download
#        bash /storage/emulated/0/Download/MusicBazi/scripts/phone-server.sh
#
#   4. در اپ موزیک بازی: «روی این گوشی».
#
# ---------------------------------------------------------------------------
# فرمان‌ها:
#
#   phone-server.sh [from=<مسیر>]        نصبِ در صورت نیاز + شروعِ سرور
#   phone-server.sh start|stop|restart|status|log
#   phone-server.sh boot                 شروعِ خودکار با روشن‌شدنِ گوشی
#   phone-server.sh cookies <مسیر>       گذاشتنِ cookies.txt برای یوتیوب
#   phone-server.sh proxy <آدرس>         پروکسی (برای شبکه‌ی فیلترشده)
#   phone-server.sh spotify <id> <secret>  اعتبارنامه‌ی اسپاتیفای (نتیجه‌ی جستجو)
#   phone-server.sh loudness-target <lufs> بلندیِ هدفِ هم‌ترازی (پیش‌فرض -14)
#
set -euo pipefail

# ----------------------------------------------------------------- تنظیمات --

# مسیرِ مطلقِ خودِ همین فایل. برای نوشتنِ اسکریپتِ Termux:Boot لازم است: اگر
# `$0` را عیناً بنویسیم و کاربر script را با مسیرِ نسبی اجرا کرده باشد
# (`bash phone-server.sh`)، آن خط در boot دیگر معنایی ندارد و سرور بی‌صدا بالا
# نمی‌آید.
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

PREFIX="$HOME/musicbazi"
PKG_DIR="$PREFIX/app"        # کپیِ پکیجِ app روی گوشی
DATA_DIR="$PREFIX/data"
DOWNLOAD_DIR="$PREFIX/downloads"
PID_FILE="$PREFIX/server.pid"
LOG_FILE="$PREFIX/server.log"
ENV_FILE="$PREFIX/env.sh"       # تنظیماتِ کاربر (کوکی، پروکسی، …)
PORT="${MUSICBAZI_PHONE_PORT:-8000}"

# پکیج‌های Termux. دو دسته‌اند و دلیلِ جدا بودنشان متفاوت است:
#
#   دسته‌ی اول — ابزارِ ساخت. `pydantic-core` از سورس کامپایل می‌شود و به
#     clang/rust/make/pkg-config نیاز دارد. یک‌بار لازم است و بعد می‌تواند
#     بماند؛ حذفش یعنی بیلدِ بعدی می‌شکند.
#   دسته‌ی دوم — خودِ وابستگی‌ها. این‌ها را *نباید* با pip نصب کرد: ویل‌های
#     PyPI برای bionic ساخته نشده‌اند و ساختنشان از سورس یا می‌شکند یا نیم‌ساعت
#     طول می‌کشد. Termux نسخه‌ی سازگارِ آماده‌شان را دارد.
# ffmpeg و nodejs اینجا نیستند که «اختیاری‌اند» — ستونِ فقرات‌اند:
# ffmpeg بدونش هیچ دانلودی کامل نمی‌شود (ترنسکد و امبد کاور) و nodejs هم چالش
# امضای یوتیوب را حل می‌دهد. libchromaprint هم fpcalc را می‌دهد که برای
# تأییدِ AcoustID لازم است؛ نبودنش فقط آن یک بررسیِ اختیاری را خاموش می‌کند.
BUILD_PKGS=(
  binutils clang make pkg-config rust openssl libsqlite python python-pip
  ffmpeg nodejs libchromaprint
)
# python-numpy/scipy/llvmlite: ساختنشان از سورس روی گوشی یا می‌شکند یا نیم‌ساعت
# طول می‌کشد، ولی Termux ویلِ آماده‌شان را دارد. این سه فقط برای *librosa* لازم
#‌اند (تحلیل حس‌وحال) — اگر نصب نشوند سرور باز هم کار می‌کند و شافل تصادفیِ
# ساده می‌شود، پس عمداً در دسته‌ی «اختیاری» هستند و در install() هم با || true
# از کنارشان رد می‌شویم.
NATIVE_PY_PKGS=(python-numpy python-brotli python-pycryptodomex)
MOOD_PKGS=(python-scipy python-llvmlite)

# وابستگی‌های پایتونِ خالص — همان‌هایی که در server/requirements.txt هستند،
# منهای سه چیز که روی گوشی معنا ندارند:
#
#   uvicorn[standard]  → uvloop و httptools C-extension‌اند و روی bionic
#                        ساخته نمی‌شوند. خودِ uvicorn با h11 (پایتونِ خالص)
#                        کار می‌کند؛ تفاوتش فقط چند درصد throughput است که روی
#                        یک دستگاهِ تک‌کاربره هیچ نقشی ندارد.
#   yt-dlp[curl-cffi]  → curl-cffi هم C-extension است. طبقِ کامنتِ خودِ
#                        requirements.txt دلیلِ لازم‌بودنش یک IncompleteRead روی
#                        جستجوی یوتیوب با urllib بود؛ httpx (که fastapi می‌آورد)
#                        همان مشکل را ندارد.
#   librosa            → برای تحلیل حس‌وحال. سنگین‌ترین وابستگیِ کل فهرست است و
#                        فقط دو عدد (valence/energy) به‌دست می‌دهد. اگر numpy و
#                        scipyِ Termux جور شدند نصب می‌شود، وگرنه طبقِ
#                        server/app/mood.py بی‌صدا خاموش می‌ماند و شافل به حالت
#                        تصادفیِ ساده برمی‌گردد — چیزی نمی‌شکند.
#
# آرایه، نه رشته: `httpx[socks]` یک الگوی glob است و اگر بی‌نقل‌در‌آرایه‌ی
# معمولی باز شود، bash می‌تواند آن را با فایلی در پوشه‌ی جاری مطابقت بدهد و
# فرمان pip خراب برود.
PY_PKGS=(fastapi uvicorn 'httpx[socks]' mutagen python-multipart yt-dlp yt-dlp-ejs)

# -------------------------------------------------------------------- رنگ --

if [ -t 1 ]; then
  C_OK=$'\e[32m'; C_WARN=$'\e[33m'; C_ERR=$'\e[31m'; C_DIM=$'\e[2m'; C_OFF=$'\e[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi

say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$C_OK" "$C_OFF" "$*"; }
warn() { printf '%s!%s %s\n' "$C_WARN" "$C_OFF" "$*"; }
die()  { printf '%s✗%s %s\n' "$C_ERR" "$C_OFF" "$*" >&2; exit 1; }
step() { printf '\n%s==>%s %s\n' "$C_OK" "$C_OFF" "$*"; }

# ------------------------------------------------------------------ سورس --

# از کجا سورس را برداریم؟ سه حالت، به‌ترتیبِ اولویت: آرگومانِ from=، متغیرِ
# محیطی، و جست‌وجوی حدسی در Download/. نبودنش خطای راهنما‌دار است، نه یک
# traceback که کاربرِ گوشی با آن هیچ کاری نمی‌تواند بکند.
find_src() {
  local guess
  local script_repo
  script_repo="$(cd "$(dirname "$SCRIPT_PATH")/.." 2>/dev/null && pwd)" || script_repo=""
  for guess in "${FROM_ARG:-}" "${MUSICBAZI_SRC:-}" \
               "$script_repo" \
               "$PWD" \
               "$HOME/Download/MusicBazi" \
               "$HOME/Downloads/MusicBazi" \
               "$HOME/MusicBazi" \
               "/storage/emulated/0/Download/MusicBazi" \
               "/storage/emulated/0/Documents/MusicBazi"; do
    if [ -n "$guess" ] && [ -f "$guess/server/app/main.py" ]; then
      printf '%s\n' "$guess/server"
      return 0
    fi
    # خودِ پوشه‌ی server را هم داده باشند درست است
    if [ -n "$guess" ] && [ -f "$guess/app/main.py" ]; then
      printf '%s\n' "$guess"
      return 0
    fi
  done
  return 1
}

# ------------------------------------------------------------------ نصب --

installed() {
  python -c 'import fastapi, uvicorn, yt_dlp, mutagen, httpx' >/dev/null 2>&1
}

install() {
  local src
  src="$(find_src)" || die "پوشه‌ی پروژه روی گوشی پیدا نشد.
  سورس را با from=<مسیر> بده، مثلاً:
    bash phone-server.sh from=/storage/emulated/0/Download/MusicBazi
  (اول «termux-setup-storage» را زده باشی.)"

  # اجرای دوباره نباید همه‌چیز را از نو بکشد. `pkg install` و به‌ویژه
  # کامپایلِ pydantic-core چند دقیقه طول می‌کشند، و کاربرِ عادی همین script را
  # هر بار که می‌خواهد سرور را روشن کند می‌زند. نشانه‌ی «نصب شده» همان
  # importِ موفق است — نه یک فایلِ پرچم که ممکن است با دستی‌کاری گم شود.
  #
  # سورس با این حال هر بار کپی می‌شود (ارزان است) تا پروژه‌ی تازه‌ی لپ‌تاپ روی
  # گوشی بنشیند.
  local skip=no
  if installed && [ -d "$PKG_DIR" ]; then skip=yes; fi

  if [ "$skip" = yes ]; then
    step "بک‌اند از قبل نصب است — فقط سورس تازه می‌شود"
  else
    step "نصبِ پکیج‌های Termux"
    # `pkg update` تنها وقتی که فهرست پکیج‌ها هیچ‌وقت دانلود نشده — وگرنه هر اجرای
    # script چند دقیقه بی‌دلیل صبر می‌کند. مسیرِ درست: ریشه‌ی Termux یک سطح
    # بالاترِ $HOME است، پس usr/var/lib/dpkg.
    if [ ! -d "$HOME/../usr/var/lib/dpkg" ]; then
      pkg update -y
    fi
    pkg install -y "${BUILD_PKGS[@]}" "${NATIVE_PY_PKGS[@]}"
  fi

  step "کپیِ سورس به $PKG_DIR"
  mkdir -p "$PREFIX"
  rm -rf "$PKG_DIR"
  # کپی، نه symlink: پوشه‌ی shared storage اندروید موقع خوابِ دستگاه کند و گاه
  # ناپدید می‌شود، و SQLite روی آن قفل‌گذاریِ درست ندارد.
  #
  # فقط `app/` — نه کلِ پوشه‌ی server. کپیِ کلِ آن یعنی `.venv` صدهامگابایتی،
  # `data/musicbazi.db` و `downloads/` لپ‌تاپ هم روی گوشی بنشینند: هم فضا را
  # می‌خورند، هم دقیقاً همان چیزی را که این طرح باید جدا نگه دارد با گوشی
  # می‌کنند. سرور برای بالا آمدن جز `app/` به چیزی نیاز ندارد.
  cp -r "$src/app" "$PKG_DIR"
  # .pycهای لپ‌تاپ بی‌فایده‌اند (Python با magic number نسخه را می‌سنجد و از نو
  # می‌سازد) ولی چند مگابایت حجم و گیج‌کننده‌اند
  find "$PKG_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
  ok "$(find "$PKG_DIR" -name '*.py' | wc -l) فایل پایتون"

  if [ "$skip" = no ]; then
    step "نصبِ وابستگی‌های پایتون"
    # PEP 668 روی Termux گاه فعال است؛ متغیرِ محیطی برای pipهای قدیمی بی‌ضرر است
    # (نمی‌شناسدش و نادیده می‌گیرد).
    export PIP_BREAK_SYSTEM_PACKAGES=1
    pip install --upgrade pip wheel setuptools >/dev/null

    # --no-cache-dir: فضای گوشی محدود است و pip پیش‌فرض هم سورسِ فشرده را نگه
    # می‌دارد هم ویلِ ساخته‌شده را.
    #
    # یک فرمان با فهرستِ کامل، نه تک‌تک: pip یک‌بار همه‌چیز را resolve می‌کند و
    # اگر جایی تعارض باشد *قبل* از نصب به ما می‌گوید.
    pip install --no-cache-dir "${PY_PKGS[@]}" || die "نصبِ وابستگی‌های اصلی شکست خورد.
  اگر خطا موقع ساختن pydantic-core بود: pkg install rust clang و دوباره امتحان کن.
  اولین بار چند دقیقه طول می‌کشد (کامپایلِ Rust)."

    if python -c 'import numpy' >/dev/null 2>&1; then
      say "${C_DIM}تحلیل حس‌وحال: numpy هست، بقیه‌ی زنجیره امتحان می‌شود${C_OFF}"
      # || true روی هر دو مرحله: این زنجیره *اختیاری* است. شکستش نباید کاربر را
      # قانع کند نصب خراب شده — طبقِ server/app/mood.py فقط شافل به حالت
      # تصادفیِ ساده برمی‌گردد.
      pkg install -y "${MOOD_PKGS[@]}" >/dev/null 2>&1 || true
      pip install --no-cache-dir librosa >/dev/null 2>&1 \
        && ok "librosa نصب شد — شافلِ هم‌حس‌وحال فعال" \
        || warn "librosa ساخته نشد — شافل تصادفیِ ساده می‌ماند (MUSICBAZI_MOOD=0)"
    else
      warn "numpy در دسترس نیست — تحلیل حس‌وحال خاموش می‌ماند"
    fi
  fi

  step "تنظیماتِ اولیه"
  mkdir -p "$DATA_DIR" "$DOWNLOAD_DIR"
  [ -f "$ENV_FILE" ] || cat > "$ENV_FILE" <<'ENV'
# تنظیماتِ بک‌اندِ گوشی — این فایل را ویرایش کن، script بازنویسی‌اش نمی‌کند.
#
# کوکی یوتیوب: «phone-server.sh cookies <مسیر>» می‌نویسدش. بدونش یوتیوب با
# «Sign in to confirm you're not a bot» رد می‌شود (ساندکلاد کار می‌کند).
export MUSICBAZI_COOKIES_FILE="$HOME/musicbazi/cookies.txt"
#
# پروکسی — برای شبکه‌ای که یوتیوب/کاتالوگ‌ها مستقیم درنمی‌آیند. socks5h یعنی
# DNS هم آن‌طرف حل شود؛ روی شبکه‌ی فیلترشده معمولاً همین تنها حالتِ کاری است.
# «phone-server.sh proxy socks5h://127.0.0.1:1080»
# export MUSICBAZI_PROXY=
#
# اسپاتیفای/دیزر/اپل‌موزیک برای متادیتا لازم‌اند ولی اختیاری‌اند؛ کلیدِ اسپاتیفای
# را همین‌جا بگذار تا لینک‌هایش دقیق خوانده شوند.
# export MUSICBAZI_SPOTIFY_CLIENT_ID=
# export MUSICBAZI_SPOTIFY_CLIENT_SECRET=
ENV
  ok "$ENV_FILE"

  installed || die "نصب تمام شد ولی import نشد. «phone-server.sh log» را ببین."
  ok "بک‌اند آماده است"
}

# ------------------------------------------------------------------ اجرا --

running_pid() {
  [ -f "$PID_FILE" ] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null)" || return 1
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  printf '%s\n' "$pid"
}

# آیا پورت آزاد است؟
#
# پرسیدن از `/api/health` جواب نمی‌دهد: سروری که در بازگشتِ بی‌پایانِ آینه‌ی
# کاور گیر کرده، پورت را نگه داشته ولی هیچ‌وقت پاسخ نمی‌فرستد. اسکریپت آن را
# «روشن نیست» می‌دید، دومی را اسپان می‌کرد و همان `address already in use`
# برمی‌گشت — دقیقاً چیزی که کاربر می‌بیند وقتی «سرور جواب نداد» روی سروری
# می‌آید که فقط معلّق است.
#
# تنها تستِ قابل‌اعتماد، خودِ bind است. `ss` و `lsof` در Termux نصب نیستند،
# ولی پایتون هست.
port_free() {
  python - "$PORT" <<'PY'
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(1)
finally:
    s.close()
PY
}

# کشتنِ هر سرورِ موزیک بازی، از روی /proc.
#
# چرا نه `pkill`: در Termux نیست و `|| true` شکستش را بی‌صدا می‌بلعید — یعنی
# یتیم سرِ جایش می‌ماند و اسکریپت همان bind error را می‌دید. چرا نه PID فایل:
# اندروید شلِ Termux را می‌کشد و فایل ممکن است از اجرایِ قبلیِ *خودِ اسکریپتِ
# قدیمی* مانده باشد یا کلاً نرود.
#
# آرگومان شماره‌ی سیگنال است (پیش‌فرض TERM). سروری که در بازگشتِ بی‌پایان گیر
# کرده، uvicorn را با handlerِ تمیزِ SIGTERM نمی‌بندد — آن handler منتظرِ نخ‌های
# مسدود می‌ماند و نخ‌ها خودشان منتظرِ همان درخواست‌ها. KILL تنها راهِ بیرون از
# آن حالت است.
kill_servers() {
  python - "${1:-TERM}" <<'PY'
import os, signal, sys
sig = getattr(signal, f"SIG{sys.argv[1]}", signal.SIGTERM)
me = os.getpid()
killed = []
for p in os.listdir("/proc"):
    if not p.isdigit() or int(p) == me:
        continue
    try:
        with open(f"/proc/{p}/cmdline", "rb") as fh:
            cmd = fh.read().decode("utf8", "replace")
    except OSError:
        continue
    if "uvicorn" in cmd and "app.main:app" in cmd:
        try:
            os.kill(int(p), sig)
            killed.append(p)
        except OSError:
            pass
print(" ".join(killed))
PY
}

start() {
  if pid="$(running_pid)"; then
    ok "سرور از قبل روشن است (pid $pid)"
    return 0
  fi

  # PID فایل رفته ولی سرور هنوز روی پورت است. این حالتِ عادی است: اندروید
  # پروسه‌ی Termux را می‌کشد و `$PREFIX/server.pid` هم با آن می‌رود، ولی خودِ
  # پایتون یتیم می‌ماند و به سرویس‌دادن ادامه می‌دهد.
  #
  # تشخیص از روی *پورت* است نه از روی `/api/health`: سروری که در آینه‌ی کاور
  # گیر کرده پورت را نگه داشته ولی جواب نمی‌دهد، و با تستِ سلامتی «روشن نیست»
  # حساب می‌شد — اسکریپت دومی را اسپان می‌کرد و `address already in use`
  # برمی‌گشت.
  #
  # یتیم را می‌کشیم، نگه نمی‌داریم: این اسکریپت معمولاً بعد از «سورس تازه شد»
  # اجرا می‌شود و نگه‌داشتنِ سرورِ قدنی یعنی کدِ تازه هیچ‌وقت بارگذاری نشود و
  # کاربر فکر کند آپدیت اثر نکرده.
  if ! port_free; then
    warn "سرورِ اجرایِ قبلی روی پورت $PORT است — می‌بندمش و تازه بالا می‌آورم"
    kill_servers TERM >/dev/null
    # پورت باید واقعاً آزاد شود؛ kill خودِ پایتون چند لحظه طول می‌کشد و
    # اسپانِ فوری همان `address already in use` را برمی‌گرداند
    for _ in $(seq 1 10); do
      port_free && break
      sleep 0.5
    done
    # TERM جواب نداد یعنی پروسه گیر کرده — سرورِ درگیرِ بن‌بستِ نخ،
    # handlerِ تمیزِ uvicorn را رد می‌کند چون منتظرِ کارهای تمام‌نشده می‌ماند
    if ! port_free; then
      warn "بسته نشد؛ با سیگنالِ اجباری"
      kill_servers KILL >/dev/null
      for _ in $(seq 1 10); do
        port_free && break
        sleep 0.5
      done
    fi
    port_free || warn "پورت $PORT هنوز اشغال است — سرور جدید احتمالاً بالا نمی‌آید"
  fi

  installed || { warn "نصب‌نشده — اول نصب می‌کنم"; install; }

  # بیدار نگه‌داشتنِ CPU. بدونش اندروید وسطِ دانلود یا ترنسکدِ ffmpeg پروسه را
  # یخ می‌زند و کار نیمه‌کاره می‌ماند.
  #
  # `|| true` لازم است: بیرون از Termux این فرمان وجود ندارد و `A && B` با
  # شکستِ A کدِ خروجِ غیرصفر می‌دهد — یعنی زیرِ `set -e` کل script می‌مرد.
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock || true

  . "$ENV_FILE" 2>/dev/null || true

  # مسیرها همه محلی‌اند. MUSICBAZI_DATA_DIR را config.py برای DB هم استفاده
  # می‌کند، پس MUSICBAZI_DB لازم نیست.
  export MUSICBAZI_DOWNLOAD_DIR="$DOWNLOAD_DIR"
  export MUSICBAZI_DATA_DIR="$DATA_DIR"

  # MUSICBAZI_FFMPEG *پوشه* است نه مسیر خودِ فایل: config.py آن را به
  # `shutil.which("ffmpeg", path=...)` می‌دهد. اگر فایل بدهیم، which آن را به‌عنوان
  # پوشه جست‌وجو می‌کند، چیزی پیدا نمی‌کند و به fallbackِ PATH می‌افتد — که در
  # Termux تصادفاً همان نتیجه را می‌دهد، ولی اگر ffmpeg روزی بیرونِ PATH باشد
  # (نصبِ دستی) فقط حالتِ پوشه‌ای کار می‌کند. همان چیزی که خودِ config.py در
  # خطِ `FFMPEG_LOCATION` می‌سازد، اینجا هم می‌سازیم.
  if command -v ffmpeg >/dev/null 2>&1; then
    export MUSICBAZI_FFMPEG="$(dirname "$(command -v ffmpeg)")"
  fi
  export MUSICBAZI_JS_RUNTIME="$(command -v node 2>/dev/null || true)"
  export PYTHONUNBUFFERED=1

  # ۱۲۷.۰.۰.1 عمدی است نه 0.0.0.0: سرورِ گوشی نباید روی وای‌فای عمومی هم
  # در دسترس باشد — هیچ رمزی ندارد.
  #
  # از $PREFIX اجرا می‌شود نه از خودِ پکیج: `app.main:app` یعنی «پوشه‌ای که
  # `app` داخلش است»، پس cwd باید *والد*ِ PKG_DIR باشد.
  cd "$PREFIX"
  nohup python -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
    >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # سلامتی را خودمان چک می‌کنیم تا «سرور بالاست» با «سرور بالا آمد و بعد از
  # دو ثانیه مُرد» یکی نشود — وگرنه کاربر در اپ فقط «نرسیدم» می‌بیند.
  local i
  for i in $(seq 1 30); do
    if curl -fsS --max-time 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      ok "سرور روی http://127.0.0.1:$PORT بالا آمد"
      say "${C_DIM}لاگ: phone-server.sh log${C_OFF}"
      return 0
    fi
    running_pid >/dev/null || break
    sleep 0.5
  done
  warn "سرور جواب نداد. آخرین خط‌ها:"
  tail -20 "$LOG_FILE" >&2 || true
  return 1
}

stop() {
  # kill_servers از روی /proc کار می‌کند نه PID فایل: یتیمِ بی‌فایل هم باید با
  # «stop» خاموش شود، وگرنه «سروری روشن نیست» می‌گوییم در حالی که پورت هنوز
  # اشغال است
  local pids
  pids="$(kill_servers TERM)"
  if pid="$(running_pid)"; then
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
  if [ -n "$pids" ]; then
    ok "سرور خاموش شد (pid ${pids})"
  else
    say "سروری روشن نبود."
  fi
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock || true
}

status() {
  if pid="$(running_pid)"; then
    ok "روشن — pid $pid — http://127.0.0.1:$PORT"
    curl -fsS --max-time 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true
    say ""
  elif ! port_free; then
    # پورت اشغال است ولی PID فایل نیست: یتیمِ اجرایِ قبل. اگر health هم جواب
    # ندهد، «معلّق» است — همان حالتی که کاربر می‌بیند «اپ هیچ‌چیز نشان نمی‌دهد»
    warn "یک سرورِ یتیم از اجرایِ قبلی روی پورت $PORT است"
    if curl -fsS --max-time 3 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      say "  جواب می‌دهد. برای تازه‌سازی: phone-server.sh restart"
    else
      say "  جواب نمی‌دهد — گیر کرده. phone-server.sh restart می‌کُشَدش و تازه بالا می‌آورد."
    fi
  else
    say "خاموش است."
  fi
  say "${C_DIM}کتابخانه: $DOWNLOAD_DIR${C_OFF}"
  du -sh "$DOWNLOAD_DIR" 2>/dev/null | awk '{print "  " $1}' || true
}

# ------------------------------------------------------------------ کمکی --

set_cookies() {
  local from="${1:-}"
  [ -n "$from" ] && [ -f "$from" ] || die "فایل کوکی پیدا نشد: $from
  از مرورگرِ لپ‌تاپ خروجی Netscape بگیر (افزونه‌ی Get cookies.txt) و به گوشی
  منتقل کن، بعد مسیرش را بده."
  # `cookies` ممکن است *قبل* از نصبِ اصلی اجرا شود — کاربر اول کوکی‌اش را
  # آماده می‌کند. بدونِ mkdir، cp به پوشه‌ای که نیست می‌خورد.
  mkdir -p "$PREFIX"
  cp "$from" "$PREFIX/cookies.txt"
  chmod 600 "$PREFIX/cookies.txt"
  ok "کوکی گذاشته شد — $PREFIX/cookies.txt"
  warn "اگر سرور روشن است ری‌استارت کن: phone-server.sh restart"
}

set_proxy() {
  local url="${1:-}"
  [ -n "$url" ] || die "آدرس پروکسی ندادی. مثال:
    phone-server.sh proxy socks5h://127.0.0.1:1080"
  mkdir -p "$PREFIX"
  touch "$ENV_FILE"
  # خطِ قبلی را عوض می‌کنیم نه اینکه اضافه‌اش کنیم: دو exportِ MUSICBAZI_PROXY
  # یعنی دومی برنده است و کاربر هیچ‌وقت نمی‌فهمد اولی کجا رفته.
  grep -v '^ *#\? *export MUSICBAZI_PROXY=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf 'export MUSICBAZI_PROXY=%s\n' "\"$url\"" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  ok "پروکسی ست شد: $url"
  warn "ری‌استارت کن: phone-server.sh restart"
}

set_spotify() {
  local cid="${1:-}" secret="${2:-}"
  [ -n "$cid" ] && [ -n "$secret" ] || die "client id و client secret هر دو لازم‌اند. مثال:
    phone-server.sh spotify 4c5f1e… <secret>

  ساخت: developer.spotify.com/dashboard → Create app. یا همان جفتی که روی
  لپ‌تاپ در server/.env داری (MUSICBAZI_SPOTIFY_CLIENT_ID / SECRET)."
  mkdir -p "$PREFIX"
  touch "$ENV_FILE"
  # secret داخلِ این فایل می‌نشیند؛ همان قاعده‌ی کوکی‌ها
  chmod 600 "$ENV_FILE"
  grep -v '^ *#\? *export MUSICBAZI_SPOTIFY_CLIENT_ID=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf 'export MUSICBAZI_SPOTIFY_CLIENT_ID=%s\n' "\"$cid\"" >> "$ENV_FILE.tmp"
  grep -v '^ *#\? *export MUSICBAZI_SPOTIFY_CLIENT_SECRET=' "$ENV_FILE.tmp" > "$ENV_FILE" || true
  printf 'export MUSICBAZI_SPOTIFY_CLIENT_SECRET=%s\n' "\"$secret\"" >> "$ENV_FILE"
  rm -f "$ENV_FILE.tmp"
  ok "اعتبارنامه‌ی اسپاتیفای ست شد"
  warn "ری‌استارت کن: phone-server.sh restart"
}

set_loudness_target() {
  local lufs="${1:-}"
  [ -n "$lufs" ] || die "بلندیِ هدف را ندادی. مثال:
    phone-server.sh loudness-target -10"
  # باید عددی منفی و معقول باشد؛ خارجِ بازه تقریباً همیشه اشتباهِ تایپی است
  python - "$lufs" <<'PY' || die "عددش یک عددِ منفی مثل -10 است، در بازه‌ی -24 تا 0"
import sys
try:
    v = float(sys.argv[1])
except ValueError:
    sys.exit(1)
sys.exit(0 if -24 <= v <= 0 else 1)
PY
  mkdir -p "$PREFIX"
  touch "$ENV_FILE"
  grep -v '^ *#\? *export MUSICBAZI_LOUDNESS_TARGET=' "$ENV_FILE" > "$ENV_FILE.tmp" || true
  printf 'export MUSICBAZI_LOUDNESS_TARGET=%s\n' "\"$lufs\"" >> "$ENV_FILE.tmp"
  mv "$ENV_FILE.tmp" "$ENV_FILE"
  ok "بلندیِ هدف ست شد: $lufs LUFS"
  say "  آهنگ‌های تازه‌دانلود با همین بلندی پخش می‌شوند؛ در اپ هم از تنظیم‌های
  صدا (هم‌ترازیِ بلندی) همان لحظه قابل تنظیم است."
}

enable_boot() {
  command -v termux-wake-lock >/dev/null 2>&1 || warn "Termux:Boot نصب نیست؛ فایل آماده می‌شود ولی خودکار بالا نمی‌آید."
  mkdir -p "$HOME/.termux/boot"
  cat > "$HOME/.termux/boot/musicbazi-server.sh" <<BOOT
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
# مکث، نه بی‌موردی: بعد از روشن‌شدنِ گوشی شبکه هنوز بالا نیامده و سرورِ بی‌شبکه
# موقعِ بالا آمدن فقط خطا لاگ می‌کند.
sleep 20
bash $SCRIPT_PATH start
BOOT
  chmod +x "$HOME/.termux/boot/musicbazi-server.sh"
  ok "شروعِ خودکار فعال شد — \$HOME/.termux/boot/musicbazi-server.sh"
  say "${C_DIM}برای لغو: rm ~/.termux/boot/musicbazi-server.sh${C_OFF}"
}

# ------------------------------------------------------------------ ورودی --

# ورودی: فرمان، آرگومانِ from=، و آرگومان‌های خودِ فرمان — به هر ترتیبی.
#
# ترتیب‌محور نبودن عمدی است: `phone-server.sh from=/sdcard/proj start` چیزی است
# که آدم طبیعی می‌نویسد، و اگر فرمان فقط جای اول را می‌پذیرفت همان‌جا با
# «آرگومانِ ناشناخته: start» می‌مرد.
CMD="install-start"
FROM_ARG=""
EXTRA=()
for a in "$@"; do
  case "$a" in
    from=*) FROM_ARG="${a#from=}" ;;
    start|stop|restart|status|log|boot|cookies|proxy|spotify|loudness-target)
      # اولین فرمان برنده است؛ دومی اگر باشد تایپو است و به EXTRA می‌رود تا
      # پایین‌تر بی‌سروصدا بلعیده نشود
      if [ "$CMD" = "install-start" ]; then CMD="$a"; else EXTRA+=("$a"); fi
      ;;
    *)
      # یک پوشه‌ی تنها، همان مسیرِ سورس است؛ بقیه به فرمانِ خودش می‌رسد
      if [ -z "$FROM_ARG" ] && [ -d "$a" ]; then FROM_ARG="$a"; else EXTRA+=("$a"); fi
      ;;
  esac
done

# آرگومانِ اضافه برای فرمانی که جایی برایش نیست = تایپوی فرمان. بی‌سروصدا
# قورتش نده: `phone-server.sh strt` وگرنه سرور را *نصب* می‌کرد و کاربر فکر
# می‌کرد ری‌استارت کرده.
if [ "${#EXTRA[@]}" -gt 0 ] && [ "$CMD" = "install-start" ]; then
  die "آرگومانِ ناشناخته: ${EXTRA[*]}
  فرمان‌ها: start | stop | restart | status | log | boot | cookies <مسیر> |
    proxy <آدرس> | spotify <client-id> <client-secret> | loudness-target <عدد>
  مسیرِ سورس: from=<مسیر>"
fi

case "$CMD" in
  install-start) install; start ;;
  start)   start ;;
  stop)    stop ;;
  restart) stop; start ;;
  status)  status ;;
  log)     tail -n 60 -f "$LOG_FILE" ;;
  boot)    enable_boot ;;
  # نبودِ آرگومان را خودِ تابعِ هر فرمان با پیامِ درست می‌گوید
  cookies) set_cookies "${EXTRA[0]:-$FROM_ARG}" ;;
  proxy)   set_proxy "${EXTRA[0]:-}" ;;
  spotify) set_spotify "${EXTRA[0]:-}" "${EXTRA[1]:-}" ;;
  loudness-target) set_loudness_target "${EXTRA[0]:-}" ;;
esac
