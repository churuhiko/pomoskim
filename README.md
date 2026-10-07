# Pomo Skin

Windows 11向けの軽量な常駐型ポモドーロタイマーです。作業画面の隅に置き、集中時間と休憩時間をシンプルに管理できます。

現在のデスクトップ版: **v0.3.0-preview.4**

公開リポジトリ: [github.com/churuhiko/pomoskim](https://github.com/churuhiko/pomoskim)

## 主な機能

- `Work 25m`／`Break 5m`タイマー
- 作業と休憩の自動切り替え
- Start／Stop／Reset
- 最前面表示、最小化、タスクトレイ収納、ドラッグ移動、表示倍率変更
- Windows 11標準トースト通知と通知音
- 低彩度の背景色プリセット
- スクロール式スキン選択画面と公式スキン
- 当日・当月・当年の実績集計
- Googleカレンダーへの一方向の月報・年報記録
- 終了時のGitHub最新版確認と公式ダウンロードページへの案内
- 初回操作チュートリアルとアプリ内ヘルプ
- 専用アプリアイコン

## 対応環境

- Windows 11
- Python 3.12以降（ソースから実行する場合）

## ソースから実行

```powershell
python -m pip install -r requirements.txt
python main.py
```

`run_pomodoro.bat`からも起動できます。

## 基本操作

1. `Work 25m`または`Break 5m`を選択します。
2. `Start`で開始、`Stop`で一時停止、`Reset`で初期時間へ戻します。
3. 歯車ボタンから通知、表示、実績、Googleカレンダー連携、ヘルプを設定できます。
4. `−`で最小化、設定でタスクトレイ収納を有効にするとトレイへ格納できます。`×`から完全終了できます。

使い方の詳細は[オンライン説明書](docs/manual.html)を参照してください。

## Googleカレンダー連携

Pomo SkinからGoogleカレンダーへ新規の終日予定を書き込む一方向連携です。既存予定の読取・検索・更新・重複判定は行いません。通信結果が不明な再送では予定が重複する場合があります。

OAuthクライアント情報とトークンはローカル専用です。`local_credentials/`、`google_calendar_token.json`、`credentials*.json`などをGitへ追加しないでください。

## データとプライバシー

- 設定と実績は利用者のPC内へ保存されます。
- 日次の詳細履歴は保存しません。
- Googleカレンダー連携を有効にした場合だけGoogle Calendar APIへ実績を送信します。
- アプリからカレンダー予定を読み取りません。

詳細は[プライバシー説明](docs/privacy.html)を参照してください。

## 開発

```powershell
python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm PomodoroOverlay.spec
```

生成物、ローカル設定、認証情報、引き継ぎ資料は`.gitignore`で公開対象から除外します。

## GitHub公開とRelease

`main`へpushするとGitHub Actionsでテストが実行されます。`v`から始まるタグ（例: `v0.3.0-preview.2`）をpushすると、Windows向けにビルドした`PomoSkin.exe`をGitHub Releaseへ添付します。GitHub Pagesは`docs/`を公開し、トップページのダウンロードボタンは最新版Releaseへリンクします。

配布EXEはWindowsのコード署名証明書を設定したReleaseで署名できます。署名を利用する場合は、リポジトリSecretsに`WINDOWS_SIGNING_CERTIFICATE_BASE64`（PFXをBase64化した値）と`WINDOWS_SIGNING_CERTIFICATE_PASSWORD`を登録します。各Releaseには署名の有無にかかわらずSHA-256チェックサムも添付します。

## 連絡先・開発支援

- 開発者: BOUYA
- X: [@xbouyax](https://x.com/xbouyax)
- 開発支援: [OFUSE](https://ofuse.me/df740631)

## Issue管理

不具合報告と機能提案は、GitHub Issuesを正本として管理します。アプリ本体には`issue`フォルダを同梱せず、ローカルの一覧とGitHub Issuesを二重管理しません。

- 不具合はGitHubの「不具合報告」フォームから報告してください。
- 改善案はGitHubの「機能提案」フォームから送ってください。
- フォーム設定は[.github/ISSUE_TEMPLATE](.github/ISSUE_TEMPLATE)で管理しています。
- OAuth認証情報、アクセストークン、個人情報をIssueへ記載・添付しないでください。

オフラインで共有すべき既知問題が発生した場合のみ、`docs/known-issues.md`を追加します。その場合も対応状況の正本はGitHub Issuesとします。

## ライセンス

Copyright © 2026 BOUYA. All rights reserved.

本リポジトリの公開は、ソースコード、イラスト、アイコンその他の素材について、再配布・改変・商用利用を許諾するものではありません。詳細は[LICENSE](LICENSE)を確認してください。
