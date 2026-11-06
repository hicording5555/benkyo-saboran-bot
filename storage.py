"""ユーザーIDと連続達成の簡易保存（JSON）。"""

from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")
DATA_PATH = Path(__file__).parent / "data" / "users.json"
_lock = threading.Lock()


def _today() -> date:
    return datetime.now(TZ).date()


def _load() -> dict:
    if not DATA_PATH.exists():
        return {}
    with DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_user(user_id: str, display_name: str | None = None) -> dict:
    with _lock:
        data = _load()
        user = data.get(user_id) or {
            "streak": 0,
            "last_done": None,
            "display_name": display_name,
            "joined_at": _today().isoformat(),
        }
        if display_name:
            user["display_name"] = display_name
        data[user_id] = user
        _save(data)
        return user


def all_user_ids() -> list[str]:
    with _lock:
        return list(_load().keys())


def mark_done(user_id: str) -> int:
    """勉強完了を記録し、連続日数を返す。"""
    with _lock:
        data = _load()
        user = data.get(user_id) or {
            "streak": 0,
            "last_done": None,
            "joined_at": _today().isoformat(),
        }
        today = _today()
        last = user.get("last_done")
        if last == today.isoformat():
            # 同日の再送信は連続を増やさない
            data[user_id] = user
            _save(data)
            return int(user.get("streak") or 0)

        if last:
            try:
                last_date = date.fromisoformat(last)
            except ValueError:
                last_date = None
            if last_date == today - timedelta(days=1):
                user["streak"] = int(user.get("streak") or 0) + 1
            elif last_date == today:
                pass
            else:
                user["streak"] = 1
        else:
            user["streak"] = 1

        user["last_done"] = today.isoformat()
        data[user_id] = user
        _save(data)
        return int(user["streak"])


def get_streak(user_id: str) -> tuple[int, str | None]:
    with _lock:
        user = _load().get(user_id) or {}
        return int(user.get("streak") or 0), user.get("last_done")
