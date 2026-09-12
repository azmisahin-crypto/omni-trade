"""Basit dashboard: equity eğrisi + işlem tablosu. Ekstra bağımlılık yok
(FastAPI/Flask gerekmez) — sadece Python stdlib http.server + sqlite.
İleride FreqUI benzeri bir şeye büyütülebilir ama şimdilik 'çalışan ve
motive eden' bir görünüm için bu yeterli.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from omnitrade.backtest import run_backtest, run_walk_forward
from omnitrade.config import Config, normalize_pair, update_pairs
from omnitrade.exchange import ExchangeClient
from omnitrade.stats import compute_drawdown_curve, compute_summary_stats
from omnitrade.storage import Storage
from omnitrade.strategies import get_strategy, list_strategies

STATIC_DIR = Path(__file__).parent / "static"


def make_handler(storage: Storage, config: Config):
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
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/api/trades":
                self._json(storage.get_trades())
            elif path == "/api/equity":
                self._json(storage.get_equity_curve())
            elif path == "/api/stats":
                # Faz 3: drawdown grafiği + özet istatistik (toplam getiri,
                # kazanma oranı) — önceden dashboard'da sadece equity eğrisi
                # ve işlem tablosu vardı.
                trades = storage.get_trades(limit=100000)
                equity_curve = storage.get_equity_curve(limit=100000)
                summary = compute_summary_stats(trades, equity_curve)
                self._json({
                    "summary": asdict(summary),
                    "drawdown_curve": compute_drawdown_curve(equity_curve),
                })
            elif path == "/api/signals":
                # Tüm coinler için EN SON sinyal — pozisyon açılmasa bile
                # her coinin güncel durumunu gösteren panel bunu kullanır.
                self._json(storage.get_latest_signals())
            elif path == "/api/signals/history":
                symbol = (query.get("symbol") or [None])[0]
                limit = int((query.get("limit") or [500])[0])
                self._json(storage.get_signals(symbol=symbol, limit=limit))
            elif path == "/api/strategies":
                # Dashboard'daki "Strateji Test Et" paneli, dropdown'ı ve
                # parametre formunu bu listeden otomatik kurar — yeni bir
                # strateji eklendiğinde (STRATEGIES sözlüğüne kayıt) burada
                # da otomatik görünür, frontend değişikliği gerekmez.
                self._json(list_strategies())
            elif path == "/api/config/pairs":
                # Faz 10: dashboard'daki "Coin Yönetimi" paneli şu an
                # config'te (in-memory, bu web sürecinde) tanımlı pariteleri
                # buradan okur.
                self._json({"pairs": list(config.pairs)})
            elif path in ("/", "/index.html"):
                self._serve_static("index.html", "text/html")
            elif path == "/app.js":
                self._serve_static("app.js", "application/javascript")
            else:
                self.send_error(404)

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/backtest":
                self._handle_backtest()
            elif parsed.path == "/api/backtest/batch":
                self._handle_backtest_batch()
            elif parsed.path == "/api/config/pairs":
                self._handle_config_pairs()
            else:
                self.send_error(404)

        def _handle_backtest(self):
            """Faz 6: dashboard'dan tıklamayla backtest/walk-forward çalıştır —
            önceden bunun için terminalde CSV indirip `cli.py backtest`
            çağırmak gerekiyordu. Mantık AYNI (`omnitrade/backtest.py`),
            sadece tetikleme yolu artık HTTP. Borsadan canlı OHLCV çeker
            (dry-run'daki gibi salt-okunur, emir gönderilmez), bu yüzden
            birkaç saniye sürebilir — ThreadingHTTPServer sayesinde bu
            sırada dashboard'un normal GET polling'i bloklanmaz.
            """
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw_body = self.rfile.read(length) if length else b"{}"
                req = json.loads(raw_body or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json({"error": "Geçersiz JSON gövdesi."}, status=400)
                return

            symbol = req.get("symbol")
            if not symbol:
                self._json({"error": "'symbol' zorunlu."}, status=400)
                return

            timeframe = req.get("timeframe") or config.timeframe
            limit = max(50, min(int(req.get("limit") or 1000), 1500))
            n_splits = max(1, min(int(req.get("walk_forward") or 4), 12))

            # Öncelik: istekte açıkça verilen strateji/params > config.yaml'daki
            # pair_strategies override'ı > genel config.strategy/strategy_params.
            # Böylece "şu an canlıda bu coin için ne çalışıyorsa onu test et"
            # varsayılanı korunur, ama dashboard'dan farklı parametre deneyip
            # canlı config'e dokunmadan sonucu görebilirsin.
            pair_override = config.pair_strategies.get(symbol, {})
            strategy_name = req.get("strategy") or pair_override.get("strategy") or config.strategy
            params = req.get("params")
            if params is None:
                if pair_override.get("strategy") == strategy_name:
                    params = pair_override.get("params")
                elif strategy_name == config.strategy:
                    params = config.strategy_params

            try:
                strategy = get_strategy(strategy_name, params)
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
                return

            try:
                exchange = ExchangeClient(config.exchange.name, config.exchange.api_key, config.exchange.api_secret, dry_run=True)
                df = exchange.fetch_ohlcv_df(symbol, timeframe=timeframe, limit=limit)
            except Exception as exc:  # noqa: BLE001 - ccxt/ağ çok çeşitli hata tipi fırlatabilir
                self._json({"error": f"Geçmiş veri çekilemedi: {exc}"}, status=502)
                return

            try:
                if n_splits > 1:
                    results = run_walk_forward(
                        df, strategy, symbol, n_splits=n_splits,
                        fee_pct=config.fee_pct, slippage_pct=config.slippage_pct,
                        risk_config=config.risk,
                    )
                else:
                    results = [run_backtest(
                        df, strategy, symbol,
                        fee_pct=config.fee_pct, slippage_pct=config.slippage_pct,
                        risk_config=config.risk,
                    )]
            except Exception as exc:  # noqa: BLE001
                self._json({"error": f"Backtest çalıştırılamadı: {exc}"}, status=500)
                return

            if not results:
                self._json({
                    "error": "Yeterli veri yok — mum sayısını artır ya da dönem sayısını azalt.",
                }, status=400)
                return

            payload = {
                "symbol": symbol,
                "timeframe": timeframe,
                "candles": len(df),
                "strategy": strategy_name,
                "params": params or {},
                "walk_forward": n_splits,
                "periods": [
                    {
                        "label": r.symbol,
                        "trades": r.trades,
                        "total_return_pct": r.total_return_pct,
                        "win_rate": r.win_rate,
                        "max_drawdown_pct": r.max_drawdown_pct,
                    }
                    for r in results
                ],
            }
            if len(results) > 1:
                returns = [r.total_return_pct for r in results]
                payload["avg_return_pct"] = sum(returns) / len(returns)
                payload["worst_period_pct"] = min(returns)
                payload["best_period_pct"] = max(returns)
            self._json(payload)

        def _handle_backtest_batch(self):
            """Faz 9: leaderboard — birden fazla strateji × coin kombinasyonunu
            TEK istekte çalıştırıp getiriye göre sıralı döner. Her sembol için
            OHLCV verisi bir kez çekilir (kombinasyon sayısı kadar değil),
            borsaya gereksiz tekrar istek atılmasın diye. Her strateji kendi
            varsayılan parametreleriyle çalışır (canlı config'i etkilemez,
            `pair_strategies`'i override etmez) — amaç "hangi strateji bu
            coinde genel olarak daha iyi" sorusuna hızlı, kaba bir cevap.
            """
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw_body = self.rfile.read(length) if length else b"{}"
                req = json.loads(raw_body or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json({"error": "Geçersiz JSON gövdesi."}, status=400)
                return

            symbols = req.get("symbols") or []
            strategies = req.get("strategies") or []
            if not symbols or not strategies:
                self._json({"error": "'symbols' ve 'strategies' listeleri zorunlu."}, status=400)
                return

            timeframe = req.get("timeframe") or config.timeframe
            limit = max(50, min(int(req.get("limit") or 1000), 1500))
            n_splits = max(1, min(int(req.get("walk_forward") or 4), 12))

            try:
                exchange = ExchangeClient(config.exchange.name, config.exchange.api_key, config.exchange.api_secret, dry_run=True)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": f"Borsa bağlantısı kurulamadı: {exc}"}, status=502)
                return

            dfs = {}
            for symbol in symbols:
                try:
                    dfs[symbol] = exchange.fetch_ohlcv_df(symbol, timeframe=timeframe, limit=limit)
                except Exception as exc:  # noqa: BLE001
                    self._json({"error": f"{symbol} için geçmiş veri çekilemedi: {exc}"}, status=502)
                    return

            rows = []
            for symbol in symbols:
                df = dfs[symbol]
                for strategy_name in strategies:
                    try:
                        strategy = get_strategy(strategy_name, None)
                    except ValueError as exc:
                        rows.append({"symbol": symbol, "strategy": strategy_name, "error": str(exc)})
                        continue
                    try:
                        if n_splits > 1:
                            results = run_walk_forward(
                                df, strategy, symbol, n_splits=n_splits,
                                fee_pct=config.fee_pct, slippage_pct=config.slippage_pct,
                                risk_config=config.risk,
                            )
                        else:
                            results = [run_backtest(
                                df, strategy, symbol,
                                fee_pct=config.fee_pct, slippage_pct=config.slippage_pct,
                                risk_config=config.risk,
                            )]
                    except Exception as exc:  # noqa: BLE001
                        rows.append({"symbol": symbol, "strategy": strategy_name, "error": str(exc)})
                        continue
                    if not results:
                        rows.append({"symbol": symbol, "strategy": strategy_name, "error": "yetersiz veri"})
                        continue

                    returns = [r.total_return_pct for r in results]
                    rows.append({
                        "symbol": symbol,
                        "strategy": strategy_name,
                        "periods": len(results),
                        "trades": sum(r.trades for r in results),
                        "avg_return_pct": sum(returns) / len(returns),
                        "worst_period_pct": min(returns),
                        "best_period_pct": max(returns),
                        "avg_win_rate": sum(r.win_rate for r in results) / len(results),
                        "avg_max_drawdown_pct": sum(r.max_drawdown_pct for r in results) / len(results),
                    })

            # En iyisi üstte — hata satırları (avg_return_pct yok) en sona düşer.
            rows.sort(key=lambda r: r.get("avg_return_pct", float("-inf")), reverse=True)

            self._json({
                "timeframe": timeframe,
                "walk_forward": n_splits,
                "candles": {s: len(dfs[s]) for s in symbols},
                "results": rows,
            })

        def _handle_config_pairs(self):
            """Faz 10: dashboard'dan coin ekle/çıkar — önceden `pairs` listesi
            sadece SSH'lanıp `config/config.yaml`'ı elle düzenleyerek
            değiştirilebiliyordu. Gövde: `{"symbol": "SOL/USDT", "action":
            "add"|"remove"}`.

            Bilerek YAPILMAYAN: bu isteğin çalışan bot sürecini (ayrı
            container) canlı olarak etkilemesi — config sadece dosyaya
            yazılır, bot'un yeni pariteyi görmesi için yeniden başlatılması
            gerekir. Bu yüzden yanıt her zaman `restart_required: true`
            döner ve dashboard bunu kullanıcıya açıkça gösterir. Otomatik
            restart (örn. docker socket üzerinden) bilinçli olarak
            eklenmedi — web container'ına docker'ı kontrol etme yetkisi
            vermek, "canlı pariteyi dashboard'dan değiştirebilme"
            kolaylığına göre orantısız bir güvenlik/blast-radius artışı
            olurdu.
            """
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw_body = self.rfile.read(length) if length else b"{}"
                req = json.loads(raw_body or b"{}")
            except (ValueError, json.JSONDecodeError):
                self._json({"error": "Geçersiz JSON gövdesi."}, status=400)
                return

            action = req.get("action")
            raw_symbol = req.get("symbol")
            if action not in ("add", "remove"):
                self._json({"error": "'action' 'add' ya da 'remove' olmalı."}, status=400)
                return
            if not raw_symbol:
                self._json({"error": "'symbol' zorunlu."}, status=400)
                return

            try:
                symbol = normalize_pair(raw_symbol)
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
                return

            current = list(config.pairs)

            if action == "add":
                if symbol in current:
                    self._json({"error": f"{symbol} zaten listede."}, status=400)
                    return
                new_pairs = current + [symbol]
            else:
                if symbol not in current:
                    self._json({"error": f"{symbol} listede değil."}, status=400)
                    return
                if len(current) <= 1:
                    self._json({"error": "En az bir coin kalmalı — son pariteyi silemezsin."}, status=400)
                    return
                new_pairs = [p for p in current if p != symbol]

            try:
                update_pairs(config.config_path, new_pairs)
            except OSError as exc:
                self._json({"error": f"config.yaml yazılamadı: {exc}"}, status=500)
                return

            # In-memory config'i de güncelle — bu WEB sürecinin kendi
            # görünümü tutarlı kalsın diye (örn. hemen ardından GET
            # /api/config/pairs çağrılırsa yeni listeyi görsün). Ayrı bir
            # süreç olan bot container'ını ETKİLEMEZ, bkz. yukarıdaki not.
            config.pairs = new_pairs

            self._json({
                "pairs": new_pairs,
                "restart_required": True,
                "message": (
                    "config.yaml güncellendi. Çalışan bota bunu fark "
                    "ettirmek için `docker compose restart bot` (ya da "
                    "`deploy.sh`) çalıştırman gerekiyor."
                ),
            })

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
    handler = make_handler(storage, config)
    server = ThreadingHTTPServer(("0.0.0.0", config.web_port), handler)
    print(f"Dashboard: http://localhost:{config.web_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        storage.close()
