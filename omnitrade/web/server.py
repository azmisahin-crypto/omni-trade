"""Basit dashboard: equity eğrisi + işlem tablosu. Ekstra bağımlılık yok
(FastAPI/Flask gerekmez) — sadece Python stdlib http.server + sqlite.
İleride FreqUI benzeri bir şeye büyütülebilir ama şimdilik 'çalışan ve
motive eden' bir görünüm için bu yeterli.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from omnitrade.config import Config
from omnitrade.storage import Storage

STATIC_DIR = Path(__file__).parent / "static"


def make_handler(storage: Storage):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # sessiz stdlib logger
            pass

        def _json(self, payload, status=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/trades":
                self._json(storage.get_trades())
            elif self.path == "/api/equity":
                self._json(storage.get_equity_curve())
            elif self.path in ("/", "/index.html"):
                self._serve_static("index.html", "text/html")
            elif self.path == "/app.js":
                self._serve_static("app.js", "application/javascript")
            else:
                self.send_error(404)

        def _serve_static(self, filename: str, content_type: str):
            file_path = STATIC_DIR / filename
            if not file_path.exists():
                self.send_error(404)
                return
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def serve(config: Config) -> None:
    storage = Storage(config.db_path)
    handler = make_handler(storage)
    server = ThreadingHTTPServer(("0.0.0.0", config.web_port), handler)
    print(f"Dashboard: http://localhost:{config.web_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        storage.close()
