#!/usr/bin/env bash
# supervisor ساده‌ی Railway: سه پروسه، یک کانتینر.
# nginx پروسه‌ی جلو (PID 1) است؛ اگر بمیرد کانتینر می‌میرد و Railway
# (restartPolicyType=ALWAYS) دوباره بالا می‌آورد. uvicorn تنها نمی‌میرد —
# حلقه‌ی ری‌استارت نگهش می‌دارد، چون ویزاردِ راه‌اندازی با os._exit(0)
# ری‌استارت می‌کند و در کانتینرِ Railway کسی جز همین حلقه نیست که به‌جایش
# بنشیند (در compose این کار را restart: unless-stopped می‌کرد).
set -u

mkdir -p /data/downloads /data/db

# --- سرور PO Token (یوتیوب) — حالت HTTP: main.js روی ۴۴۱۶ (همان پینگِ compose) ---
(
  cd /opt/bgutil/server
  while :; do
    node build/main.js || { echo "[potoken] exited, restart in 3s" >&2; sleep 3; }
  done
) &

# --- بک‌اند FastAPI ---
(
  cd /app/server
  while :; do
    uvicorn app.main:app --host 127.0.0.1 --port 8000
    echo "[server] exited, restart in 3s" >&2
    sleep 3
  done
) &

# --- nginx: فرانت + پروکسی /api ---
# Railway پورت را با env می‌دهد؛ nginx داینامیک نمی‌فهمد، پس جای‌گذاری می‌شود
# (الگو فضای خالی ابتدای خط را هم می‌خورد چون کانفیک listen را با ایندنت دارد)
sed -i "s/^[[:space:]]*listen .*/    listen ${PORT:-8080};/" /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
