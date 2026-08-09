# Changelog

## v0.3.0-preview.1 - 2026-08-09

### Preview

- v0.3プレビューのビルド識別子を追加し、アプリ画面・起動スプラッシュ・スプラッシュキャッシュで共通化
- v0.2.999までのタイマー、実績、Googleカレンダー連携、スキン機能をプレビュー基盤の回帰対象として継続

## v0.2.999 - 2026-07-19

### Fixed

- 起動スプラッシュのイラスト表示中はメインオーバーレイの最前面属性を一時解除し、イラストを最前面へ表示するよう変更
- スキン選択にページ番号 `1 2 3` の直接移動リンクを追加
- Googleカレンダー書き込み失敗通知に、再連携を試す案内を追加
- 起動直後の自動カレンダー同期と手動書き込みが競合し、最新の時間短縮実績が送信されない問題を修正
- 当日の0件日報が未送信キューにあると、その後の時間短縮（ズル）実績だけがカレンダーへ反映されない問題を修正
- 公式スキンに自然系の「フラワー」「ボタニカル」を追加し、スキン選択へ自然系の第3ページを追加
- 公式スキンの自然系に「クローバー」を追加
- 旧開発モードを製品機能「時間短縮モード」として復元し、画面・通知・実績表記を統一。依存関係の直接指定を固定
- ローカル設定JSONに容量上限と型・範囲・列挙値検証を追加し、不正なウィンドウ値・実績キュー・レポート識別子を安全な既定値へ正規化
- Googleカレンダー権限を本人所有イベント用の `calendar.events.owned` へ縮小し、旧スコープのトークンを再認証へ移行
- 時間短縮モードの実績表記を「（ズル）」へ戻し、ズル実績だけのレポートもGoogleカレンダーへ書き込めることを保証
- 実績が0回でも「カレンダーに書き込み」で当日の日報を作成し、不要な「書き込む実績がありません」ダイアログを廃止
- 「カレンダーに書き込み」押下時に同期を開始してGoogleカレンダーを既定ブラウザーで開くよう変更
- スキン選択の適用値を表示倍率ごとに失わないよう、倍率変更後も同じスキンを再適用
- 配布版の未処理例外ダイアログでスタックトレースを表示しないようにし、カレンダー連携失敗ログから生の例外本文を除外
- 表示タブの表示倍率を選択時にメインへ即時反映・保存するライブプレビューへ変更し、ウィンドウ位置とタイマー状態を維持
- 表示タブの背景色を選択時にメインへ即時反映・保存するライブプレビューへ変更し、位置・サイズ・タイマー・スキンを維持
- 設定画面をモデルレス化して表示中もタイマー操作を可能にし、スキン選択のライブプレビューとキャンセル時の復元を追加
- 設定画面を通常ウィンドウとし、外部アプリ起動時の設定画面最小化とGoogle認証後の自動復元を追加。一般タブの「常に最前面に表示」は維持
- 「カレンダーに書き込み」を実績タブへ移し、連携タブには連携時のみ有効な「Googleカレンダーに飛ぶ」を追加
- 未連携時の「Googleカレンダーに飛ぶ」を灰色背景・黒文字の無効ボタンとして明示
- スキン選択をカラー系／ダーク系の2ページに分け、共通の「スキンなし」と無効状態を判別できるページ送りリンクを追加
- スキンカード全体を選択可能にし、ページ送りを適用・キャンセル操作の直上へ移動
- クリック可能なスキンカードで白背景・枠線・角丸が消える表示不具合を修正
- `WA_DeleteOnClose`で削除済みのSplashWindowを終了処理で再参照し、`Internal C++ object already deleted`が発生する問題を修正。
- GUIテスト終了時に非表示のトップレベルQtウィジェットが残存し、python.exe終了時にアクセス違反(0xC0000005)が発生する問題を修正。

