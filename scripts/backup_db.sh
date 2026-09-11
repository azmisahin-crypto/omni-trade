#!/usr/bin/env bash
# Faz 3: SQLite veritabanının günlük yedeğini alır.
#
# `sqlite3 .backup` kullanır (cp/rsync yerine) çünkü bot WAL modunda
# çalışıyor (bkz. storage.py) — dosyayı doğrudan kopyalamak yazma sırasında
# yarım/bozuk bir kopya alma riski taşır, `.backup` komutu SQLite'ın kendi
# tutarlı anlık görüntü mekanizmasını kullanır.
#
# Kullanım:
#   bash scripts/backup_db.sh [db_path] [backup_dir]
#
# Varsayılanlar: data/omnitrade.db -> data/backups/omnitrade_YYYYmmdd_HHMMSS.db
#
# Cron örneği (her gün 03:00'te, host üzerinde — container içinde değil):
#   0 3 * * * cd /path/to/omni-trade && bash scripts/backup_db.sh >> data/backup.log 2>&1
#
# Eski yedekleri temizlemek istersen (örn. 14 günden eski):
#   find data/backups -name 'omnitrade_*.db' -mtime +14 -delete

set -euo pipefail

DB_PATH="${1:-data/omnitrade.db}"
BACKUP_DIR="${2:-data/backups}"

if [ ! -f "$DB_PATH" ]; then
  echo "Uyarı: $DB_PATH bulunamadı — bot henüz hiç çalışmamış olabilir, yedek atlanıyor." >&2
  exit 0
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEST="$BACKUP_DIR/omnitrade_${TIMESTAMP}.db"

sqlite3 "$DB_PATH" ".backup '$DEST'"
echo "Yedek alındı: $DEST ($(du -h "$DEST" | cut -f1))"
