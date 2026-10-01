# بک‌اند موزیک بازی — FastAPI + yt-dlp + ffmpeg
FROM python:3.12-slim

# ffmpeg      → ترنسکد و امبد کاور، بدونش هیچ دانلودی کامل نمی‌شود
# nodejs      → JS runtime برای حل چالش امضا/n یوتیوب
# fpcalc      → فینگرپرینت AcoustID (اختیاری، ولی اینجا مفت است)
# ca-certs    → بدونش هر HTTPS به provider ها می‌شکند
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        nodejs \
        libchromaprint-tools \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# لایه‌ی جدا برای وابستگی‌ها: تغییر کد نباید pip install را دوباره اجرا کند
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# دیتابیس و فایل‌ها روی volume می‌نشینند، وگرنه با هر بازسازی ایمیج می‌پرند
ENV MUSICBAZI_DOWNLOAD_DIR=/data/downloads \
    MUSICBAZI_DATA_DIR=/data/db \
    MUSICBAZI_JS_RUNTIME=node \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
