"""少しユーモアありの声かけ文面（強め）。"""

from datetime import date
import random

REMINDERS = [
    "緊急速報：机のノートがストライキを検討中。勉強タイム開始で交渉成立だ！",
    "サボり怪獣が近づいてきた…！ 16:30の必殺技は「勉強スタート」。今だ！",
    "今日のメインクエストは勉強。報酬は「やった感」と明日の自分からの高評価だよ。",
    "脳みそ「まだ休憩？」／僕「勉強！」／脳みそ「……了解、5分だけね」。よし、始めよう。",
    "勉強スイッチ、どこだっけ？ …あった、ここだ！ ポチッ。さあ机へゴー。",
]

DONE_REPLIES = [
    "クリア！ 連続 {streak} 日。サボり怪獣、今日も撃退完了だぞ。",
    "やったね！ {streak} 日連続。ノートが「ありがとう」って言ってた（たぶん）。",
    "ミッション完了！ 連続 {streak} 日。明日の自分、ニヤニヤしてるはず。",
    "おお、伝説更新！ {streak} 日連続クリア。表彰状は心の中に飾っといて。",
]

HELP = (
    "べんきょうサボらんBotの使い方\n"
    "・平日16:30に勉強リマインドを送るよ\n"
    "・終わったら「やった」と送ってね\n"
    "・「連続」で連続達成日数を確認できるよ\n"
    "・「ヘルプ」でこの案内を再表示"
)


def reminder_text() -> str:
    base = random.choice(REMINDERS)
    return f"{base}\n\n終わったら「やった」と送ってね。"


def done_text(streak: int) -> str:
    return random.choice(DONE_REPLIES).format(streak=streak)


def streak_text(streak: int, last_done: str | None) -> str:
    if streak <= 0:
        return "まだ連続記録はないよ。勉強が終わったら「やった」と送ってスタート！"
    last = f"（最終クリア: {last_done}）" if last_done else ""
    return f"いまの連続達成は {streak} 日だよ！ サボり怪獣撃退数も同数！ {last}".strip()
