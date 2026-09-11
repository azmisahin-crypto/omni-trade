FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Varsayılan: bot döngüsü. `docker compose run omnitrade python -m omnitrade.cli web`
# ile dashboard'u ayrı başlatabilirsin.
CMD ["python", "-m", "omnitrade.cli", "run"]
