FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libraqm0 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m bot && mkdir -p /app/data /app/logs && chown -R bot /app
USER bot
# Waits for the database, applies migrations (creates tables), then starts the bot
CMD ["sh", "-c", "python scripts/wait_for_db.py && alembic upgrade head && python main.py"]
