"""友だち登録と連続日数。

`data/users.json` はインスタンス内のキャッシュです。Render 無料枠の
ファイルシステムはスリープや再起動で消えるため、環境変数
`USERS_STORE_URL`（任意で `USERS_STORE_SECRET`）の JSON ドキュメントが
本体です。`USERS_JSON` があれば起動時にマージしますが、書き戻し先には
しません（環境変数の更新にはアカウント全体の API キーが要るため）。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tokyo")
DATA_PATH = Path(__file__).parent / "data" / "users.json"
_MAX_BYTES = 90_000
_MAX_USERS = 5_000
_lock = threading.Lock()
_cache: dict | None = None
_store: "HttpJsonStore | None" = None
_env_json: str | None = None
_last_error: str | None = None
_dirty = False
logger = logging.getLogger("benkyo-saboran.storage")


class StoreError(Exception):
    def __init__(self, status: int | None, message: str) -> None:
        super().__init__(message)
        self.status = status


class HttpJsonStore:
    """GET/PUT する JSON ドキュメント。秘密は Security-key ヘッダで送る。"""

    def __init__(self, url: str, secret: str | None = None, timeout: float = 10.0) -> None:
        self._url = url.strip()
        self._secret = secret.strip() if secret else None
        self._timeout = timeout

    def __repr__(self) -> str:
        return "HttpJsonStore(configured)"

    def load(self) -> dict:
        status, payload = self._request("GET")
        if status == 404:
            return {}
        if not isinstance(payload, dict):
            raise StoreError(status, "store payload is not an object")
        return payload

    def save(self, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) > _MAX_BYTES:
            raise StoreError(None, "store payload is too large")
        status, payload = self._request("PUT", raw)
        if isinstance(payload, dict) and payload.get("status") not in (None, 0):
            raise StoreError(status, "store rejected the write")

    def _request(self, method: str, body: bytes | None = None) -> tuple[int, object]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "benkyo-saboran-bot",
        }
        if self._secret:
            headers["Security-key"] = self._secret
        if body is not None:
            headers["Content-Type"] = "application/json"
        # The bin host caches GET for two hours. A fresh query avoids reading
        # an empty document after a write and then saving that empty copy back.
        url = self._url
        if method == "GET":
            headers["Cache-Control"] = "no-cache"
            headers["Pragma"] = "no-cache"
            url = f"{self._url}{'&' if '?' in self._url else '?'}cb={time.time_ns()}"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        delay = 0.3
        last_error: StoreError | None = None
        for attempt in range(3):
            try:
                return self._read_response(request)
            except StoreError as exc:
                last_error = exc
                if exc.status not in (None, 429, 500, 502, 503, 504) or attempt == 2:
                    raise
                time.sleep(delay)
                delay *= 2
        assert last_error is not None
        raise last_error

    def _read_response(self, request: urllib.request.Request) -> tuple[int, object]:
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                status = response.status
                raw = response.read(_MAX_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(300).decode("utf-8", errors="replace")
            raise StoreError(exc.code, detail[:180] or exc.reason) from None
        except urllib.error.URLError as exc:
            raise StoreError(None, exc.reason.__class__.__name__ if exc.reason else "URLError") from None
        if len(raw) > _MAX_BYTES:
            raise StoreError(status, "store payload is too large")
        if not raw:
            return status, {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise StoreError(status, "store payload is not JSON") from exc
        return status, payload


def configure(
    path: Path | None = None,
    store: HttpJsonStore | None = None,
    env_json: str | None = None,
    *,
    use_env: bool = False,
) -> None:
    """保存先を差し替える。テストとプロセス起動の両方から使う。"""
    global DATA_PATH, _store, _env_json, _cache, _last_error, _dirty
    if path is not None:
        DATA_PATH = path
    if use_env:
        url = os.environ.get("USERS_STORE_URL", "").strip()
        secret = os.environ.get("USERS_STORE_SECRET", "").strip() or None
        _store = HttpJsonStore(url, secret) if url else None
        _env_json = os.environ.get("USERS_JSON")
    else:
        _store = store
        _env_json = env_json
    _cache = None
    _last_error = None
    _dirty = False
    logger.info("耐久ストア: %s", "configured" if _store is not None else "disabled")


def _today() -> date:
    return datetime.now(TZ).date()


def _note_error(exc: BaseException) -> None:
    global _last_error, _dirty
    status = getattr(exc, "status", None)
    _last_error = f"{type(exc).__name__}" + (f" status={status}" if status else "")
    _dirty = True
    logger.warning("耐久ストアに失敗: %s", _last_error)


def _mark_saved() -> None:
    global _last_error, _dirty
    _last_error = None
    _dirty = False


def _normalize_user(user: dict) -> dict:
    try:
        streak = int(user.get("streak") or 0)
    except (TypeError, ValueError):
        streak = 0
    if streak < 0:
        streak = 0
    last = user.get("last_done")
    name = user.get("display_name")
    joined = user.get("joined_at")
    return {
        "streak": streak,
        "last_done": last if isinstance(last, str) and last else None,
        "display_name": name if isinstance(name, str) and name else None,
        "joined_at": joined if isinstance(joined, str) and joined else None,
    }


def _valid_user_id(user_id: object) -> bool:
    return isinstance(user_id, str) and 0 < len(user_id) <= 128 and not user_id.startswith("_")


def _sanitize(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    cleaned: dict = {}
    for user_id, user in data.items():
        if len(cleaned) >= _MAX_USERS:
            break
        if not _valid_user_id(user_id) or not isinstance(user, dict):
            continue
        cleaned[user_id] = _normalize_user(user)
    return cleaned


def _activity_key(user: dict) -> tuple:
    return (user.get("last_done") or "", int(user.get("streak") or 0))


def merge_users(*parts: dict) -> dict:
    """同じユーザーは、より新しい last_done（同日なら大きい streak）を残す。"""
    merged: dict = {}
    for part in parts:
        for user_id, user in _sanitize(part).items():
            current = merged.get(user_id)
            if current is None or _activity_key(user) >= _activity_key(current):
                chosen = dict(user)
                other = current
            else:
                chosen = dict(current)
                other = user
            if other:
                if not chosen.get("display_name") and other.get("display_name"):
                    chosen["display_name"] = other["display_name"]
                if not chosen.get("joined_at"):
                    chosen["joined_at"] = other.get("joined_at")
                elif other.get("joined_at") and other["joined_at"] < chosen["joined_at"]:
                    chosen["joined_at"] = other["joined_at"]
            merged[user_id] = chosen
    return merged


def _read_file() -> dict | None:
    if not DATA_PATH.exists():
        return None
    try:
        with DATA_PATH.open(encoding="utf-8") as handle:
            return _sanitize(json.load(handle))
    except (OSError, json.JSONDecodeError, UnicodeError):
        logger.warning("ローカルの users.json を読めないため無視します")
        return None


def _write_file(data: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(DATA_PATH)


def _env_users() -> dict:
    if not _env_json or not _env_json.strip():
        return {}
    try:
        return _sanitize(json.loads(_env_json))
    except json.JSONDecodeError:
        logger.warning("USERS_JSON が JSON ではないため無視します")
        return {}


def _load_remote() -> dict | None:
    """読めれば辞書、失敗なら None。空のストアは {}。"""
    global _last_error
    if _store is None:
        return None
    try:
        payload = _sanitize(_store.load())
    except Exception as exc:  # noqa: BLE001 - 起動を止めない
        _note_error(exc)
        return None
    _last_error = None
    return payload


def _ensure_loaded() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    local = _read_file()
    remote = _load_remote()
    parts = [part for part in (local, remote, _env_users()) if part]
    merged = merge_users(*parts) if parts else {}
    _cache = merged
    if local != merged:
        _write_file(merged)
    if remote is not None and remote != merged and _store is not None:
        try:
            _store.save(merged)
            _mark_saved()
        except Exception as exc:  # noqa: BLE001
            _note_error(exc)
    elif remote is not None:
        _mark_saved()
    return _cache


def _save(data: dict) -> None:
    global _cache
    _cache = data
    _write_file(data)
    if _store is None:
        _mark_saved()
        return
    try:
        remote = _sanitize(_store.load())
    except Exception as exc:  # noqa: BLE001
        _note_error(exc)
        return
    merged = merge_users(remote, data)
    if merged != data:
        _cache = merged
        _write_file(merged)
    if merged == remote:
        _mark_saved()
        return
    try:
        _store.save(merged)
    except Exception as exc:  # noqa: BLE001
        _note_error(exc)
        return
    _mark_saved()


def _flush() -> None:
    if _dirty and _cache is not None:
        _save(_cache)


def _ready() -> dict:
    _ensure_loaded()
    _flush()
    if _cache is None:
        return {}
    return _cache


def _blank_user(display_name: str | None = None) -> dict:
    return {
        "streak": 0,
        "last_done": None,
        "display_name": display_name,
        "joined_at": _today().isoformat(),
    }


def ensure_user(user_id: str, display_name: str | None = None) -> dict:
    with _lock:
        data = _ready()
        user = data.get(user_id)
        if user is None:
            user = _blank_user(display_name)
            data[user_id] = user
            _save(data)
            return user
        if display_name and user.get("display_name") != display_name:
            user["display_name"] = display_name
            data[user_id] = user
            _save(data)
        return user


def remember_users(user_ids: list[str]) -> None:
    """友だち一覧で見つかった未登録 ID を streak 0 で追加する。"""
    with _lock:
        data = _ready()
        changed = False
        for user_id in user_ids:
            if not _valid_user_id(user_id) or user_id in data:
                continue
            data[user_id] = _blank_user()
            changed = True
        if changed:
            _save(data)


def all_user_ids() -> list[str]:
    with _lock:
        return list(_ensure_loaded().keys())


def mark_done(user_id: str) -> int:
    """勉強完了を記録し、連続日数を返す。"""
    with _lock:
        data = _ready()
        user = data.get(user_id) or _blank_user()
        today = _today()
        last = user.get("last_done")
        if last == today.isoformat():
            data[user_id] = user
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
        return int(_cache[user_id]["streak"]) if _cache and user_id in _cache else int(user["streak"])


def get_streak(user_id: str) -> tuple[int, str | None]:
    with _lock:
        user = _ensure_loaded().get(user_id) or {}
        return int(user.get("streak") or 0), user.get("last_done")


def status() -> dict:
    with _lock:
        data = _ensure_loaded()
        return {
            "enabled": _store is not None,
            "users": len(data),
            "error": _last_error,
        }


configure(use_env=True)
