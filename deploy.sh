#!/usr/bin/env bash
# Tek komutla deploy: en son kodu çeker, image'ları yeniden build edip
# container'ları ayağa kaldırır. `data/` klasörü (SQLite dosyası) volume
# olduğu için pull/rebuild sırasında kaybolmaz.
#
# Kullanım (repo kök dizininde, VM üzerinde):
#   bash deploy.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "==> git pull"
git pull --ff-only

echo "==> docker compose up -d --build"
docker compose up -d --build

echo "==> Son 20 satır log (bot):"
docker compose logs --tail=20 bot

echo "==> Deploy tamamlandı. Durum:"
docker compose ps
