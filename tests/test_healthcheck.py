import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from omnitrade.storage import Storage

import healthcheck  # noqa: E402  (scripts/ dizininden, sys.path ile eklendi)


class TestHealthcheck(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.db_path = str(Path(self._tmpdir.name) / "test.db")
        self.config_path = str(Path(self._tmpdir.name) / "config.yaml")
        Path(self.config_path).write_text(f"db_path: {self.db_path}\npoll_interval_seconds: 60\n")

    @patch("healthcheck.subprocess.run")
    def test_fresh_heartbeat_does_not_restart(self, mock_run):
        storage = Storage(self.db_path)
        storage.beat()
        storage.close()

        # main() argparse kullanıyor, doğrudan sys.argv ile çağırıyoruz:
        with patch.object(sys, "argv", ["healthcheck.py", "--config", self.config_path]):
            rc = healthcheck.main()
        self.assertEqual(rc, 0)
        mock_run.assert_not_called()

    @patch("healthcheck.subprocess.run")
    def test_stale_heartbeat_triggers_restart(self, mock_run):
        storage = Storage(self.db_path)
        # Elle çok eski bir heartbeat yaz (5 dakika önce, eşik 60*5=300s -> tam sınırda
        # olmasın diye 10 dakika öncesini kullanıyoruz).
        storage.conn.execute(
            "INSERT INTO heartbeat (id, ts) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET ts = excluded.ts",
            (time.time() - 600,),
        )
        storage.conn.commit()
        storage.close()

        with patch.object(sys, "argv", ["healthcheck.py", "--config", self.config_path]):
            rc = healthcheck.main()
        self.assertEqual(rc, 0)
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        self.assertIn("docker", args[0])
        self.assertIn("restart", args[0])

    @patch("healthcheck.subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker"))
    def test_restart_failure_returns_nonzero(self, mock_run):
        storage = Storage(self.db_path)
        storage.conn.execute(
            "INSERT INTO heartbeat (id, ts) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET ts = excluded.ts",
            (time.time() - 600,),
        )
        storage.conn.commit()
        storage.close()

        with patch.object(sys, "argv", ["healthcheck.py", "--config", self.config_path]):
            rc = healthcheck.main()
        self.assertEqual(rc, 1)

    def test_no_heartbeat_yet_is_not_an_error(self):
        # DB var ama hiç beat() çağrılmamış (yeni kurulum senaryosu).
        Storage(self.db_path).close()
        with patch.object(sys, "argv", ["healthcheck.py", "--config", self.config_path]):
            rc = healthcheck.main()
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
