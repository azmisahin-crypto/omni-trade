import tempfile
import unittest
from pathlib import Path

from omnitrade.storage import Storage


class TestSignalsStorage(unittest.TestCase):
    """`signals` tablosu: her ÜRETİLEN sinyali (hold dahil) tutar — dashboard
    'pozisyona girilmese bile tüm coinler için sinyal' panelini buradan
    besler. `trades` tablosundan farkı: gerçekleşmemiş sinyaller de burada."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = str(Path(self._tmpdir.name) / "test.db")
        self.storage = Storage(self.db_path)
        self.addCleanup(self.storage.close)

    def test_log_signal_persists_hold_signals_too(self):
        self.storage.log_signal("BTC/USDT", "hold", 100.0, reason="RSI=50")
        signals = self.storage.get_signals("BTC/USDT")
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]["action"], "hold")
        self.assertEqual(signals[0]["executed"], 0)

    def test_get_latest_signals_returns_one_per_symbol(self):
        self.storage.log_signal("BTC/USDT", "hold", 100.0)
        self.storage.log_signal("BTC/USDT", "buy", 101.0, executed=True)
        self.storage.log_signal("ETH/USDT", "sell", 5.0, executed=False)

        latest = self.storage.get_latest_signals()
        by_symbol = {s["symbol"]: s for s in latest}

        self.assertEqual(len(latest), 2)
        self.assertEqual(by_symbol["BTC/USDT"]["action"], "buy")  # en son yazılan
        self.assertEqual(by_symbol["ETH/USDT"]["action"], "sell")

    def test_get_signals_filters_by_symbol_and_orders_chronologically(self):
        self.storage.log_signal("BTC/USDT", "hold", 100.0)
        self.storage.log_signal("ETH/USDT", "hold", 5.0)
        self.storage.log_signal("BTC/USDT", "buy", 101.0, executed=True)

        btc_signals = self.storage.get_signals("BTC/USDT")
        self.assertEqual(len(btc_signals), 2)
        self.assertEqual([s["action"] for s in btc_signals], ["hold", "buy"])

    def test_get_signals_without_symbol_returns_all(self):
        self.storage.log_signal("BTC/USDT", "hold", 100.0)
        self.storage.log_signal("ETH/USDT", "hold", 5.0)
        all_signals = self.storage.get_signals()
        self.assertEqual(len(all_signals), 2)

    def test_get_signals_respects_limit(self):
        for i in range(10):
            self.storage.log_signal("BTC/USDT", "hold", 100.0 + i)
        limited = self.storage.get_signals("BTC/USDT", limit=3)
        self.assertEqual(len(limited), 3)
        # En yeni 3 kayıt, kronolojik sırada dönmeli
        self.assertEqual([s["price"] for s in limited], [107.0, 108.0, 109.0])


class TestModeAuditLog(unittest.TestCase):
    """Faz 16: canlı/dry-run geçiş denetim kaydı — sadece ekleme/okuma,
    güncelleme ya da silme metodu yok (bkz. storage.py SCHEMA yorumu)."""

    def setUp(self):
        self.storage = Storage(":memory:")

    def tearDown(self):
        self.storage.close()

    def test_log_and_read_back_a_mode_change(self):
        self.storage.log_mode_change(
            action="go_live", old_dry_run=True, new_dry_run=False,
            old_live_trading_confirmed=False, new_live_trading_confirmed=True,
            username="admin", ip="127.0.0.1",
        )
        entries = self.storage.get_mode_audit_log()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["action"], "go_live")
        self.assertEqual(entry["username"], "admin")
        self.assertEqual(entry["ip"], "127.0.0.1")
        self.assertEqual(entry["old_dry_run"], 1)
        self.assertEqual(entry["new_dry_run"], 0)
        self.assertEqual(entry["old_live_trading_confirmed"], 0)
        self.assertEqual(entry["new_live_trading_confirmed"], 1)

    def test_most_recent_entry_first(self):
        self.storage.log_mode_change(
            action="go_live", old_dry_run=True, new_dry_run=False,
            old_live_trading_confirmed=False, new_live_trading_confirmed=True,
        )
        self.storage.log_mode_change(
            action="go_dry_run", old_dry_run=False, new_dry_run=True,
            old_live_trading_confirmed=True, new_live_trading_confirmed=False,
        )
        entries = self.storage.get_mode_audit_log()
        self.assertEqual(entries[0]["action"], "go_dry_run")
        self.assertEqual(entries[1]["action"], "go_live")

    def test_respects_limit(self):
        for i in range(5):
            self.storage.log_mode_change(
                action="go_live", old_dry_run=True, new_dry_run=False,
                old_live_trading_confirmed=False, new_live_trading_confirmed=True,
            )
        self.assertEqual(len(self.storage.get_mode_audit_log(limit=2)), 2)

    def test_no_update_or_delete_method_exists(self):
        # Bilinçli tasarım kararı: bu tablo API üzerinden salt-okunur olsun
        # diye Storage sınıfında UPDATE/DELETE yapan hiçbir metod yok.
        self.assertFalse(hasattr(self.storage, "update_mode_audit_log"))
        self.assertFalse(hasattr(self.storage, "delete_mode_audit_log"))
        self.assertFalse(hasattr(self.storage, "clear_mode_audit_log"))


if __name__ == "__main__":
    unittest.main()
