"""べんきょうサボらんBot — LINE webhook + 平日16:30リマインド。"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    BroadcastRequest,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.messaging.exceptions import ApiException
from linebot.v3.webhooks import (
    FollowEvent,
    MessageEvent,
    TextMessageContent,
)

import messages
import storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("benkyo-saboran")

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")
CHANNEL_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")
ENABLE_INTERNAL_SCHEDULER = os.environ.get("ENABLE_INTERNAL_SCHEDULER", "0") == "1"
TZ = ZoneInfo("Asia/Tokyo")

app = Flask(__name__)
handler = WebhookHandler(CHANNEL_SECRET) if CHANNEL_SECRET else None
configuration = Configuration(access_token=CHANNEL_TOKEN) if CHANNEL_TOKEN else None


def _api() -> MessagingApi:
    if not configuration:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN が未設定です")
    return MessagingApi(ApiClient(configuration))


def reply_text(reply_token: str, text: str) -> None:
    _api().reply_message(
        ReplyMessageRequest(
            reply_token=reply_token,
            messages=[TextMessage(text=text)],
        )
    )


def push_text(user_id: str, text: str) -> None:
    _api().push_message(
        PushMessageRequest(
            to=user_id,
            messages=[TextMessage(text=text)],
        )
    )


def broadcast_text(text: str) -> None:
    _api().broadcast(BroadcastRequest(messages=[TextMessage(text=text)]))


def fetch_follower_ids() -> list[str] | None:
    """友だち ID 一覧。認証済み/プレミアム以外では API が 403 なので None。"""
    if not configuration:
        logger.info("LINEトークン未設定のためフォロワーID取得をスキップ")
        return None
    try:
        api = _api()
        found: list[str] = []
        start: str | None = None
        seen: set[str] = set()
        for _ in range(50):
            if start:
                if start in seen:
                    break
                seen.add(start)
            page = api.get_followers(start=start, limit=1000)
            found.extend(page.user_ids or [])
            start = page.next
            if not start:
                break
        return found
    except ApiException as exc:
        # 標準の Messaging API チャネルは verified/premium 限定のため 403 になる。
        logger.info("フォロワーID APIは利用不可 status=%s", exc.status)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("フォロワーID取得に失敗: %s", type(exc).__name__)
        return None


def send_weekday_reminders() -> dict:
    now = datetime.now(TZ)
    if now.weekday() >= 5:
        logger.info("週末のためリマインドをスキップ")
        return {"ok": True, "skipped": "weekend", "users": len(storage.all_user_ids())}

    text = messages.reminder_text()
    followers = fetch_follower_ids()
    if followers is not None:
        storage.remember_users(followers)

    users = storage.all_user_ids()
    if users:
        sent = 0
        logger.info("リマインド送信開始: %s人", len(users))
        for uid in users:
            try:
                push_text(uid, text)
                sent += 1
            except Exception:
                logger.exception("push失敗: %s", uid)
        return {"ok": True, "mode": "push", "users": len(users), "sent": sent}

    if followers is not None:
        logger.info("送信先の友だちがいないためリマインドをスキップ")
        return {"ok": True, "mode": "none", "users": 0}

    try:
        broadcast_text(text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ブロードキャスト失敗: %s", type(exc).__name__)
        return {"ok": False, "mode": "broadcast_failed", "users": 0}
    logger.info("登録が空のためブロードキャストでリマインド")
    return {"ok": True, "mode": "broadcast", "users": 0}


@app.get("/")
def health():
    info = storage.status()
    body = {
        "name": "べんきょうサボらんBot",
        "ok": True,
        "users": info["users"],
        "durable": info["enabled"],
        "now": datetime.now(TZ).isoformat(),
    }
    if info["error"]:
        body["storage_error"] = info["error"]
    return body


@app.post("/cron/remind")
def cron_remind():
    """無料クラウド向け: 外部cronから平日16:30に叩く。"""
    secret = request.headers.get("X-Cron-Secret") or request.args.get("secret", "")
    if not CRON_SECRET or secret != CRON_SECRET:
        abort(401)
    result = send_weekday_reminders()
    return {
        "ok": bool(result.get("ok", True)),
        "users": result.get("users", 0),
        "mode": result.get("mode") or result.get("skipped"),
    }


@app.post("/callback")
def callback():
    if not handler:
        abort(500, "LINE_CHANNEL_SECRET が未設定です")
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400, "Invalid signature")
    return "OK"


if handler:

    @handler.add(FollowEvent)
    def on_follow(event: FollowEvent):
        uid = event.source.user_id
        storage.ensure_user(uid)
        reply_text(
            event.reply_token,
            "友だち追加ありがとう！ ぼくは「べんきょうサボらんBot」。\n"
            "平日16:30に勉強の声かけをするよ。\n"
            "終わったら「やった」と送ってね。\n\n" + messages.HELP,
        )

    @handler.add(MessageEvent, message=TextMessageContent)
    def on_text(event: MessageEvent):
        uid = event.source.user_id
        storage.ensure_user(uid)
        text = (event.message.text or "").strip()
        lower = text.lower()

        if text in ("やった", "できた", "終わり", "完了") or lower in ("done", "yatta"):
            streak = storage.mark_done(uid)
            reply_text(event.reply_token, messages.done_text(streak))
            return

        if text in ("連続", "ストリーク", "記録") or lower == "streak":
            streak, last = storage.get_streak(uid)
            reply_text(event.reply_token, messages.streak_text(streak, last))
            return

        if text in ("ヘルプ", "使い方", "help", "Help"):
            reply_text(event.reply_token, messages.HELP)
            return

        reply_text(
            event.reply_token,
            "なるほど！ 勉強が終わったら「やった」と送ってね。\n"
            "使い方は「ヘルプ」だよ。",
        )


def start_scheduler() -> None:
    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(
        send_weekday_reminders,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=TZ),
        id="weekday_reminder",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("スケジューラ起動: 平日 16:30 Asia/Tokyo")


# gunicorn 起動時も内部スケジューラを任意で有効化（無料クラウドでは外部cron推奨）
if ENABLE_INTERNAL_SCHEDULER:
    start_scheduler()

if __name__ == "__main__":
    if not CHANNEL_SECRET or not CHANNEL_TOKEN:
        logger.warning(".env の LINE_CHANNEL_SECRET / LINE_CHANNEL_ACCESS_TOKEN を設定してください")
    if not ENABLE_INTERNAL_SCHEDULER:
        start_scheduler()
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
