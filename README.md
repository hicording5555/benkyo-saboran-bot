# べんきょうサボらんBot

平日 16:30（Asia/Tokyo）に LINE で勉強の声かけをする、無料の簡易ボットです。

## できること（MVP）

- 友だち追加後、平日 16:30 にリマインド送信
- 「やった」と送ると完了記録＋連続日数
- 「連続」「ヘルプ」コマンド

## 必要なもの（すべて無料枠で可）

1. [LINE Developers](https://developers.line.biz/) アカウント
2. Messaging API チャネル
3. 公開 URL（例: [Render](https://render.com/) 無料枠、または手元起動＋ [ngrok](https://ngrok.com/)）

## セットアップ手順

### 1. LINE チャネル作成

1. LINE Developers でプロバイダー作成
2. Messaging API チャネルを作成
3. **Channel secret** と **Channel access token（長期）** を控える
4. LINE公式アカウント設定で「あいさつメッセージ」はオフ推奨（Bot側で送るため）

### 2. このプロジェクトの準備

```bash
cd benkyo-saboran-bot
python -m venv .venv
# Windows
.venv\Scripts\activate
# Mac/Linux
# source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env   # Mac/Linux は cp .env.example .env
```

`.env` に secret と token を入れる。

### 3. ローカル起動＋ngrok

```bash
python app.py
```

別ターミナルで:

```bash
ngrok http 8000
```

出てきた `https://xxxx.ngrok-free.app/callback` を LINE の Webhook URL に設定し、Webhook を有効化。検証ボタンで成功することを確認。

### 4. 動作確認

1. チャネルの QR から友だち追加
2. 「ヘルプ」と送る
3. 「やった」と送って連続日数が増えるか確認
4. リマインドの手動テスト（任意）:

```python
from app import send_weekday_reminders
send_weekday_reminders()
```

## メッセージ例

- リマインド: 勉強クエストの開始合図（少しユーモアあり）
- 完了: 連続日数つきのねぎらい

## 仕様メモ

詳細は `spec.json` を参照。

## 次に足せること

- 保護者への週次まとめ
- 教科別リマインド
- 「やった」クイック返信ボタン（Flex Message）
