"""耐久ストアと連続日数。"""

from __future__ import annotations

import json
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import storage
from storage import HttpJsonStore, StoreError


class MemoryStore:
    def __init__(self, data: dict | None = None, fail_load: bool = False, fail_save: bool = False) -> None:
        self.data = json.loads(json.dumps(data or {}))
        self.fail_load = fail_load
        self.fail_save = fail_save
        self.saves = 0

    def load(self) -> dict:
        if self.fail_load:
            raise StoreError(503, "down")
        return json.loads(json.dumps(self.data))

    def save(self, data: dict) -> None:
        self.saves += 1
        if self.fail_save:
            raise StoreError(503, "down")
        self.data = json.loads(json.dumps(data))


class StorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "users.json"
        self.store = MemoryStore()
        storage.configure(self.path, self.store, env_json=None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_streak_rules(self) -> None:
        current = {"day": date(2026, 11, 6)}
        storage._today = lambda: current["day"]
        self.assertEqual(storage.mark_done("U1"), 1)
        self.assertEqual(storage.mark_done("U1"), 1)
        current["day"] = date(2026, 11, 7)
        self.assertEqual(storage.mark_done("U1"), 2)
        current["day"] = date(2026, 11, 10)
        self.assertEqual(storage.mark_done("U1"), 1)

    def test_file_wipe_keeps_streak(self) -> None:
        current = {"day": date(2026, 11, 6)}
        storage._today = lambda: current["day"]
        storage.ensure_user("Ufriend", "花")
        self.assertEqual(storage.mark_done("Ufriend"), 1)
        self.path.unlink()
        storage.configure(self.path, self.store, env_json=None)
        storage._today = lambda: current["day"]
        streak, last = storage.get_streak("Ufriend")
        self.assertEqual((streak, last), (1, "2026-11-06"))
        self.assertEqual(storage.all_user_ids(), ["Ufriend"])
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["Ufriend"]["display_name"], "花")
        self.assertIn("Ufriend", self.store.data)

    def test_remote_failure_does_not_erase_remote(self) -> None:
        storage._today = lambda: date(2026, 11, 6)
        storage.mark_done("U1")
        self.store.fail_save = True
        storage._today = lambda: date(2026, 11, 7)
        self.assertEqual(storage.mark_done("U1"), 2)
        self.assertEqual(self.store.data["U1"]["streak"], 1)
        self.assertEqual(storage.get_streak("U1"), (2, "2026-11-07"))

    def test_env_seed_is_pushed_then_survives_without_env(self) -> None:
        seed = json.dumps(
            {"Useed": {"streak": 4, "last_done": "2026-11-01", "joined_at": "2026-10-01"}}
        )
        storage.configure(self.path, self.store, env_json=seed)
        self.assertEqual(storage.get_streak("Useed"), (4, "2026-11-01"))
        self.path.unlink()
        storage.configure(self.path, self.store, env_json=None)
        self.assertEqual(storage.get_streak("Useed"), (4, "2026-11-01"))

    def test_later_last_done_wins_merge(self) -> None:
        self.store.data = {
            "U1": {"streak": 5, "last_done": "2026-11-05", "joined_at": "2026-10-01", "display_name": "元"}
        }
        self.path.write_text(
            json.dumps({"U1": {"streak": 1, "last_done": "2026-11-01", "display_name": "新"}}),
            encoding="utf-8",
        )
        streak, last = storage.get_streak("U1")
        self.assertEqual((streak, last), (5, "2026-11-05"))
        self.assertEqual(storage.status()["users"], 1)

    def test_failed_save_is_retried_on_next_message(self) -> None:
        storage._today = lambda: date(2026, 11, 6)
        self.store.fail_save = True
        storage.mark_done("U1")
        self.assertEqual(self.store.data, {})
        self.store.fail_save = False
        storage.ensure_user("U1")
        self.assertEqual(self.store.data["U1"]["streak"], 1)
        self.assertIsNone(storage.status()["error"])

    def test_status_reports_store_error_without_url(self) -> None:
        self.store.fail_load = True
        info = storage.status()
        self.assertTrue(info["enabled"])
        self.assertEqual(info["users"], 0)
        self.assertIn("StoreError", info["error"])


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_PUT(self) -> None:  # noqa: N802
        self._handle("PUT")

    def _handle(self, method: str) -> None:
        secret = self.headers.get("Security-key")
        if secret != self.server.secret:  # type: ignore[attr-defined]
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"status":1,"message":"Wrong Security key"}')
            return
        self.server.paths.append(self.path)  # type: ignore[attr-defined]
        if method == "PUT":
            length = int(self.headers.get("Content-Length") or 0)
            self.server.document = json.loads(self.rfile.read(length).decode("utf-8"))  # type: ignore[attr-defined]
        body = json.dumps(self.server.document).encode("utf-8")  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


class HttpStoreTest(unittest.TestCase):
    def test_wipe_against_http_document(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.secret = "sek"  # type: ignore[attr-defined]
        server.document = {}  # type: ignore[attr-defined]
        server.paths = []  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        url = f"http://127.0.0.1:{server.server_address[1]}/bin"
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.json"
            store = HttpJsonStore(url, "sek", timeout=2)
            storage.configure(path, store, env_json=None)
            storage._today = lambda: date(2026, 11, 6)
            self.assertEqual(storage.mark_done("Uhttp"), 1)
            path.unlink()
            storage.configure(path, store, env_json=None)
            storage._today = lambda: date(2026, 11, 6)
            self.assertEqual(storage.get_streak("Uhttp"), (1, "2026-11-06"))
            gets = [path for path in server.paths if path.startswith("/bin?")]  # type: ignore[attr-defined]
            self.assertTrue(any("cb=" in path for path in gets))
            bare = HttpJsonStore(url, None, timeout=2)
            with self.assertRaises(StoreError) as caught:
                bare.load()
            self.assertEqual(caught.exception.status, 401)


if __name__ == "__main__":
    unittest.main()
