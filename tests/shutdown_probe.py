"""Isolated native-shutdown probe for Windows component bisecting."""

import ctypes
import os
import socket
import sys
import tempfile
import time
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Suppress Windows native-error dialogs so access violations are observable as
# subprocess exit codes instead of blocking unattended diagnostics.
if sys.platform == "win32":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)


def run_pyside_only():
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication([])
    widget = QWidget()
    timer = QTimer(widget)
    timer.start(10)

    def shutdown():
        timer.stop()
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.quit()

    QTimer.singleShot(40, shutdown)
    return app.exec()


def run_pyside_stress():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication([])
    for _ in range(40):
        widget = QWidget()
        widget.close()
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
    app.quit()
    return 0


def run_overlay(mode):
    import main
    from PySide6.QtCore import QCoreApplication, QEvent, QTimer
    from PySide6.QtWidgets import QApplication

    use_toasts = mode in {"toasts", "all"}
    use_calendar = mode in {"calendar", "all"}
    use_socket = mode in {"socket", "all"}
    if not use_toasts:
        main.WindowsToaster = None

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as directory:
        settings_path = Path(directory) / "settings.json"

        class ProbeOverlay(main.PomodoroOverlay):
            def _get_settings_path(self):
                return settings_path

        window = ProbeOverlay()
        if use_socket:
            lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            lock_socket.bind(("127.0.0.1", 0))
            lock_socket.listen(1)
            window._lock_socket = lock_socket

        if use_toasts:
            window.notification_service.notify_time_shortening_mode(True)

        if use_calendar:
            class FakeCalendar:
                @staticmethod
                def has_credentials():
                    return True

                @staticmethod
                def send_record(_record):
                    time.sleep(0.25)
                    return True

            window.google_calendar = FakeCalendar()
            window.settings["integration"]["google_calendar_enabled"] = True
            window.settings["stats_state"]["pending_reports"] = [
                {
                    "report_id": "daily-2026-07-20",
                    "report_type": "daily",
                    "period": "2026-07-20",
                    "created_at": "",
                    "pomodoro_completed": 1,
                    "short_break_completed": 0,
                    "cheat_pomodoro_completed": 0,
                    "cheat_short_break_completed": 0,
                    "status": "pending",
                }
            ]
            window._start_calendar_sync()

        def shutdown():
            window.quit_application()

        QTimer.singleShot(60, shutdown)
        exit_code = app.exec()
        if not window._shutdown_complete:
            window._is_quitting = True
            window._shutdown_runtime()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        return exit_code


def run_overlay_stress():
    import main
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    main.WindowsToaster = None
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for index in range(30):
            settings_path = root / f"settings-{index}.json"

            class ProbeOverlay(main.PomodoroOverlay):
                def _get_settings_path(self):
                    return settings_path

            window = ProbeOverlay()
            window._is_quitting = True
            window._shutdown_runtime()
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
    app.quit()
    return 0


def main_probe():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pyside"
    if mode == "pyside":
        return run_pyside_only()
    if mode == "pyside_stress":
        return run_pyside_stress()
    if mode == "overlay_stress":
        return run_overlay_stress()
    if mode not in {"overlay", "toasts", "calendar", "socket", "all"}:
        raise SystemExit(f"Unknown probe mode: {mode}")
    return run_overlay(mode)


if __name__ == "__main__":
    raise SystemExit(main_probe())