- 終了処理を統一し、タイマー、カレンダー同期、スプラッシュ更新、Windows通知、イベントフィルター、単一起動ソケットをQt終了前に停止・解放
- `app.exec()` 終了後にウィンドウの遅延削除イベントを明示処理し、Qtオブジェクトの破棄順序を安定化
- 通常ボタン色をさらに白方向へ10%調整
- GUIテストでは実物のWindows通知サービスを初期化せず、テスト終了時のネイティブ解放エラーを防止
- 通常ボタン色を白方向へ5%調整し、暗色スキン上の視認性を改善
- 通常ボタン色を黒方向へ約2/6暗くし、選択中のWork／Breakとの判別性を強化
- 通常ボタンの明度をダーク系スキン上でも沈みすぎない範囲で下げ、選択中ボタンとの視覚差を拡大
- 通常ボタンを一段濃くし、選択中のWork／Breakを通常色よりわずかに明るく調整
- 終了時にアプリケーションイベントフィルターを明示解除し、Pythonプロセス終了時のネイティブエラーを防止
- 背景色テーマごとの濃色ボタン配色を追加し、Work／Breakの選択中は通常色よりわずかに明るく表示
- スキン使用中も専用配色を設けず、選択した背景色テーマの配色を維持
- 「ポップ迷彩1」の表示名を「ポップ迷彩」に変更
- 公式スキンに「カーボン」「ギャラクシー」「ヘアライン」「ポップタイル」「武田菱」を追加
- 日付変更時の日報、月初の月報、年始の年報を未送信キュー経由でGoogleカレンダーへ記録
- 日報は短時間通知、月報はアプリ操作まで保持する通知として表示
- 年始は月報通知の終了後に年報ダイアログとHappy New Year通知を順番に表示
- 送信失敗時はタイマーを止めず、未送信データを保持して後から再試行
- v0.3-alpha リリース直前版として記録
- 公式スキン選択と背景色変更を表示設定へ統合
- 起動スプラッシュ、操作チュートリアル、ヘルプ機能を整備
- チュートリアルの文字を拡大し、主要な操作名を太字化
- GitHub 公開準備用のドキュメントとワークフローを追加

## v0.2.5 - 2026-07-18

- Enlarged tutorial text to a rounded-up 120%, bolded application/control names, and documented background colors and official skins on page 4
- Added a Display-tab splash-artwork viewer with a dimmed backdrop, text × close control, and outside-click dismissal
- Moved `スキンなし（背景色を使用）` to the top of the skin picker
- Expanded the Display-tab Skin button to the full row, removed the adjacent skin-name text, and made the selected skin marker red
- Fixed the no-skin background becoming transparent and added rounded preset-colored title/timer surfaces above active skins
- Added the first selectable skin, `ポップ迷彩`, with a scrollable thumbnail-left/name-right skin picker in the Display tab
- Added GitHub publication files, issue/PR templates, Windows CI, GitHub Pages documentation, privacy notes, and an All Rights Reserved license
- Shortened the startup splash from 1.5 seconds to 1 second and removed the redundant bold tutorial heading from Help
- Renamed the Help contact action to `開発者連絡先` and restored white text contrast in the dark full-exit dialog
- Fixed tutorial contrast with explicit light content colors and white text on dark buttons
- Added a first-run-only Skip button that suppresses future automatic tutorial display
- Added a four-page first-run operation tutorial after the splash, with Back/Next/Finish navigation and Help-tab replay
- Added an OFUSE development-support link (`https://ofuse.me/df740631`) to Help
- Added a Help tab with an in-app operation tutorial, creator contact, and development-support guidance
- Adjusted the startup splash duration from 2 seconds to 1.5 seconds
- Added the finished Pomodoro Overlay icon to the executable, taskbar, and application windows
- Moved the title/credit above the illustration and the version below it so artwork can never hide the text
- Fixed splash typography to opaque cream text with a black outline and a solid black version label
- Removed explicit translucent-widget processing while keeping text and illustration structurally separate
- Extended the splash to 2 seconds and sized it to 70% of the active monitor's usable short edge
- Overlaid the title at the illustration top and the version at the bottom on a transparent text layer
- Expanded the square illustration to the full splash area and made the overlaid text layer transparent
- Extended the startup splash from 0.5 seconds to 1 second for comfortable recognition
- Made bundled splash preparation version- and content-specific for future upgrades
- Show the optimization dialog once after each version upgrade or bundled-art replacement
- Keep later launches fast by reusing the verified per-version cache
- Added a first-launch `最適化中 このままお待ちください` preparation dialog and a 0.5-second post-preparation splash
- Split illustration and application text into independent UI layers to keep all version/title/credit text out of the bitmap
- Added a centered, non-blocking startup splash with UI-rendered version, title, and `by BOUYA` credit
- Added optional bundled and cached illustration loading without modifying the source artwork
- Added a delayed background updater for future GitHub-hosted splash assets
- Added HTTPS-only downloads, daily throttling, timeout, cancellation, size/hash/dimension/format checks, and atomic cache replacement
- Kept the existing cache on every update failure and activate downloaded artwork only on the next launch
- Left the illustration and remote manifest URL optional until the publishing workflow is ready

## v0.2.4 - 2026-07-18

