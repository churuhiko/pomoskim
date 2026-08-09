import tempfile
import json
import ctypes
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

import stats_integration
from stats_integration import GoogleCalendarClient, StatisticsManager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)


class StatisticsManagerTests(unittest.TestCase):
    def make_manager(self, saved_date="2026-07-18"):
        settings = {}
        return settings, StatisticsManager(settings, saved_date)

    def test_normal_and_cheat_increment_today_month_and_year_separately(self):
        settings, manager = self.make_manager()
        manager.record_completion("work", "2026-07-18")
        manager.record_completion("break", "2026-07-18")
        manager.record_completion("work", "2026-07-18", cheat=True)
        manager.record_completion("break", "2026-07-18", cheat=True)
        state = settings["stats_state"]
        for bucket in ("today", "current_month", "current_year"):
            self.assertEqual(state[bucket]["pomodoro_completed"], 1)
            self.assertEqual(state[bucket]["short_break_completed"], 1)
            self.assertEqual(state[bucket]["cheat_pomodoro_completed"], 1)
            self.assertEqual(state[bucket]["cheat_short_break_completed"], 1)

    def test_month_rollover_enqueues_total_and_resets_month(self):
        settings, manager = self.make_manager("2026-07-31")
        manager.record_completion("work", "2026-07-31")
        manager.record_completion("break", "2026-07-31", cheat=True)
        self.assertTrue(manager.rollover("2026-08-01"))
        reports = settings["stats_state"]["pending_reports"]
        self.assertEqual(
            [item["report_id"] for item in reports],
            ["daily-2026-07-31", "monthly-2026-07"],
        )
        self.assertEqual(reports[1]["pomodoro_completed"], 1)
        self.assertEqual(reports[1]["cheat_short_break_completed"], 1)
        self.assertEqual(settings["stats_state"]["current_month"]["month"], 8)
        self.assertEqual(settings["stats_state"]["current_month"]["pomodoro_completed"], 0)

    def test_new_year_enqueues_monthly_then_yearly_reports(self):
        settings, manager = self.make_manager("2026-12-31")
        manager.record_completion("work", "2026-12-31")
        self.assertTrue(manager.rollover("2027-01-01"))
        self.assertEqual(
            [item["report_id"] for item in settings["stats_state"]["pending_reports"]],
            ["daily-2026-12-31", "monthly-2026-12", "yearly-2026"],
        )

    def test_day_rollover_enqueues_previous_day_and_resets_today(self):
        settings, manager = self.make_manager("2026-07-18")
        manager.record_completion("work", "2026-07-18")
        manager.record_completion("break", "2026-07-18", cheat=True)
        self.assertTrue(manager.rollover("2026-07-19"))
        report = settings["stats_state"]["pending_reports"][0]
        self.assertEqual(report["report_id"], "daily-2026-07-18")
        self.assertEqual(report["pomodoro_completed"], 1)
        self.assertEqual(report["cheat_short_break_completed"], 1)
        self.assertEqual(settings["stats_state"]["today"]["date"], "2026-07-19")
        self.assertEqual(settings["stats_state"]["today"]["pomodoro_completed"], 0)

    def test_cheat_only_activity_is_enqueued_for_calendar_writing(self):
        settings, manager = self.make_manager("2026-07-18")
        manager.record_completion("work", "2026-07-18", cheat=True)

        self.assertTrue(manager.rollover("2026-07-19"))

        report = settings["stats_state"]["pending_reports"][0]
        self.assertEqual(report["report_id"], "daily-2026-07-18")
        self.assertEqual(report["pomodoro_completed"], 0)
        self.assertEqual(report["short_break_completed"], 0)
        self.assertEqual(report["cheat_pomodoro_completed"], 1)
        self.assertEqual(report["cheat_short_break_completed"], 0)

    def test_manual_daily_report_is_queued_even_when_all_counts_are_zero(self):
        settings, manager = self.make_manager("2026-07-18")

        self.assertTrue(manager.enqueue_current_daily_report("2026-07-18"))

        report = settings["stats_state"]["pending_reports"][0]
        self.assertEqual(report["report_id"], "daily-2026-07-18")
        self.assertTrue(all(report[key] == 0 for key in stats_integration.COUNTER_KEYS))
        self.assertFalse(manager.enqueue_current_daily_report("2026-07-18"))

    def test_manual_daily_report_refreshes_existing_zero_report_with_cheat_only_activity(self):
        settings, manager = self.make_manager("2026-07-18")
        self.assertTrue(manager.enqueue_current_daily_report("2026-07-18"))
        manager.record_completion("work", "2026-07-18", cheat=True)
        manager.record_completion("break", "2026-07-18", cheat=True)

        self.assertTrue(manager.enqueue_current_daily_report("2026-07-18"))

        reports = settings["stats_state"]["pending_reports"]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["pomodoro_completed"], 0)
        self.assertEqual(reports[0]["short_break_completed"], 0)
        self.assertEqual(reports[0]["cheat_pomodoro_completed"], 1)
        self.assertEqual(reports[0]["cheat_short_break_completed"], 1)


    def test_long_inactivity_discards_old_counts_and_pending_reports(self):
        settings, manager = self.make_manager("2025-01-01")
        manager.record_completion("work", "2025-01-01")
        manager.rollover("2025-02-01")
        saved = json.loads(json.dumps(settings))
        restored = StatisticsManager(saved, "2026-02-02")
        self.assertTrue(restored.long_inactivity_reset)
        state = saved["stats_state"]
        self.assertEqual(state["pending_reports"], [])
        self.assertEqual(state["today"]["pomodoro_completed"], 0)
        self.assertEqual(state["current_month"]["year"], 2026)

    def test_regular_use_prevents_false_long_inactivity_reset(self):
        settings, manager = self.make_manager("2025-01-01")
        manager.rollover("2025-08-01")
        restored = StatisticsManager(settings, "2026-01-02")
        self.assertFalse(restored.long_inactivity_reset)

    def test_same_day_state_survives_json_round_trip(self):
        settings, manager = self.make_manager()
        manager.record_completion("work", "2026-07-18", cheat=True)
        restored = json.loads(json.dumps(settings))
        StatisticsManager(restored, "2026-07-18")
        self.assertEqual(restored["stats_state"]["today"]["cheat_pomodoro_completed"], 1)


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, credentials):
        self.credentials = credentials
        self.requests = []

    def get(self, url, **kwargs):
        raise AssertionError("One-way calendar integration must not read events")

    def put(self, url, **kwargs):
        raise AssertionError("One-way calendar integration must not update events")

    def post(self, url, **kwargs):
        self.requests.append(("post", url, kwargs))
        return FakeResponse()


