"""平日リマインドの送信先。"""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import app
import storage
from linebot.v3.messaging.exceptions import ApiException

_ORIG_FETCH = app.fetch_follower_ids


class _DictStore:
    def __init__(self, data: dict) -> None:
        self.data = data

    def load(self) -> dict:
        return json.loads(json.dumps(self.data))

    def save(self, data: dict) -> None:
        self.data.clear()
        self.data.update(json.loads(json.dumps(data)))


def _freeze(day: date) -> type:
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(day.year, day.month, day.day, 16, 30, tzinfo=tz)

    return Fixed


class ReminderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / "users.json"
        self.remote: dict = {}
        storage.configure(self.path, _DictStore(self.remote), env_json=None)
        storage._today = lambda: date(2026, 11, 6)
        self.pushed: list[str] = []
        self.broadcasts: list[str] = []
        self.followers: list[str] | None = None
        app.push_text = lambda user_id, text: self.pushed.append(user_id)  # type: ignore[method-assign]
        app.broadcast_text = lambda text: self.broadcasts.append(text)  # type: ignore[method-assign]
        app.fetch_follower_ids = lambda: self.followers  # type: ignore[method-assign]
        app.datetime = _freeze(date(2026, 11, 6))  # Friday

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_weekend_skips(self) -> None:
        app.datetime = _freeze(date(2026, 11, 7))  # Saturday
        storage.mark_done("U1")
        result = app.send_weekday_reminders()
        self.assertEqual(result["skipped"], "weekend")
        self.assertEqual(self.pushed, [])
        self.assertEqual(self.broadcasts, [])

    def test_push_known_users_after_file_wipe(self) -> None:
        storage.mark_done("Uknown")
        self.path.unlink()
        storage.configure(self.path, _DictStore(self.remote), env_json=None)
        result = app.send_weekday_reminders()
        self.assertEqual(result["mode"], "push")
        self.assertEqual(self.pushed, ["Uknown"])
        self.assertEqual(self.broadcasts, [])

    def test_broadcast_when_registry_empty_and_follower_api_unavailable(self) -> None:
        result = app.send_weekday_reminders()
        self.assertEqual(result["mode"], "broadcast")
        self.assertEqual(len(self.broadcasts), 1)
        self.assertEqual(self.pushed, [])

    def test_follower_ids_are_remembered_and_pushed(self) -> None:
        storage._today = lambda: date(2026, 11, 5)
        storage.mark_done("Uknown")
        self.followers = ["Unew", "Uknown"]
        result = app.send_weekday_reminders()
        self.assertEqual(result["mode"], "push")
        self.assertCountEqual(self.pushed, ["Unew", "Uknown"])
        self.assertEqual(self.broadcasts, [])
        self.assertEqual(storage.get_streak("Uknown")[0], 1)
        self.assertEqual(storage.get_streak("Unew"), (0, None))

    def test_empty_follower_list_does_not_broadcast(self) -> None:
        self.followers = []
        result = app.send_weekday_reminders()
        self.assertEqual(result["mode"], "none")
        self.assertEqual(self.broadcasts, [])

    def test_follower_api_403_returns_none(self) -> None:
        class FakeApi:
            def get_followers(self, start=None, limit=None):
                raise ApiException(status=403, reason="Forbidden")

        app.configuration = object()
        app._api = lambda: FakeApi()  # type: ignore[method-assign]
        self.assertIsNone(_ORIG_FETCH())

    def test_follower_api_paginates(self) -> None:
        class FakeApi:
            def get_followers(self, start=None, limit=None):
                if start is None:
                    return SimpleNamespace(user_ids=["Ua"], next="cursor")
                return SimpleNamespace(user_ids=["Ub"], next=None)

        app.configuration = object()
        app._api = lambda: FakeApi()  # type: ignore[method-assign]
        self.assertEqual(_ORIG_FETCH(), ["Ua", "Ub"])

    def test_cron_requires_secret_and_reports_mode(self) -> None:
        app.CRON_SECRET = "cron-test"
        client = app.app.test_client()
        self.assertEqual(client.post("/cron/remind").status_code, 401)
        response = client.post("/cron/remind", headers={"X-Cron-Secret": "cron-test"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["mode"], "broadcast")
        health = client.get("/").get_json()
        self.assertTrue(health["ok"])
        self.assertTrue(health["durable"])
        self.assertEqual(health["users"], 0)


if __name__ == "__main__":
    unittest.main()
