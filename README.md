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

## データの保存

友だちと連続日数は起動中の `data/users.json` にキャッシュします。Render の無料 Web サービスはディスクが一時的なので、スリープや再起動のあとファイルは消えます。本体は `USERS_STORE_URL` の非公開 JSON です。更新のたびにそこへ PUT し、ファイルが無い起動では GET して戻します。`USERS_STORE_SECRET` はリクエストの `Security-key` です。どちらも Render の環境変数に置き、リポジトリには書きません。

すでに消えてしまった登録は戻りません。その人に「ヘルプ」など何でも一度送ってもらうと、そこから記録が再開します。登録が空のまま平日のリマインドが走ったときは、友だち ID 一覧 API（認証済みまたはプレミアムのアカウントだけ）が使えない場合に限り、LINE のブロードキャストで友だち全員へ送ります。

## 無料枠を起こしたままにする

Render の無料 Web サービスは、およそ15分アクセスがないとスリープします。起きてから応答するまで20秒ほどかかり、LINE の Webhook はその時間を待たないので、「テスト」や「やった」に返事が返りません。

`.github/workflows/keep-awake.yml` が5分ごとに `https://benkyo-saboran-bot.onrender.com/` へ GET します。待っても最大60秒で、HTTP 200 以外ならジョブは失敗します。すぐ起こしたいときは、GitHub の Actions タブで「Keep Render awake」を手動実行します。この定期実行は `main` に入ってから動きます。追加の料金はかかりません。

## 仕様メモ

詳細は `spec.json` を参照。

## 次に足せること

- 保護者への週次まとめ
- 教科別リマインド
- 「やった」クイック返信ボタン（Flex Message）
