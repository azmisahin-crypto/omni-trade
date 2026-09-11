#!/usr/bin/env python3
"""Storage.last_heartbeat()'i okuyup bot'un canlı olup olmadığını kontrol
eder. `poll_interval_seconds`'in birkaç katından daha eskiyse (varsayılan:
5x) bot takılmış/çökmüş demektir — Telegram'a `system_alert()` ile haber
verir ve `docker restart` ile container'ı yeniden başlatır.

Host üzerinde (container İÇİNDE DEĞİL) cron ile 5 dakikada bir çalıştırılmak
üzere tasarlandı — container'ı kendi kendine restart edemeyeceği için
docker CLI'a host'tan erişim gerekiyor.

Cron örneği (crontab -e):
    */5 * * * * cd /path/to/omni-trade && python3 scripts/healthcheck.py >> data/healthcheck.log 2>&1

Kullanım:
    python3 scripts/healthcheck.py [--config config/config.yaml] [--stale-multiplier 5]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omnitrade.config import load_config
from omnitrade.notifier.telegram import TelegramNotifier
from omnitrade.storage import Storage

CONTAINER_NAME = "omnitrade-bot"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument(
        "--stale-multiplier", type=float, default=5.0,
        help="Heartbeat, poll_interval_seconds'in kaç katından eskiyse stale sayılır.",
    )
    parser.add_argument(
        "--container", default=CONTAINER_NAME,
        help="Restart edilecek docker container adı.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    notifier = TelegramNotifier(config.telegram.token, config.telegram.chat_id, config.telegram.enabled)

    storage = Storage(config.db_path)
    last = storage.last_heartbeat()
    storage.close()

    threshold = config.poll_interval_seconds * args.stale_multiplier
    now = time.time()

    if last is None:
        # Bot hiç çalışmamış olabilir (ilk kurulum) — henüz alarm verme,
        # sadece logla.
        print("Heartbeat kaydı yok — bot henüz hiç çalışmamış olabilir.")
        return 0

    age = now - last
    if age <= threshold:
        print(f"OK — son heartbeat {age:.0f}s önce (eşik: {threshold:.0f}s).")
        return 0

    message = (
        f"Bot yanıt vermiyor: son heartbeat {age:.0f}s önce "
        f"(eşik: {threshold:.0f}s). Container '{args.container}' restart ediliyor."
    )
    print(message)
    notifier.system_alert(message)

    try:
        subprocess.run(["docker", "restart", args.container], check=True, timeout=60)
        notifier.system_alert(f"Container '{args.container}' restart edildi.")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        error_msg = f"Container restart BAŞARISIZ oldu: {exc}"
        print(error_msg, file=sys.stderr)
        notifier.system_alert(error_msg)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