class GoogleCalendarClientTests(unittest.TestCase):
    def test_saved_token_requires_current_owned_events_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "token.json"
            token_path.write_text("{}", encoding="utf-8")
            client = GoogleCalendarClient(token_path)
            credentials = Mock()
            credentials.has_scopes.return_value = False
            with patch.object(
                stats_integration.Credentials,
                "from_authorized_user_file",
                return_value=credentials,
            ):
                self.assertFalse(client.has_credentials())
            credentials.has_scopes.assert_called_with([stats_integration.CALENDAR_SCOPE])

    def test_daily_report_is_posted_as_all_day_event(self):
        sessions = []

        def make_session(credentials):
            session = FakeSession(credentials)
            sessions.append(session)
            return session

        client = GoogleCalendarClient("unused.json")
        client._load_credentials = lambda: object()
        client._save_credentials = lambda credentials: None
        record = {
            "report_id": "daily-2026-07-18",
            "report_type": "daily",
            "period": "2026-07-18",
            "pomodoro_completed": 6,
            "short_break_completed": 5,
            "status": "pending",
        }
        with patch.object(stats_integration, "AuthorizedSession", make_session):
            self.assertTrue(client.send_record(record))
        body = sessions[0].requests[0][2]["json"]
        self.assertEqual(body["summary"], "ポモドーロ実績")
        self.assertEqual(body["start"]["date"], "2026-07-18")
        self.assertEqual(body["end"]["date"], "2026-07-19")

    def test_send_only_posts_new_all_day_event(self):
        sessions = []

        def make_session(credentials):
            session = FakeSession(credentials)
            sessions.append(session)
            return session

        client = GoogleCalendarClient("unused.json")
        client._load_credentials = lambda: object()
        client._save_credentials = lambda credentials: None
        record = {
            "report_id": "monthly-2026-07",
            "report_type": "monthly",
            "period": "2026-07",
            "pomodoro_completed": 6,
            "short_break_completed": 5,
            "status": "pending",
        }
        with patch.object(stats_integration, "AuthorizedSession", make_session):
            self.assertTrue(client.send_record(record))
        request_methods = [item[0] for item in sessions[0].requests]
        self.assertEqual(request_methods, ["post"])
        body = sessions[0].requests[0][2]["json"]
        self.assertEqual(body["summary"], "2026年7月 実績")
        self.assertEqual(body["start"]["date"], "2026-07-31")
        self.assertEqual(body["end"]["date"], "2026-08-01")
        self.assertNotIn("extendedProperties", body)
        self.assertEqual(
            body["description"], "ポモドーロ完了数：6回\n小休憩完了数：5回"
        )

    def test_send_record_adds_cheat_counts_only_when_present(self):
        sessions = []

        def make_session(credentials):
            session = FakeSession(credentials)
            sessions.append(session)
            return session

        client = GoogleCalendarClient("unused.json")
        client._load_credentials = lambda: object()
        client._save_credentials = lambda credentials: None
        record = {
            "report_id": "yearly-2026",
            "report_type": "yearly",
            "period": "2026",
            "pomodoro_completed": 2,
            "short_break_completed": 1,
            "cheat_pomodoro_completed": 3,
            "cheat_short_break_completed": 4,
            "status": "pending",
        }
        with patch.object(stats_integration, "AuthorizedSession", make_session):
            self.assertTrue(client.send_record(record))
        self.assertEqual(
            sessions[0].requests[0][2]["json"]["description"],
            "ポモドーロ完了数：2回\n小休憩完了数：1回\n"
            "ポモドーロ完了数（ズル）：3回\n小休憩完了数（ズル）：4回",
        )
        self.assertEqual(sessions[0].requests[0][2]["json"]["summary"], "2026年 年間実績")

    def test_send_record_posts_cheat_only_report(self):
        sessions = []

        def make_session(credentials):
            session = FakeSession(credentials)
            sessions.append(session)
            return session

        client = GoogleCalendarClient("unused.json")
        client._load_credentials = lambda: object()
        client._save_credentials = lambda credentials: None
        record = {
            "report_id": "daily-2026-07-18",
            "report_type": "daily",
            "period": "2026-07-18",
            "pomodoro_completed": 0,
            "short_break_completed": 0,
            "cheat_pomodoro_completed": 1,
            "cheat_short_break_completed": 0,
            "status": "pending",
        }
        with patch.object(stats_integration, "AuthorizedSession", make_session):
            self.assertTrue(client.send_record(record))
        self.assertEqual(
            sessions[0].requests[0][2]["json"]["description"],
            "ポモドーロ完了数：0回\n小休憩完了数：0回\n"
            "ポモドーロ完了数（ズル）：1回\n小休憩完了数（ズル）：0回",
        )


class OverlayCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        from PySide6.QtWidgets import QApplication

        cls.windows_toaster_patcher = patch.object(main, "WindowsToaster", None)
        cls.windows_toaster_patcher.start()
        cls.app = QApplication.instance() or QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls.windows_toaster_patcher.stop()
        from PySide6.QtCore import QCoreApplication, QEvent

        for widget in cls.app.topLevelWidgets():
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        cls.app.processEvents()
        cls.app.quit()

    def make_manager(self, saved_date="2026-07-18"):
        settings = {
            "daily_record": {
                "date": saved_date,
                "pomodoro_completed": 0,
                "short_break_completed": 0,
            }
        }
        return settings, StatisticsManager(settings, saved_date)

    def test_timer_completion_counts_once_and_persists_before_notification(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.settings["notification_enabled"] = False
                window.current_mode = "work"
                window.remaining_seconds = 0
                settings_identity = id(window.settings)
                window.tick()
                self.assertEqual(
                    window.settings["stats_state"]["today"]["pomodoro_completed"], 1
                )
                self.assertEqual(
                    window.settings["stats_state"]["today"]["cheat_pomodoro_completed"], 0
                )
                self.assertEqual(id(window.statistics.settings), settings_identity)
                self.assertEqual(id(window.settings), settings_identity)
                window.tick()
                self.assertEqual(
                    window.settings["stats_state"]["today"]["pomodoro_completed"], 1
                )
                self.assertEqual(
                    window.settings["stats_state"]["today"]["cheat_pomodoro_completed"], 0
                )
                self.assertTrue(path.exists())
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()
                self.assertFalse(window._application_event_filter_installed)

    def test_settings_dialog_has_statistics_and_integration_tabs(self):
        import main
        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtWidgets import (
            QDialog,
            QLabel,
            QPushButton,
            QSizePolicy,
            QTabWidget,
            QCheckBox,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                captured = []
                notification_guidance = []
                all_labels = []
                all_buttons = []
                skin_button_policies = []
                statistics_buttons = []
                integration_buttons = []
                open_calendar_enabled = []
                open_calendar_disabled_style = []
                settings_topmost = []
                general_checkboxes = []

                def inspect_dialog():
                    dialog = next(
                        item
                        for item in self.app.topLevelWidgets()
                        if isinstance(item, QDialog) and item.isVisible()
                    )
                    tabs = dialog.findChild(QTabWidget)
                    settings_topmost.append(
                        bool(dialog.windowFlags() & Qt.WindowStaysOnTopHint)
                    )
                    general_checkboxes.extend(
                        checkbox.text()
                        for checkbox in tabs.widget(0).findChildren(QCheckBox)
                    )
                    captured.extend(tabs.tabText(index) for index in range(tabs.count()))
                    all_labels.extend(label.text() for label in dialog.findChildren(QLabel))
                    all_buttons.extend(
                        button.text() for button in dialog.findChildren(QPushButton)
                    )
                    statistics_buttons.extend(
                        button.text()
                        for button in tabs.widget(3).findChildren(QPushButton)
                    )
                    integration_buttons.extend(
                        button.text()
                        for button in tabs.widget(4).findChildren(QPushButton)
                    )
                    open_calendar_enabled.append(
                        dialog.findChild(
                            QPushButton, "openGoogleCalendarButton"
                        ).isEnabled()
                    )
                    open_calendar_disabled_style.append(
                        "QPushButton#openGoogleCalendarButton:disabled"
                        in dialog.styleSheet()
                        and "background: #c8c8c8" in dialog.styleSheet()
                        and "color: #202020" in dialog.styleSheet()
                    )
                    skin_button = dialog.findChild(QPushButton, "displaySkinButton")
                    skin_button_policies.append(
                        skin_button.sizePolicy().horizontalPolicy()
                    )
                    notification_guidance.extend(
                        label.text()
                        for label in dialog.findChildren(QLabel)
                        if "設定 → システム → 通知" in label.text()
                    )
                    dialog.reject()

                window.open_settings_dialog()
                self.app.processEvents()
                inspect_dialog()
                self.app.processEvents()
                self.assertEqual(
                    captured,
                    ["一般", "通知", "表示", "実績", "連携", "ヘルプ"],
                )
                self.assertEqual(len(notification_guidance), 1)
                self.assertFalse(any("（ズル）" in text for text in all_labels))
                self.assertFalse(any(text == "操作チュートリアル" for text in all_labels))
                self.assertTrue(any("4ページチュートリアル" in text for text in all_labels))
                self.assertTrue(any("X: @xbouyax" in text for text in all_labels))
                self.assertTrue(any("開発支援" in text for text in all_labels))
                self.assertIn("操作チュートリアルを開く", all_buttons)
                self.assertIn("スキン", all_buttons)
                self.assertIn("起動スプラッシュのイラストを見る", all_buttons)
                self.assertIn("カレンダーに書き込み", statistics_buttons)
                self.assertNotIn("カレンダーに書き込み", integration_buttons)
                self.assertIn("Googleカレンダーに飛ぶ", integration_buttons)
                self.assertNotIn("Googleカレンダーに飛ぶ", statistics_buttons)
                self.assertEqual(open_calendar_enabled, [False])
                self.assertEqual(open_calendar_disabled_style, [True])
                self.assertEqual(settings_topmost, [False])
                self.assertTrue(window.windowFlags() & Qt.WindowStaysOnTopHint)
                self.assertIn("常に最前面に表示", general_checkboxes)
                self.assertEqual(
                    skin_button_policies,
                    [QSizePolicy.Policy.Expanding],
                )
                self.assertNotIn("ポップ迷彩", all_labels)
                self.assertIn("開発者連絡先", all_buttons)
                self.assertNotIn("Xで連絡先を開く", all_buttons)
                self.assertIn("OFUSEで開発を支援", all_buttons)
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_settings_dialog_is_modeless_and_does_not_block_timer_controls(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                dialog = window.open_settings_dialog()
                self.app.processEvents()

                self.assertTrue(dialog.isVisible())
                self.assertIs(window.open_settings_dialog(), dialog)
                window.start_button.click()
                self.assertTrue(window.timer.isActive())
                self.assertTrue(dialog.isVisible())
                window.stop_timer()
                dialog.reject()
                self.app.processEvents()
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_skin_selection_applies_across_display_scales_and_cancel_restores_original_skin(self):
        import main
        from PySide6.QtWidgets import QComboBox, QDialog, QPushButton

        class AcceptedCarbonSkinDialog:
            def __init__(self, current_skin, parent=None):
                self.selected_skin = "carbon"

            def exec(self):
                return QDialog.Accepted

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with (
                patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path),
                patch.object(main, "SkinSelectionDialog", AcceptedCarbonSkinDialog),
            ):
                window = main.PomodoroOverlay()
                self.assertFalse(window.container.has_skin())
                dialog = window.open_settings_dialog()
                self.app.processEvents()

                dialog.findChild(QPushButton, "displaySkinButton").click()
                self.assertTrue(window.container.has_skin())
                self.assertEqual(window.settings["skin"], "carbon")

                scale_choice = dialog.findChild(QComboBox, "displayScaleChoice")
                scale_choice.setCurrentIndex(scale_choice.findData(130))
                self.app.processEvents()
                self.assertTrue(window.container.has_skin())
                self.assertEqual(window.settings["skin"], "carbon")

                dialog.reject()
                self.app.processEvents()
                self.assertFalse(window.container.has_skin())
                self.assertEqual(window.settings["skin"], "none")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["skin"], "none")
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_background_selection_applies_and_saves_live_without_geometry_changes(self):
        import main
        from PySide6.QtWidgets import QComboBox, QTabWidget

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.setGeometry(140, 160, window.width(), window.height())
                original_geometry = window.geometry()
                original_mode = window.current_mode
                original_remaining = window.remaining_seconds
                original_skin = window.settings["skin"]
                dialog = window.open_settings_dialog()
                self.app.processEvents()
                tabs = dialog.findChild(QTabWidget)
                tabs.setCurrentIndex(2)
                background_choice = dialog.findChild(
                    QComboBox, "backgroundPresetChoice"
                )

                background_choice.setCurrentIndex(
                    background_choice.findData("sage")
                )
                self.app.processEvents()

                self.assertEqual(window.settings["background_preset"], "sage")
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8"))["background_preset"],
                    "sage",
                )
                self.assertIn(
                    main.BACKGROUND_PRESETS["sage"]["background"],
                    window.styleSheet(),
                )
                self.assertEqual(window.geometry(), original_geometry)
                self.assertEqual(window.current_mode, original_mode)
                self.assertEqual(window.remaining_seconds, original_remaining)
                self.assertEqual(window.settings["skin"], original_skin)
                self.assertTrue(dialog.isVisible())
                self.assertEqual(tabs.currentIndex(), 2)

                dialog.reject()
                self.app.processEvents()
                self.assertEqual(window.settings["background_preset"], "sage")
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_display_scale_applies_and_saves_live_while_preserving_position(self):
        import main
        from PySide6.QtWidgets import QComboBox

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.move(170, 190)
                original_position = window.pos()
                original_size = window.size()
                original_mode = window.current_mode
                original_remaining = window.remaining_seconds
                dialog = window.open_settings_dialog()
                self.app.processEvents()
                scale_choice = dialog.findChild(QComboBox, "displayScaleChoice")

                scale_choice.setCurrentIndex(scale_choice.findData(130))
                self.app.processEvents()

                self.assertEqual(window.settings["display_scale"], 130)
                self.assertEqual(
                    json.loads(path.read_text(encoding="utf-8"))["display_scale"],
                    130,
                )
                self.assertEqual(window.pos(), original_position)
                self.assertNotEqual(window.size(), original_size)
                self.assertEqual(window.current_mode, original_mode)
                self.assertEqual(window.remaining_seconds, original_remaining)
                self.assertTrue(dialog.isVisible())

                dialog.reject()
                self.app.processEvents()
                self.assertEqual(window.settings["display_scale"], 130)
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_skin_picker_is_scrollable_with_thumbnail_left_and_name_right(self):
        import main
        from PySide6.QtWidgets import QLabel, QRadioButton, QScrollArea

        dialog = main.SkinSelectionDialog("none")
        scroll = dialog.findChild(QScrollArea, "skinScrollArea")
        thumbnail = dialog.findChild(QLabel, "skinThumbnail_pop_camouflage_1")
        choice = dialog.findChild(QRadioButton, "skinChoice_pop_camouflage_1")
        self.assertIsNotNone(scroll)
        self.assertTrue(scroll.widgetResizable())
        self.assertIsNotNone(thumbnail)
        self.assertFalse(thumbnail.pixmap().isNull())
        self.assertEqual(
            dialog.skin_buttons.buttons()[0].objectName(),
            "skinChoice_none",
        )
        self.assertEqual(choice.text(), "ポップ迷彩")
        self.assertIn("#e53935", dialog.styleSheet())
        choice.setChecked(True)
        self.assertEqual(dialog.selected_skin, "pop_camouflage_1")
        dialog.close()

    def test_skin_picker_groups_skins_into_color_dark_and_nature_pages(self):
        import main
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel, QRadioButton

        dialog = main.SkinSelectionDialog("none")
        dialog.show()
        self.app.processEvents()
        no_skin = dialog.findChild(QRadioButton, "skinChoice_none")

        self.assertEqual(dialog.windowTitle(), "スキン選択/カラー系")
        self.assertEqual(dialog.page_stack.count(), 3)
        self.assertTrue(no_skin.isVisible())
        self.assertFalse(dialog.previous_page_link.is_link_enabled())
        self.assertTrue(dialog.next_page_link.is_link_enabled())
        self.assertEqual([link.text() for link in dialog.page_jump_links], ["1", "2", "3"])
        self.assertFalse(dialog.page_jump_links[0].is_link_enabled())
        self.assertTrue(dialog.page_jump_links[1].is_link_enabled())
        self.assertTrue(dialog.page_jump_links[2].is_link_enabled())
        self.assertEqual(
            {button.objectName() for button in dialog.skin_buttons.buttons()[1:4]},
            {
                "skinChoice_pop_camouflage_1",
                "skinChoice_pop_tile",
                "skinChoice_takeda_bishi",
            },
        )

        QTest.mouseClick(dialog.previous_page_link, Qt.LeftButton)
        self.assertEqual(dialog.page_stack.currentIndex(), 0)
        QTest.mouseClick(dialog.next_page_link, Qt.LeftButton)
        self.app.processEvents()

        self.assertEqual(dialog.windowTitle(), "スキン選択/ダーク系")
        self.assertTrue(no_skin.isVisible())
        self.assertTrue(dialog.previous_page_link.is_link_enabled())
        self.assertTrue(dialog.next_page_link.is_link_enabled())
        self.assertTrue(dialog.page_jump_links[0].is_link_enabled())
        self.assertFalse(dialog.page_jump_links[1].is_link_enabled())
        self.assertTrue(dialog.page_jump_links[2].is_link_enabled())
        self.assertEqual(
            {button.objectName() for button in dialog.skin_buttons.buttons()[4:]},
            {
                "skinChoice_carbon",
                "skinChoice_galaxy_1",
                "skinChoice_hairline",
                "skinChoice_flower",
                "skinChoice_botanical",
                "skinChoice_clover",
            },
        )
        QTest.mouseClick(dialog.next_page_link, Qt.LeftButton)
        self.assertEqual(dialog.page_stack.currentIndex(), 2)
        self.assertEqual(dialog.windowTitle(), "スキン選択/自然系")
        self.assertTrue(dialog.previous_page_link.is_link_enabled())
        self.assertFalse(dialog.next_page_link.is_link_enabled())
        self.assertTrue(dialog.page_jump_links[0].is_link_enabled())
        self.assertTrue(dialog.page_jump_links[1].is_link_enabled())
        self.assertFalse(dialog.page_jump_links[2].is_link_enabled())
        self.assertEqual(
            {
                button.objectName()
                for button in dialog.findChild(main.QWidget, "skinPage_3").findChildren(QRadioButton)
            },
            {"skinChoice_flower", "skinChoice_botanical", "skinChoice_clover"},
        )
        QTest.mouseClick(dialog.next_page_link, Qt.LeftButton)
        self.assertEqual(dialog.page_stack.currentIndex(), 2)
        QTest.mouseClick(dialog.page_jump_links[0], Qt.LeftButton)
        self.assertEqual(dialog.page_stack.currentIndex(), 0)
        QTest.mouseClick(dialog.page_jump_links[2], Qt.LeftButton)
        self.assertEqual(dialog.page_stack.currentIndex(), 2)
        dialog.close()

        dark_dialog = main.SkinSelectionDialog("carbon")
        self.assertEqual(dark_dialog.page_stack.currentIndex(), 1)
        self.assertEqual(dark_dialog.windowTitle(), "スキン選択/ダーク系")
        dark_dialog.close()

        nature_dialog = main.SkinSelectionDialog("botanical")
        self.assertEqual(nature_dialog.page_stack.currentIndex(), 2)
        self.assertEqual(nature_dialog.windowTitle(), "スキン選択/自然系")
        nature_dialog.close()

        clover_dialog = main.SkinSelectionDialog("clover")
        self.assertEqual(clover_dialog.page_stack.currentIndex(), 2)
        self.assertTrue(
            clover_dialog.findChild(QRadioButton, "skinChoice_clover").isChecked()
        )
        clover_dialog.close()

    def test_skin_card_region_selects_skin_but_no_skin_requires_radio(self):
        import main
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel, QRadioButton

        dialog = main.SkinSelectionDialog("none")
        dialog.show()
        self.app.processEvents()
        row = dialog.findChild(main.SkinChoiceRow, "skinRow_pop_tile")
        thumbnail = dialog.findChild(QLabel, "skinThumbnail_pop_camouflage_1")
        no_skin = dialog.findChild(QRadioButton, "skinChoice_none")

        QTest.mouseClick(row, Qt.LeftButton)
        self.assertEqual(dialog.selected_skin, "pop_tile")
        self.assertFalse(no_skin.isChecked())

        QTest.mouseClick(thumbnail, Qt.LeftButton)
        self.assertEqual(dialog.selected_skin, "pop_camouflage_1")

        QTest.mouseClick(no_skin, Qt.LeftButton)
        self.assertEqual(dialog.selected_skin, "none")
        self.assertTrue(no_skin.isChecked())
        dialog.close()

    def test_skin_cards_keep_white_rounded_background_after_clickable_conversion(self):
        import main
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPixmap

        dialog = main.SkinSelectionDialog("none")
        dialog.show()
        self.app.processEvents()
        row = dialog.findChild(main.SkinChoiceRow, "skinRow_pop_tile")
        rendered = QPixmap(row.size())
        rendered.fill(Qt.transparent)
        row.render(rendered)

        background = rendered.toImage().pixelColor(row.width() - 12, 12)
        self.assertGreater(background.red(), 245)
        self.assertGreater(background.green(), 245)
        self.assertGreater(background.blue(), 245)
        self.assertIn("background: #ffffff", row.styleSheet())
        self.assertIn("border-radius: 8px", row.styleSheet())
        dialog.close()

    def test_splash_artwork_viewer_dims_screen_and_closes_outside_or_by_text_x(self):
        import main
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QPixmap
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton

        image_path = Path(__file__).resolve().parents[1] / "assets" / "splash_default.png"
        viewer = main.SplashArtworkViewer(image_path)
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        self.assertFalse(viewer.image_label.pixmap().isNull())
        self.assertTrue(viewer.windowFlags() & Qt.WindowStaysOnTopHint)
        self.assertIsInstance(viewer.close_label, main.ClickableLabel)
        self.assertNotIsInstance(viewer.close_label, QPushButton)
        rendered = QPixmap(viewer.size())
        rendered.fill(Qt.transparent)
        viewer.render(rendered)
        outside = rendered.toImage().pixelColor(1, 1)
        self.assertGreater(outside.alpha(), 0)
        self.assertLess(outside.red(), 40)
        QTest.mouseClick(viewer, Qt.LeftButton, pos=QPoint(2, 2))
        self.assertFalse(viewer.isVisible())

        viewer = main.SplashArtworkViewer(image_path)
        viewer.resize(800, 600)
        viewer.show()
        self.app.processEvents()
        QTest.mouseClick(viewer.close_label, Qt.LeftButton)
        self.assertFalse(viewer.isVisible())

    def test_splash_artwork_temporarily_releases_overlay_topmost_state(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            image_path = Path(__file__).resolve().parents[1] / "assets" / "splash_default.png"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.show()
                self.app.processEvents()
                observed_overlay_topmost = []

                viewer = Mock()
                viewer.show_on_parent_screen.side_effect = lambda: observed_overlay_topmost.append(
                    bool(window.windowFlags() & main.Qt.WindowStaysOnTopHint)
                )
                with (
                    patch.object(window, "_startup_artwork_path", return_value=image_path),
                    patch.object(main, "SplashArtworkViewer", return_value=viewer),
                ):
                    self.assertTrue(window.show_splash_artwork())

                self.assertEqual(observed_overlay_topmost, [False])
                self.assertTrue(window.windowFlags() & main.Qt.WindowStaysOnTopHint)
                viewer.show_on_parent_screen.assert_called_once_with()
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_selected_skin_is_applied_and_persisted(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                self.assertTrue(window.container.testAttribute(main.Qt.WA_StyledBackground))
                self.assertFalse(window.container.has_skin())
                window.settings["skin"] = "pop_camouflage_1"
                window._apply_skin()
                self.assertTrue(window.container.has_skin())
                window._apply_display_scale()
                palette = window._background_palette()
                self.assertIn(
                    f"background: {palette['surface']}",
                    window.title_label.styleSheet(),
                )
                self.assertIn(
                    f"background: {palette['surface']}",
                    window.timer_panel.styleSheet(),
                )
                self.assertNotIn("palette", main.SKINS["pop_camouflage_1"])
                for preset in main.BACKGROUND_PRESETS.values():
                    normal = main.QColor(preset["button"])
                    selected = main.QColor(preset["checked"])
                    self.assertGreaterEqual(
                        selected.lightness() - normal.lightness(),
                        20,
                    )
                window.save_settings()
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["skin"], "pop_camouflage_1")
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_operation_tutorial_has_four_pages_and_exact_ui_terms(self):
        import main
        import math
        from PySide6.QtWidgets import QLabel

        base_point_size = self.app.font().pointSizeF()
        if base_point_size <= 0:
            base_point_size = 9
        tutorial = main.OperationTutorialDialog()
        page_text = "\n".join(
            label.text() for label in tutorial.findChildren(QLabel)
        )
        self.assertEqual(tutorial.pages.count(), 4)
        self.assertEqual(
            tutorial.tutorial_text_point_size,
            math.ceil(base_point_size * 1.2),
        )
        self.assertIn("Work 25m", page_text)
        self.assertIn("Break 5m", page_text)
        self.assertIn("Start", page_text)
        self.assertIn("Stop", page_text)
        self.assertIn("Reset", page_text)
        self.assertIn("<b>PomodoroOverlay</b>", page_text)
        self.assertIn("<b>背景色</b>", page_text)
        self.assertIn("<b>公式スキン</b>", page_text)
        self.assertTrue(tutorial.next_button.font().bold())
        self.assertFalse(tutorial.back_button.isEnabled())
        self.assertFalse(tutorial.next_button.isHidden())
        self.assertTrue(tutorial.finish_button.isHidden())

        tutorial.next_page()
        tutorial.next_page()
        tutorial.next_page()
        self.assertEqual(tutorial.pages.currentIndex(), 3)
        self.assertTrue(tutorial.next_button.isHidden())
        self.assertFalse(tutorial.finish_button.isHidden())
        tutorial.previous_page()
        self.assertEqual(tutorial.pages.currentIndex(), 2)
        tutorial.close()

        initial_tutorial = main.OperationTutorialDialog(allow_skip=True)
        self.assertIsNotNone(initial_tutorial.skip_button)
        self.assertEqual(initial_tutorial.skip_button.text(), "Skip")
        self.assertIn("color: #ffffff", initial_tutorial.styleSheet())
        initial_tutorial.close()

        help_tutorial = main.OperationTutorialDialog(allow_skip=False)
        self.assertIsNone(help_tutorial.skip_button)
        help_tutorial.close()

    def test_initial_tutorial_is_saved_after_finish_and_not_repeated(self):
        import main
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()

                def finish_tutorial():
                    tutorial = next(
                        item
                        for item in self.app.topLevelWidgets()
                        if isinstance(item, main.OperationTutorialDialog)
                        and item.isVisible()
                    )
                    tutorial.next_page()
                    tutorial.next_page()
                    tutorial.next_page()
                    tutorial.finish_button.click()

                QTimer.singleShot(10, finish_tutorial)
                self.assertTrue(window.show_initial_operation_tutorial())
                self.assertTrue(window.settings["operation_tutorial_completed"])
                self.assertTrue(json.loads(path.read_text(encoding="utf-8"))["operation_tutorial_completed"])
                self.assertFalse(window.show_initial_operation_tutorial())
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_statistics_tab_reveals_shortened_counts_after_first_completion(self):
        import main
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QDialog, QLabel

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.statistics.record_completion("work", cheat=True)
                captured_labels = []

                def inspect_dialog():
                    dialog = next(
                        item
                        for item in self.app.topLevelWidgets()
                        if isinstance(item, QDialog) and item.isVisible()
                    )
                    captured_labels.extend(
                        label.text() for label in dialog.findChildren(QLabel)
                    )
                    dialog.reject()

                window.open_settings_dialog()
                self.app.processEvents()
                inspect_dialog()
                self.app.processEvents()
                self.assertIn("ポモドーロ完了数（ズル）: 1回", captured_labels)
                self.assertIn("休憩完了数（ズル）: 0回", captured_labels)
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_sync_success_removes_only_sent_record_and_failure_keeps_pending(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.settings["notification_enabled"] = False
                pending = window.settings["stats_state"]["pending_reports"]
                pending.extend(
                    [
                        {
                            "report_id": "monthly-2026-06",
                            "report_type": "monthly",
                            "period": "2026-06",
                            "pomodoro_completed": 2,
                            "short_break_completed": 1,
                            "status": "pending",
                        },
                        {
                            "report_id": "monthly-2026-07",
                            "report_type": "monthly",
                            "period": "2026-07",
                            "pomodoro_completed": 3,
                            "short_break_completed": 2,
                            "status": "pending",
                        },
                    ]
                )
                window._finish_calendar_sync(["monthly-2026-06"], "network error")
                self.assertEqual(
                    [item["report_id"] for item in window.settings["stats_state"]["pending_reports"]],
                    ["monthly-2026-07"],
                )
                window._finish_calendar_sync([], "network error")
                self.assertEqual(window.statistics.pending_count(), 1)
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_manual_calendar_write_starts_sync_and_opens_browser(self):
        import main

        window = main.PomodoroOverlay.__new__(main.PomodoroOverlay)
        window._rollover_if_needed = Mock(return_value=False)
        window.statistics = Mock()
        window.save_settings = Mock()
        window._calendar_sync_running = False
        window._start_calendar_sync = Mock(return_value=True)
        pending_label = Mock()
        settings_dialog = Mock()
        with patch.object(main.webbrowser, "open", return_value=True) as open_browser:
            window._write_calendar(pending_label, settings_dialog)
        window._start_calendar_sync.assert_called_once_with(pending_label)
        window._rollover_if_needed.assert_called_once_with()
        window.statistics.enqueue_current_daily_report.assert_called_once_with(main.today_text())
        window.save_settings.assert_called_once_with()
        open_browser.assert_called_once_with("https://calendar.google.com/")
        settings_dialog.showMinimized.assert_called_once_with()

    def test_manual_calendar_write_during_startup_sync_requests_latest_report_retry(self):
        import main

        window = main.PomodoroOverlay.__new__(main.PomodoroOverlay)
        window._rollover_if_needed = Mock(return_value=False)
        window.statistics = Mock()
        window.save_settings = Mock()
        window._calendar_sync_running = True
        window._calendar_resync_requested = False
        window._manual_calendar_sync = False
        window._active_pending_label = None
        window._start_calendar_sync = Mock()
        window._open_google_calendar = Mock()
        pending_label = Mock()
        settings_dialog = Mock()

        window._write_calendar(pending_label, settings_dialog)

        self.assertTrue(window._calendar_resync_requested)
        self.assertTrue(window._manual_calendar_sync)
        self.assertIs(window._active_pending_label, pending_label)
        window._start_calendar_sync.assert_not_called()
        window._open_google_calendar.assert_called_once_with(settings_dialog)

    def test_sync_keeps_report_updated_during_send_and_retries_latest_snapshot(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.settings["notification_enabled"] = False
                window.statistics.enqueue_current_daily_report(main.today_text())
                report = window.settings["stats_state"]["pending_reports"][0]
                stale_snapshot = dict(report)
                report["cheat_pomodoro_completed"] = 1
                window._calendar_sync_running = True
                window._calendar_sync_records = {
                    stale_snapshot["report_id"]: stale_snapshot
                }
                window._calendar_resync_requested = True
                window._manual_calendar_sync = True

                with patch.object(main.QTimer, "singleShot") as single_shot:
                    window._finish_calendar_sync([report["report_id"]], "")

                self.assertEqual(window.statistics.pending_count(), 1)
                self.assertEqual(
                    window.settings["stats_state"]["pending_reports"][0][
                        "cheat_pomodoro_completed"
                    ],
                    1,
                )
                self.assertTrue(window._manual_calendar_sync)
                single_shot.assert_called_once_with(
                    0, window._restart_requested_calendar_sync
                )
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_open_google_calendar_uses_requested_url(self):
        import main

        window = main.PomodoroOverlay.__new__(main.PomodoroOverlay)
        settings_dialog = Mock()
        with patch.object(main.webbrowser, "open", return_value=True) as open_browser:
            window._open_google_calendar(settings_dialog)
        open_browser.assert_called_once_with("https://calendar.google.com/")
        settings_dialog.showMinimized.assert_called_once_with()
        settings_dialog.showNormal.assert_not_called()

    def test_google_auth_restores_same_settings_dialog_after_completion(self):
        import main

        window = main.PomodoroOverlay.__new__(main.PomodoroOverlay)
        window.google_calendar = Mock()
        window.google_calendar.connect.return_value = "user@example.com"
        window.settings = {
            "integration": {
                "google_calendar_enabled": False,
                "google_calendar_account": None,
            }
        }
        window.save_settings = Mock()
        window._start_calendar_sync = Mock()
        dialog = Mock()
        connection_label = Mock()
        account_label = Mock()
        pending_label = Mock()
        open_button = Mock()

        with patch.object(main.Path, "is_file", return_value=True):
            window._connect_google_calendar(
                dialog,
                connection_label,
                account_label,
                pending_label,
                open_button,
            )

        dialog.showMinimized.assert_called_once_with()
        dialog.showNormal.assert_called_once_with()
        dialog.raise_.assert_called_once_with()
        dialog.activateWindow.assert_called_once_with()
        open_button.setEnabled.assert_called_once_with(True)
        self.assertEqual(
            window.settings["integration"]["google_calendar_account"],
            "user@example.com",
        )

    def test_exit_dialog_exit_button_quits_application(self):
        import main
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.show()

                exit_dialog_styles = []

                def click_exit():
                    dialog = next(
                        item
                        for item in self.app.topLevelWidgets()
                        if isinstance(item, QMessageBox) and item.isVisible()
                    )
                    exit_dialog_styles.append(dialog.styleSheet())
                    exit_button = next(
                        button for button in dialog.buttons() if button.text() == "終了"
                    )
                    exit_button.click()

                QTimer.singleShot(10, click_exit)
                window.confirm_full_exit()
                self.assertIn("QMessageBox QLabel { color: #ffffff", exit_dialog_styles[0])
                self.assertTrue(window._is_quitting)
                self.assertFalse(window.isVisible())
                window.date_check_timer.stop()

    def test_runtime_shutdown_stops_workers_timers_notifications_and_socket(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.splash_assets = Mock()
                window.notification_service = Mock()
                window._lock_socket = Mock()
                window._calendar_sync_thread = threading.Thread(
                    target=lambda: window._calendar_sync_cancel.wait(2), daemon=True
                )
                window._calendar_sync_thread.start()

                window._shutdown_runtime()

                self.assertTrue(window._shutdown_complete)
                self.assertTrue(window._calendar_sync_cancel.is_set())
                self.assertFalse(window.timer.isActive())
                self.assertFalse(window.date_check_timer.isActive())
                window.splash_assets.cancel.assert_called_once_with(wait=True)
                window.notification_service.shutdown.assert_called_once_with()
                self.assertIsNone(window._calendar_sync_thread)
                self.assertIsNone(window._lock_socket)
                window._is_quitting = True
                window.close()

    def test_time_shortening_checkbox_toggles_timer_without_persisting_it(self):
        import main
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with (
                patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path),
                patch.object(main, "ENABLE_TIME_SHORTENING_MODE", True),
            ):
                window = main.PomodoroOverlay()
                window.notification_service.notify_time_shortening_mode = Mock(return_value=True)
                enabled_labels = []

                def enable_in_settings():
                    dialog = next(
                        item
                        for item in self.app.topLevelWidgets()
                        if isinstance(item, QDialog) and item.isVisible()
                    )
                    checkboxes = dialog.findChildren(main.BorderedCheckBox)
                    enabled_labels.extend(item.text() for item in checkboxes)
                    for checkbox in checkboxes:
                        if checkbox.text() == "時間短縮モード（Work 25秒 / Break 5秒）":
                            checkbox.setChecked(True)
                    dialog.findChild(QDialogButtonBox).button(
                        QDialogButtonBox.Ok
                    ).click()

                window.open_settings_dialog()
                self.app.processEvents()
                enable_in_settings()
                self.app.processEvents()
                self.assertIn("時間短縮モード（Work 25秒 / Break 5秒）", enabled_labels)
                self.assertTrue(window.time_shortening_enabled)
                self.assertEqual(window.remaining_seconds, 25)
                self.assertEqual(window.timer_label.text(), "00:25")
                window.save_settings()
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["remaining_seconds"], 25 * 60)
                self.assertNotIn("time_shortening_enabled", saved)

                captured_titles = []
                captured_checked = []

                def disable_in_settings():
                    dialog = next(
                        item
                        for item in self.app.topLevelWidgets()
                        if isinstance(item, QDialog) and item.isVisible()
                    )
                    captured_titles.append(dialog.windowTitle())
                    for checkbox in dialog.findChildren(main.BorderedCheckBox):
                        if checkbox.text() == "時間短縮モード（Work 25秒 / Break 5秒）":
                            captured_checked.append(checkbox.isChecked())
                            checkbox.setChecked(False)
                    dialog.findChild(QDialogButtonBox).button(
                        QDialogButtonBox.Ok
                    ).click()

                window.open_settings_dialog()
                self.app.processEvents()
                disable_in_settings()
                self.app.processEvents()
                self.assertEqual(
                    captured_titles,
                    [f"PomodoroOverlay v{main.APP_VERSION} 時間短縮モード"],
                )
                self.assertEqual(captured_checked, [True])
                self.assertFalse(window.time_shortening_enabled)
                self.assertEqual(window.remaining_seconds, 25 * 60)
                self.assertEqual(window.timer_label.text(), "25:00")
                self.assertEqual(
                    window.notification_service.notify_time_shortening_mode.call_args_list,
                    [call(True), call(False)],
                )
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_time_shortening_feature_flag_hides_checkbox(self):
        import main
        from PySide6.QtWidgets import QDialog

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with (
                patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path),
                patch.object(main, "ENABLE_TIME_SHORTENING_MODE", False),
            ):
                window = main.PomodoroOverlay()
                captured_labels = []

                def inspect_settings():
                    dialog = next(
                        item
                        for item in self.app.topLevelWidgets()
                        if isinstance(item, QDialog) and item.isVisible()
                    )
                    captured_labels.extend(
                        item.text() for item in dialog.findChildren(main.BorderedCheckBox)
                    )
                    dialog.reject()

                window.open_settings_dialog()
                self.app.processEvents()
                inspect_settings()
                self.app.processEvents()
                self.assertNotIn("時間短縮モード（Work 25秒 / Break 5秒）", captured_labels)
                self.assertFalse(window.time_shortening_enabled)
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_time_shortening_notifications_use_windows_short_duration(self):
        import main

        service = main.NotificationService.__new__(main.NotificationService)
        toaster = Mock()
        service.toaster = toaster
        self.assertTrue(service.notify_time_shortening_mode(True))
        enabled_toast = service.toaster.show_toast.call_args.args[0]
        self.assertEqual(enabled_toast.text_fields[0], "時間短縮モード")
        self.assertIn("移行", enabled_toast.text_fields[1])
        self.assertEqual(enabled_toast.duration, main.ToastDuration.Short)
        self.assertIsNone(enabled_toast.expiration_time)
        self.assertIs(service.time_shortening_toast, enabled_toast)
        self.assertTrue(service.notify_time_shortening_mode(False))
        service.toaster.remove_toast.assert_called_once_with(enabled_toast)
        disabled_toast = service.toaster.show_toast.call_args.args[0]
        self.assertIn("解除", disabled_toast.text_fields[1])
        self.assertIs(service.time_shortening_toast, disabled_toast)

    def test_notification_shutdown_removes_toasts_and_callbacks(self):
        import main

        service = main.NotificationService.__new__(main.NotificationService)
        toaster = Mock()
        service.toaster = toaster
        service.session_activated_callback = Mock()
        service.session_completion_toast = Mock(on_activated=Mock())
        service.time_shortening_toast = Mock()
        service.monthly_report_toast = Mock()
        service.transient_toasts = [Mock(), Mock()]
        expected_toasts = [
            service.session_completion_toast,
            service.time_shortening_toast,
            service.monthly_report_toast,
            *service.transient_toasts,
        ]

        service.shutdown()

        self.assertIsNone(service.toaster)
        for toast in expected_toasts:
            self.assertIn(call(toast), toaster.remove_toast.call_args_list)
        toaster.clear_toasts.assert_called_once_with()

    def test_session_notifications_use_standard_click_to_close_toast(self):
        import main

        service = main.NotificationService.__new__(main.NotificationService)
        service.toaster = Mock()
        service.session_activated_callback = Mock()
        for completed_mode in ("work", "break"):
            self.assertTrue(service.notify_session_completed(completed_mode, sound_enabled=True))
            toast = service.toaster.show_toast.call_args.args[0]
            self.assertEqual(toast.actions, [])
            toast.on_activated(Mock())
            service.session_activated_callback.assert_called()
            self.assertIs(service.session_completion_toast, toast)
            self.assertTrue(service.dismiss_session_completion())
            service.toaster.remove_toast.assert_called_with(toast)
            self.assertIsNone(service.session_completion_toast)

    def test_session_notification_activation_restores_window(self):
        import main

        window = main.PomodoroOverlay.__new__(main.PomodoroOverlay)
        window.showNormal = Mock()
        window.raise_ = Mock()
        window.activateWindow = Mock()
        window._restore_from_session_notification()
        window.showNormal.assert_called_once_with()
        window.raise_.assert_called_once_with()
        window.activateWindow.assert_called_once_with()

    def test_calendar_failure_notification_stays_as_reminder_without_button(self):
        import main

        service = main.NotificationService.__new__(main.NotificationService)
        service.toaster = Mock()
        self.assertTrue(service.notify_calendar_write(False, sound_enabled=True))
        toast = service.toaster.show_toast.call_args.args[0]
        self.assertEqual(toast.scenario, main.ToastScenario.Reminder)
        self.assertEqual(toast.duration, main.ToastDuration.Long)
        self.assertEqual(toast.actions, [])
        self.assertIn("Googleカレンダーとの再連携", toast.text_fields[1])

    def test_daily_report_toast_is_short_and_monthly_report_is_persistent(self):
        import main

        service = main.NotificationService.__new__(main.NotificationService)
        service.toaster = Mock()
        service.monthly_report_toast = None
        daily = {"period": "2026-07-31"}
        monthly = {"period": "2026-07"}
        self.assertTrue(service.notify_daily_report(daily, sound_enabled=True))
        daily_toast = service.toaster.show_toast.call_args.args[0]
        self.assertEqual(daily_toast.duration, main.ToastDuration.Short)
        self.assertTrue(service.notify_monthly_report(monthly, sound_enabled=True))
        monthly_toast = service.toaster.show_toast.call_args.args[0]
        self.assertEqual(monthly_toast.scenario, main.ToastScenario.Reminder)
        self.assertEqual(monthly_toast.duration, main.ToastDuration.Long)
        self.assertIs(service.monthly_report_toast, monthly_toast)
        self.assertTrue(service.dismiss_monthly_report())
        service.toaster.remove_toast.assert_called_with(monthly_toast)

    def test_completed_year_waits_for_monthly_notification_dismissal(self):
        import main

        window = main.PomodoroOverlay.__new__(main.PomodoroOverlay)
        window.settings = {
            "notification_enabled": True,
            "notification_sound_enabled": True,
        }
        window.notification_service = Mock()
        window.notification_service.notify_monthly_report.return_value = True
        window._monthly_report_waiting = False
        window._pending_yearly_reports = []
        window._show_next_year_report_dialog = Mock()
        reports = [
            {"report_type": "monthly", "period": "2026-12"},
            {"report_type": "yearly", "period": "2026"},
        ]
        window._notify_completed_reports(reports)
        self.assertTrue(window._monthly_report_waiting)
        self.assertEqual(window._pending_yearly_reports, [reports[1]])
        window._dismiss_monthly_report_and_continue()
        self.assertFalse(window._monthly_report_waiting)
        window.notification_service.dismiss_monthly_report.assert_called_once_with()

    def test_time_shortening_completes_work_in_25_ticks_and_break_in_5_ticks(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                window.settings["notification_enabled"] = False
                window._set_time_shortening_mode(True)
                for _ in range(24):
                    window.tick()
                self.assertEqual(window.current_mode, "work")
                self.assertEqual(window.remaining_seconds, 1)
                window.tick()
                self.assertEqual(window.current_mode, "break")
                self.assertEqual(window.remaining_seconds, 5)
                self.assertFalse(window.work_button.isChecked())
                self.assertTrue(window.break_button.isChecked())
                self.assertEqual(
                    window.settings["stats_state"]["today"]["pomodoro_completed"], 0
                )
                self.assertEqual(
                    window.settings["stats_state"]["today"]["cheat_pomodoro_completed"], 1
                )
                for _ in range(5):
                    window.tick()
                self.assertEqual(window.current_mode, "work")
                self.assertEqual(window.remaining_seconds, 25)
                self.assertTrue(window.work_button.isChecked())
                self.assertFalse(window.break_button.isChecked())
                self.assertEqual(
                    window.settings["stats_state"]["today"]["short_break_completed"], 0
                )
                self.assertEqual(
                    window.settings["stats_state"]["today"]["cheat_short_break_completed"], 1
                )
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_invalid_data_is_safely_normalized(self):
        settings = {
            "stats_state": {
                "last_activity_date": "bad",
                "today": {"date": "bad", "pomodoro_completed": "many"},
                "pending_reports": [None, {"report_type": "bad"}],
            },
        }
        manager = StatisticsManager(settings, "2026-07-18")
        self.assertEqual(settings["stats_state"]["today"]["pomodoro_completed"], 0)
        self.assertEqual(settings["stats_state"]["today"]["date"], "2026-07-18")
        self.assertEqual(manager.pending_count(), 0)

    def test_invalid_settings_json_values_fall_back_to_safe_defaults(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "mode": "invalid",
                        "remaining_seconds": "forever",
                        "display_scale": 999,
                        "geometry": "not-hex",
                        "window": {
                            "x": "left",
                            "y": None,
                            "width": -1,
                            "height": 999999,
                        },
                        "general": {
                            "always_on_top": "yes",
                            "confirm_full_exit": None,
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                window = main.PomodoroOverlay()
                self.assertEqual(window.current_mode, "work")
                self.assertEqual(window.remaining_seconds, 25 * 60)
                self.assertEqual(window.settings["display_scale"], 100)
                self.assertIsNone(window.settings["geometry"])
                self.assertEqual(window.settings["window"], window.default_settings["window"])
                self.assertEqual(window.settings["general"], window.default_settings["general"])
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

    def test_non_object_or_oversized_settings_file_is_rejected(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(main.PomodoroOverlay, "_get_settings_path", return_value=path):
                path.write_text("[]", encoding="utf-8")
                window = main.PomodoroOverlay()
                self.assertEqual(window.current_mode, "work")
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()

                path.write_bytes(b" " * (main.MAX_SETTINGS_FILE_BYTES + 1))
                window = main.PomodoroOverlay()
                self.assertEqual(window.current_mode, "work")
                window.date_check_timer.stop()
                window._is_quitting = True
                window.close()


if __name__ == "__main__":
    unittest.main()
