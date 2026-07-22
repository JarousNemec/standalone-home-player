FROM python:3.12-slim

# mpv + libmpv (pro python-mpv) + ffmpeg (yt-dlp) + certifikáty
RUN apt-get update && apt-get install -y --no-install-recommends \
        mpv \
        libmpv2 \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY web ./web

EXPOSE 8080

# PORT lze přepsat přes env; uvicorn poslouchá na všech rozhraních (LAN)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
