FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini alembic.ini
COPY alembic alembic
COPY app app

# DB-IP Country MMDB в образе — на Railway не зависит от скачивания при старте контейнера.
# Лицензия CC BY 4.0: https://db-ip.com
RUN mkdir -p data && curl -fsSL --retry 3 --connect-timeout 20 --max-time 180 \
    -o data/dbip-country.mmdb \
    "https://cdn.jsdelivr.net/npm/@ip-location-db/dbip-country-mmdb@latest/dbip-country.mmdb" \
    && python -c "import os; s=os.path.getsize('data/dbip-country.mmdb'); assert s>1_000_000, s"

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
