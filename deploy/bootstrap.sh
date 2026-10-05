#!/usr/bin/env bash
#
# موزیک بازی را روی یک VM ابری خام (Ubuntu 22.04/24.04) بالا می‌آورد.
# یک‌بار روی VM اجرا کن — بقیه‌اش خودکار است:
#   داکر نصب می‌شود → مخزن کلون می‌شود → ایمیج‌ها بیلد می‌شوند →
#   تونل Cloudflare یک آدرس HTTPS عمومی می‌دهد.
#
#   curl -fsSL https://raw.githubusercontent.com/mahan-mgn/MusicBazi/main/deploy/bootstrap.sh | bash
#
# یا اگر مخزن را دستی کلون کردی، از ریشه‌ی پروژه:
#   bash deploy/bootstrap.sh
#
# آدرس نهایی (https://…trycloudflare.com) آخرِ خروجی چاپ می‌شود.
set -euo pipefail

REPO="https://github.com/mahan-mgn/MusicBazi.git"
DIR="${MUSICBAZI_DIR:-$HOME/musicbazi}"

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mخطا:\033[0m %s\n' "$*" >&2; exit 1; }

# داکر باید باشد؛ روی VM خام نیست. نصب رسمیِ خودِ داکر، بدون حدس زدن پکیج‌ها.
if ! command -v docker >/dev/null 2>&1; then
  log "نصب داکر…"
  curl -fsSL https://get.docker.com | bash
fi
command -v docker >/dev/null 2>&1 || die "داکر نصب نشد."
docker compose version >/dev/null 2>&1 || die "پلاگین docker compose نیست — با get.docker.com باید می‌آمد."

# کاربرِ غیر-root باید در گروه docker باشد تا sudo نخورد. ولی روی VM خام که
# داکر همین الان نصب شده، عضویتِ تازه در گروه در همین session اعمال نمی‌شود و
# docker ps با permission denied می‌افتد. پس تا وقتی که docker بدون sudo کار
# نکند، همه‌ی دستورهای docker را با sudo می‌زنیم.
DOCKER="docker"
if ! docker ps >/dev/null 2>&1; then
  if [ "$(id -u)" != "0" ]; then
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    DOCKER="sudo docker"
    log "داکر با sudo اجرا می‌شود (عضویت در گروه docker دفعه‌ی بعد از نو لاگین اثر می‌کند)."
  fi
fi
$DOCKER ps >/dev/null 2>&1 || die "داکر کار نمی‌کند: sudo systemctl start docker را بزن و دوباره اجرا کن."

# مخزن: اگر همین‌جا داخلش هستیم که هستیم، وگرنه کلون کن.
if [ -f docker-compose.yml ]; then
  DIR="$(pwd)"
  log "داخل مخزن هستیم: $DIR"
elif [ -d "$DIR/.git" ]; then
  log "مخزن موجود، به‌روزرسانی…"
  git -C "$DIR" pull --ff-only
else
  log "کلون مخزن به $DIR…"
  git clone "$REPO" "$DIR"
fi
cd "$DIR"

# فایل .env: اگر نیست از نمونه بساز (همه‌ی مقدارها اختیاری‌اند).
if [ ! -f .env ]; then
  cp .env.docker.example .env
  log ".env ساخته شد از نمونه (کلیدها همه اختیاری‌اند)."
fi

log "بیلد و اجرای پشته (فرانت + بک‌اند + PO Token + تونل)… اولین بار چند دقیقه طول می‌کشد."
$DOCKER compose --profile tunnel up -d --build

# آدرس عمومیِ تونل از لاگِ cloudflared بیرون می‌آید (روی stderr چاپ می‌شود).
log "منتظر آدرس تونل…"
URL=""
for _ in $(seq 1 40); do
  URL="$($DOCKER compose logs tunnel 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 3
done
[ -n "$URL" ] || die "آدرس تونل پیدا نشد. خودت ببین: docker compose logs tunnel"

# صبر تا بک‌اند واقعاً جواب بدهد، نه فقط بالا آمده باشد. از پورت وب روی
# هاست می‌زنیم: کانتینر web همان را map کرده و nginx داخلش /api/ را به بک‌اند
# پروکسی می‌کند — پس اگر /api/health ۲۰۰ داد، کل زنجیره سالم است.
PORT="$(grep -E '^(MUSICBAZI_WEB_PORT|MUSICBAZI_PORT)=' .env 2>/dev/null | tail -1 | cut -d= -f2)"
PORT="${PORT:-8080}"
log "چک سلامت بک‌اند روی پورت $PORT…"
HEALTHY=""
for _ in $(seq 1 30); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$PORT/api/health" 2>/dev/null || true)"
  if [ "$code" = "200" ]; then HEALTHY=1; break; fi
  sleep 2
done
[ -n "$HEALTHY" ] || log "هشدار: /api/health هنوز ۲۰۰ نمی‌دهد. لاگ بک‌اند: docker compose logs server"

cat <<EOF

══════════════════════════════════════════════════════════════
  موزیک بازی بالا آمد.
  آدرس عمومی:  $URL
══════════════════════════════════════════════════════════════

  هشدارها (حتماً بخوان):
  • این آدرس trycloudflare موقتی است — هر بار ری‌استارت تونل عوض می‌شود.
    برای آدرس پایدار به DEPLOY.md نگاه کن (Named Tunnel + دامنه).
  • عمومی و بی‌رمز است — هرکس لینک را داشته باشد به دانلودر دسترسی دارد.
  • دانلود از یوتیوب از آی‌پی دیتاسنتر ممکن است به «bot wall» بخورد.
    راهش (کوکی Netscape در secrets/cookies.txt) در DEPLOY.md هست.

  دستورهای روزمره:
    docker compose logs -f              # همه‌ی لاگ‌ها
    docker compose --profile tunnel logs -f tunnel
    docker compose down                 # خاموش
    docker compose up -d                # دوباره (بدون بیلد)
EOF
