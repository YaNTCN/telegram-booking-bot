FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot
COPY data/salon.json ./data/salon.json

RUN useradd --create-home --uid 1000 bot && mkdir -p /app/data/db && chown bot /app/data/db
USER bot

ENV DB_PATH=/app/data/db/bookings.sqlite3
CMD ["python", "-m", "bot"]