- Replaced daily Calendar events with separate monthly and yearly aggregate reports
- Added local today/current-month/current-year counters without retaining daily history
- Added durable pending monthly/yearly report queues and oldest-first retry
- Reset old aggregates and pending reports after one year of inactivity
- Migrated same-day legacy counters while intentionally discarding legacy daily queues that cannot be aggregated exactly
- Added hidden same-day `（ズル）` Work/Break counters revealed only after a development-mode completion and reset at date rollover
- Kept development-mode counts separate from normal statistics and added separate cheat-count lines to Calendar records
- Restored and foregrounded the minimized app when a Work/Break completion notification is clicked
- Kept notification-click dismissal and Start-triggered dismissal of the preceding timer notification
- Embedded the developer-provided desktop OAuth configuration at build time and removed the end-user JSON picker
- Confirmed Google Calendar OAuth operation with a configured test user
- Added manual current-day calendar writing and opened Google Calendar after a manual write request
- Changed calendar event title to `ポモドーロ実績` and description to completed/break counts
- Added success and persistent failure Windows notifications for manual calendar writes
- Added confirmation before disconnecting Google Calendar
- Moved the development-mode checkbox to the bottom of General settings
- Removed the ineffective timer-notification close-button action; notifications remain clickable to dismiss
- Starting the next timer dismisses the preceding Work/Break completion notification
- Kept Work and Break selection buttons synchronized with the active timer mode
- Fixed calendar message-box contrast before replacing manual-write result dialogs with Windows notifications
- Added automatic tests for the new calendar, notification, and mode-selection behavior

## v0.2.3 - 2026-07-18

- Added an isolated, non-persistent development timer checkbox guarded by `ENABLE_DEV_FEATURES`
- Show `開発モード` in the settings title while the short timer is enabled
- Added Windows short-duration toast notifications when development mode is enabled or disabled
- Removed the five-second expiration that could discard a development notification before Windows displayed it
- Added guidance in the Notification tab to check Windows Settings > System > Notifications
- Development mode immediately shows `00:25` or `00:05`
- Fixed the Exit confirmation not closing the application after choosing `終了`
- Fixed the five-day backlog dialog incorrectly containing application-exit commands
- Added read-only lifetime Pomodoro and short-break statistics
- Added daily counters, date rollover, and a durable unsent-record queue
- Added Statistics and Integration settings tabs
- Added optional one-way Google Calendar OAuth connection that only creates all-day events
- Does not read, update, identify, compare, or deduplicate Google Calendar events
- Allows possible duplicate events after an uncertain delivery result and leaves cleanup to the user
- Added oldest-first retry behavior and a one-time warning at five pending days
- Kept timer completion independent from notification and calendar failures

## v0.2.2 - 2026-07-18

- Replaced the custom sliding popup with Windows standard local app notifications
- Added distinct Work-complete and Break-complete notification text
- Added `notification_enabled` and `notification_sound_enabled` settings with defaults of `true`
- Removed direct `winsound` playback and custom notification audio selection
- Notification failures are non-fatal and never block timer completion
- Added `Windows-Toasts 1.3.1` and Python 3.14-compatible WinRT dependencies
- Simplified the notification option label to `タイマー完了通知` with ON as the default
- Added a `通知サウンド` switch; ON uses the Windows default notification sound and OFF sends a silent Windows notification
- Added a Windows notification `閉じる` button so completed-session notices can remain until reviewed
- Added bordered checkbox indicators for clearer settings without color coding
- Preserved the native check mark inside the border when a checkbox is ON
- Changed the settings-window title to show the current app version with a space separator

## v0.2.1 - 2026-07-17

- Added background color selection to Display settings
- Added six low-saturation presets: cream, sage, mist blue, dusty rose, gray, and charcoal
- Automatically matches text, border, and button colors to each background for readability
- Keeps existing v0.2.0 settings compatible
- Fixed the legacy yellow style overriding selected background presets
- Made every non-button overlay label black for consistent readability
- Removed the dark charcoal preset and migrate it to cream
- Fixed invisible unselected tabs in the settings dialog
- Changed the timer toast to slide horizontally from the right edge
- Replaced the toast `×` control with a clearly labeled `閉じる` button

## v0.2.0 - 2026-07-17

Status: Stable operation confirmed on 2026-07-17.

- Changed the overlay from a tool window to a normal taskbar window
- Enabled users to pin PomodoroOverlay to the Windows taskbar
- Removed system-tray storage and kept the v0.2 scope focused on taskbar use
- Replaced the blocking timer-finished dialog with a non-activating bottom-right toast
- Added an in-app minimize button next to the exit button
- Added a close button to the bottom-right timer notification
- Changed the timer sound to the Windows 11 instant-message notification event

## v0.1.1 - 2026-07-16

- Fixed timer text overlap on Windows displays using 175% scaling
- Calculate the timer label from the actual rendered font metrics
- Automatically increase only the minimum window height when required

## v0.1.0 - 2026-07-16

First desktop release.

- Sticky-note Pomodoro overlay for Windows
- 25-minute work and 5-minute break timers
- Start, stop, reset, and mode switching
- Always-on-top and draggable frameless window
- System tray support and complete-exit confirmation
- JSON settings persistence
- Japanese settings and exit dialogs
- Windows system sound or mute option
- UI scale presets from 100% to 150%
- Stable single-instance behavior
- Standalone no-console PyInstaller executable
