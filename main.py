import json
import logging
import math
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
    QTabWidget,
    QProgressDialog,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
)

from stats_integration import (
    COUNTER_KEYS,
    GoogleCalendarClient,
    StatisticsManager,
    today_text,
)
from time_shortening import ENABLE_TIME_SHORTENING_MODE
from splash_assets import SplashAssetManager, SplashWindow
from version import APP_NAME, APP_VERSION

try:
    from windows_toasts import (
        Toast,
        ToastAudio,
        ToastDuration,
        ToastScenario,
        WindowsToaster,
    )
except ImportError:  # pragma: no cover - notification failure must be non-fatal
    Toast = None
    ToastAudio = None
    ToastDuration = None
    ToastScenario = None
    WindowsToaster = None

MAX_SETTINGS_FILE_BYTES = 2 * 1024 * 1024
SPLASH_DISPLAY_MS = 1000
LOGGER = logging.getLogger("PomodoroOverlay")

BACKGROUND_PRESETS = {
    "cream": {
        "label": "クリーム",
        "background": "#FFF3DE",
        "surface": "#FFF9EB",
        "border": "#E4CFA9",
        "text": "#111111",
        "button": "#746348",
        "button_border": "#493A21",
        "checked": "#B08E58",
        "hover": "#987A46",
        "pressed": "#6F572F",
        "disabled": "#D9C7A6",
    },
    "sage": {
        "label": "セージ",
        "background": "#E6EAD9",
        "surface": "#F2F5E9",
        "border": "#C3CBB4",
        "text": "#111111",
        "button": "#49524C",
        "button_border": "#202923",
        "checked": "#5B6D60",
        "hover": "#4A5C4F",
        "pressed": "#303D34",
        "disabled": "#9AA79A",
    },
    "mist_blue": {
        "label": "ミストブルー",
        "background": "#DCEBF3",
        "surface": "#EDF4FA",
        "border": "#B8CAD8",
        "text": "#111111",
        "button": "#43505D",
        "button_border": "#1B2733",
        "checked": "#566F88",
        "hover": "#425A73",
        "pressed": "#293B4D",
        "disabled": "#9BB0C6",
    },
    "dusty_rose": {
        "label": "ダスティローズ",
        "background": "#F2DCE1",
        "surface": "#F9EEF0",
        "border": "#DAB7C0",
        "text": "#111111",
        "button": "#62494D",
        "button_border": "#382126",
        "checked": "#965F69",
        "hover": "#7D4A53",
        "pressed": "#523038",
        "disabled": "#C99AA2",
    },
    "gray": {
        "label": "ソフトグレー",
        "background": "#E6E6E8",
        "surface": "#F2F2F3",
        "border": "#C7C7CA",
        "text": "#111111",
        "button": "#4C4E50",
        "button_border": "#242527",
        "checked": "#686A6E",
        "hover": "#535559",
        "pressed": "#343639",
        "disabled": "#A1A3A7",
    },
}

SKINS = {
    "pop_camouflage_1": {
        "label": "ポップ迷彩",
        "asset": "assets/skins/pop_camouflage_1.png",
    },
    "carbon": {
        "label": "カーボン",
        "asset": "assets/skins/carbon.png",
    },
    "galaxy_1": {
        "label": "ギャラクシー",
        "asset": "assets/skins/galaxy_1.png",
    },
    "hairline": {
        "label": "ヘアライン",
        "asset": "assets/skins/hairline.png",
    },
    "pop_tile": {
        "label": "ポップタイル",
        "asset": "assets/skins/pop_tile.png",
    },
    "takeda_bishi": {
        "label": "武田菱",
        "asset": "assets/skins/takeda_bishi.png",
    },
    "flower": {
        "label": "フラワー",
        "asset": "assets/skins/flower.png",
    },
    "botanical": {
        "label": "ボタニカル",
        "asset": "assets/skins/botanical.png",
    },
    "clover": {
        "label": "クローバー",
        "asset": "assets/skins/clover.png",
    },
}

SKIN_PAGES = (
    ("カラー系", ("pop_camouflage_1", "pop_tile", "takeda_bishi")),
    ("ダーク系", ("carbon", "galaxy_1", "hairline")),
    ("自然系", ("flower", "botanical", "clover")),
)


def bundled_path(relative_path):
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return root / relative_path


def skin_asset_path(skin_key):
    skin = SKINS.get(skin_key)
    if skin is None:
        return None
    path = bundled_path(skin["asset"])
    return path if path.is_file() else None


class SplashLifetime:
    """Guard a WA_DeleteOnClose splash without retaining a stale QObject."""

    def __init__(self, splash):
        self._splash = splash
        splash.destroyed.connect(self._clear)

    def _clear(self, *_args):
        self._splash = None

    def close(self):
        splash = self._splash
        self._splash = None
        if splash is None or not shiboken6.isValid(splash):
            return False
        splash.close()
        return True

    @property
    def is_alive(self):
        return self._splash is not None and shiboken6.isValid(self._splash)


class SkinPanel(QWidget):
    """Overlay panel that paints a cropped skin beneath transparent child widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._skin_pixmap = QPixmap()
        self._skin_border = QColor("#C9B96F")

    def set_skin(self, image_path=None, border_color="#C9B96F"):
        self._skin_pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        self._skin_border = QColor(border_color)
        self.update()

    def set_border_color(self, border_color):
        self._skin_border = QColor(border_color)
        self.update()

    def has_skin(self):
        return not self._skin_pixmap.isNull()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._skin_pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        target = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(QRectF(target), 17, 17)
        painter.setClipPath(path)
        scaled = self._skin_pixmap.scaled(
            target.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        source_x = max(0, (scaled.width() - target.width()) // 2)
        source_y = max(0, (scaled.height() - target.height()) // 2)
        painter.drawPixmap(target, scaled, scaled.rect().adjusted(
            source_x,
            source_y,
            -(scaled.width() - target.width() - source_x),
            -(scaled.height() - target.height() - source_y),
        ))
        painter.setClipping(False)
        painter.setPen(QPen(self._skin_border, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(target, 17, 17)


class SkinPageLink(QLabel):
    """Plain-text page link that can be visibly and functionally disabled."""

    activated = Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._link_enabled = True
        self.setAlignment(Qt.AlignCenter)
        self.set_link_enabled(True)

    def set_link_enabled(self, enabled):
        self._link_enabled = bool(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        color = "#303030" if enabled else "#a0a0a0"
        decoration = "underline" if enabled else "none"
        self.setStyleSheet(
            f"background: transparent; color: {color}; text-decoration: {decoration};"
        )

    def is_link_enabled(self):
        return self._link_enabled

    def mousePressEvent(self, event):
        if self._link_enabled and event.button() == Qt.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class SkinChoiceRow(QWidget):
    """Clickable skin card; selecting the card selects its radio button."""

    activated = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class SkinSelectionDialog(QDialog):
    """Paged skin picker grouped into color, dark, and natural categories."""

    def __init__(self, current_skin="none", parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 390)
        self.selected_skin = current_skin if current_skin in SKINS else "none"
        self.setStyleSheet(
            "QDialog, QWidget { background: #f2f2f2; color: #202020; }"
            "QLabel, QRadioButton { background: transparent; color: #202020; }"
            "QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid #666666; "
            "border-radius: 8px; background: #ffffff; }"
            "QRadioButton::indicator:checked { background: "
            "qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, "
            "stop:0 #e53935, stop:0.43 #e53935, stop:0.46 #ffffff, stop:1 #ffffff); }"
            "QScrollArea { border: 1px solid #aaaaaa; background: #ffffff; }"
            "QPushButton { background: #383838; color: #ffffff; border: 1px solid #555555; "
            "border-radius: 7px; padding: 7px 14px; }"
        )

        self.skin_buttons = QButtonGroup(self)
        self.skin_buttons.setExclusive(True)
        no_skin = QRadioButton("スキンなし（背景色を使用）")
        no_skin.setObjectName("skinChoice_none")
        no_skin.setChecked(self.selected_skin == "none")
        no_skin.toggled.connect(lambda checked: self._select_skin("none", checked))
        self.skin_buttons.addButton(no_skin)

        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("skinPageStack")
        for page_index, (_category, skin_keys) in enumerate(SKIN_PAGES):
            scroll = QScrollArea(self)
            scroll_names = ("skinScrollArea", "skinScrollArea_dark", "skinScrollArea_nature")
            scroll.setObjectName(scroll_names[page_index])
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            list_widget = QWidget()
            list_widget.setObjectName(f"skinPage_{page_index + 1}")
            list_layout = QVBoxLayout(list_widget)
            list_layout.setContentsMargins(10, 10, 10, 10)
            list_layout.setSpacing(10)

            for skin_key in skin_keys:
                skin = SKINS[skin_key]
                row = SkinChoiceRow()
                row.setObjectName(f"skinRow_{skin_key}")
                row.setAttribute(Qt.WA_StyledBackground, True)
                row.setStyleSheet(
                    "#skinRow_%s { background: #ffffff; border: 1px solid #c4c4c4; "
                    "border-radius: 8px; }" % skin_key
                )
                row_layout = QHBoxLayout(row)
                thumbnail = QLabel()
                thumbnail.setObjectName(f"skinThumbnail_{skin_key}")
                thumbnail.setFixedSize(170, 105)
                thumbnail.setAlignment(Qt.AlignCenter)
                asset_path = skin_asset_path(skin_key)
                if asset_path is not None:
                    thumbnail.setPixmap(
                        QPixmap(str(asset_path)).scaled(
                            thumbnail.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                    )
                radio = QRadioButton(skin["label"])
                radio.setObjectName(f"skinChoice_{skin_key}")
                radio.setChecked(self.selected_skin == skin_key)
                radio.toggled.connect(
                    lambda checked, key=skin_key: self._select_skin(key, checked)
                )
                row.activated.connect(radio.click)
                self.skin_buttons.addButton(radio)
                row_layout.addWidget(thumbnail)
                row_layout.addWidget(radio, 1)
                list_layout.addWidget(row)

            list_layout.addStretch(1)
            scroll.setWidget(list_widget)
            self.page_stack.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("適用")
        buttons.button(QDialogButtonBox.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.previous_page_link = SkinPageLink("＜＜", self)
        self.previous_page_link.setObjectName("skinPagePrevious")
        self.next_page_link = SkinPageLink("＞＞", self)
        self.next_page_link.setObjectName("skinPageNext")
        self.previous_page_link.activated.connect(
            lambda: self._show_page(self.page_stack.currentIndex() - 1)
        )
        self.next_page_link.activated.connect(
            lambda: self._show_page(self.page_stack.currentIndex() + 1)
        )
        self.page_jump_links = []
        page_jumps = QHBoxLayout()
        page_jumps.addStretch(1)
        for page_index in range(len(SKIN_PAGES)):
            page_link = SkinPageLink(str(page_index + 1), self)
            page_link.setObjectName(f"skinPageJump_{page_index + 1}")
            page_link.activated.connect(
                lambda index=page_index: self._show_page(index)
            )
            self.page_jump_links.append(page_link)
            page_jumps.addWidget(page_link)
            if page_index < len(SKIN_PAGES) - 1:
                page_jumps.addSpacing(12)
        page_jumps.addStretch(1)

        page_links = QHBoxLayout()
        page_links.addStretch(1)
        page_links.addWidget(self.previous_page_link)
        page_links.addSpacing(18)
        page_links.addWidget(self.next_page_link)
        page_links.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(no_skin)
        layout.addWidget(self.page_stack)
        layout.addLayout(page_jumps)
        layout.addLayout(page_links)
        layout.addWidget(buttons)

        initial_page = 0
        for page_index, (_category, skin_keys) in enumerate(SKIN_PAGES):
            if self.selected_skin in skin_keys:
                initial_page = page_index
                break
        self._show_page(initial_page)

    def _select_skin(self, skin_key, checked):
        if checked:
            self.selected_skin = skin_key

    def _show_page(self, page_index):
        if not 0 <= page_index < len(SKIN_PAGES):
            return
        self.page_stack.setCurrentIndex(page_index)
        category = SKIN_PAGES[page_index][0]
        self.setWindowTitle(f"スキン選択/{category}")
        self.previous_page_link.set_link_enabled(page_index > 0)
        self.next_page_link.set_link_enabled(page_index < len(SKIN_PAGES) - 1)
        for index, page_link in enumerate(self.page_jump_links):
            page_link.set_link_enabled(index != page_index)


class BorderedCheckBox(QCheckBox):
    """Keep the native check mark and draw a clear neutral border around it."""

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        indicator_rect = self.style().subElementRect(
            QStyle.SE_CheckBoxIndicator, option, self
        )
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#666666"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(indicator_rect.adjusted(0, 0, -1, -1), 3, 3)


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class SplashArtworkViewer(QDialog):
    """Dimmed full-screen viewer closed by its text × or the area outside art."""

    def __init__(self, image_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("起動スプラッシュのイラスト")
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._artwork = QPixmap(str(image_path)) if image_path else QPixmap()
        self.image_label = QLabel(self)
        self.image_label.setObjectName("splashArtworkImage")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: transparent;")
        self.close_label = ClickableLabel("×", self)
        self.close_label.setObjectName("splashArtworkClose")
        self.close_label.setAlignment(Qt.AlignCenter)
        self.close_label.setToolTip("閉じる")
        self.close_label.setStyleSheet(
            "color: #ffffff; background: transparent; font-size: 30px; font-weight: 700;"
        )
        self.close_label.clicked.connect(self.reject)

    def show_on_parent_screen(self):
        screen = self.parentWidget().screen() if self.parentWidget() else QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        return self.exec()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 165))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._artwork.isNull():
            self.image_label.setGeometry(self.rect())
            return
        maximum = self.size() * 0.78
        scaled = self._artwork.scaled(
            maximum, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        left = (self.width() - scaled.width()) // 2
        top = (self.height() - scaled.height()) // 2
        self.image_label.setGeometry(left, top, scaled.width(), scaled.height())
        self.image_label.setPixmap(scaled)
        close_size = 42
        close_left = min(self.width() - close_size - 12, left + scaled.width() + 10)
        close_top = max(12, top - 6)
        self.close_label.setGeometry(close_left, close_top, close_size, close_size)
        self.close_label.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.image_label.geometry().contains(
            event.position().toPoint()
        ):
            self.reject()
            event.accept()
            return
        super().mousePressEvent(event)


class NotificationService:
    """Send local Windows notifications without affecting timer completion."""

    def __init__(self, session_activated_callback=None):
        self.toaster = None
        self.session_completion_toast = None
        self.time_shortening_toast = None
        self.monthly_report_toast = None
        self.transient_toasts = []
        self.session_activated_callback = session_activated_callback
        if WindowsToaster is None:
            LOGGER.error("Windows-Toasts is unavailable; notifications are disabled")
            return
        try:
            self.toaster = WindowsToaster("PomodoroOverlay")
        except Exception:
            LOGGER.exception("Failed to initialize Windows notifications")

    def notify_session_completed(self, completed_mode, sound_enabled=True):
        if self.toaster is None or Toast is None:
            return False
        if completed_mode == "work":
            title = "作業時間が終了しました"
            message = "休憩に切り替えましょう。"
        else:
            title = "休憩時間が終了しました"
            message = "作業を再開しましょう。"
        try:
            toast = Toast()
            toast.text_fields = [title, message]
            callback = getattr(self, "session_activated_callback", None)
            if callback is not None:
                toast.on_activated = lambda _event: callback()
            if not sound_enabled and ToastAudio is not None:
                toast.audio = ToastAudio(silent=True)
            self.toaster.show_toast(toast)
            self.session_completion_toast = toast
            return True
        except Exception:
            LOGGER.exception("Failed to send Windows notification")
            return False

    def dismiss_session_completion(self):
        toast = getattr(self, "session_completion_toast", None)
        if self.toaster is None or toast is None:
            return False
        try:
            self.toaster.remove_toast(toast)
            return True
        except Exception:
            LOGGER.exception("Failed to dismiss session-completion notification")
            return False
        finally:
            self.session_completion_toast = None

    def notify_time_shortening_mode(self, enabled):
        if self.toaster is None or Toast is None:
            return False
        try:
            self.dismiss_time_shortening_mode()
            toast = Toast()
            toast.text_fields = [
                "時間短縮モード",
                "時間短縮モードに移行しました（Work 25秒 / Break 5秒）"
                if enabled
                else "時間短縮モードを解除しました",
            ]
            if ToastDuration is not None:
                toast.duration = ToastDuration.Short
            self.toaster.show_toast(toast)
            self.time_shortening_toast = toast
            return True
        except Exception:
            LOGGER.exception("Failed to send time-shortening notification")
            return False

    def dismiss_time_shortening_mode(self):
        toast = getattr(self, "time_shortening_toast", None)
        if self.toaster is None or toast is None:
            return False
        try:
            self.toaster.remove_toast(toast)
            return True
        except Exception:
            LOGGER.exception("Failed to dismiss time-shortening notification")
            return False
        finally:
            self.time_shortening_toast = None

    def notify_calendar_write(self, success, sound_enabled=True):
        if self.toaster is None or Toast is None:
            return False
        try:
            toast = Toast()
            if success:
                toast.text_fields = ["Googleカレンダー連携", "書き込みが完了しました。"]
            else:
                toast.text_fields = [
                    "Googleカレンダー連携",
                    "書き込みに失敗しました。Googleカレンダーとの再連携をお試しください。",
                ]
                if ToastScenario is not None:
                    toast.scenario = ToastScenario.Reminder
                if ToastDuration is not None:
                    toast.duration = ToastDuration.Long
            if not sound_enabled and ToastAudio is not None:
                toast.audio = ToastAudio(silent=True)
            self.toaster.show_toast(toast)
            self._remember_transient(toast)
            return True
        except Exception:
            LOGGER.exception("Failed to send calendar-write notification")
            return False

    def notify_daily_report(self, report, sound_enabled=True):
        return self._show_report_toast(
            "日報を記録しました",
            f"{report['period']} の実績をGoogleカレンダーへ記録しました。",
            sound_enabled,
        )

    def notify_monthly_report(self, report, sound_enabled=True):
        if self.toaster is None or Toast is None:
            return False
        try:
            toast = Toast()
            toast.text_fields = [
                "月報を記録しました",
                f"{report['period']} の実績をGoogleカレンダーへ記録しました。",
            ]
            if ToastScenario is not None:
                toast.scenario = ToastScenario.Reminder
            if ToastDuration is not None:
                toast.duration = ToastDuration.Long
            if not sound_enabled and ToastAudio is not None:
                toast.audio = ToastAudio(silent=True)
            self.toaster.show_toast(toast)
            self.monthly_report_toast = toast
            return True
        except Exception:
            LOGGER.exception("Failed to send monthly-report notification")
            return False

    def dismiss_monthly_report(self):
        toast = self.monthly_report_toast
        if self.toaster is None or toast is None:
            return False
        try:
            self.toaster.remove_toast(toast)
            return True
        except Exception:
            LOGGER.exception("Failed to dismiss monthly-report notification")
            return False
        finally:
            self.monthly_report_toast = None

    def notify_happy_new_year(self, year, sound_enabled=True):
        return self._show_report_toast(
            "🎉 Happy New Year",
            f"{year}年の実績をGoogleカレンダーへ記録しました。\n今年もよろしくお願いします。",
            sound_enabled,
        )

    def _show_report_toast(self, title, message, sound_enabled):
        if self.toaster is None or Toast is None:
            return False
        try:
            toast = Toast()
            toast.text_fields = [title, message]
            if ToastDuration is not None:
                toast.duration = ToastDuration.Short
            if not sound_enabled and ToastAudio is not None:
                toast.audio = ToastAudio(silent=True)
            self.toaster.show_toast(toast)
            self._remember_transient(toast)
            return True
        except Exception:
            LOGGER.exception("Failed to send report notification")
            return False

    def _remember_transient(self, toast):
        toasts = getattr(self, "transient_toasts", None)
        if toasts is None:
            self.transient_toasts = []
            toasts = self.transient_toasts
        toasts.append(toast)

    def shutdown(self):
        toaster = self.toaster
        if toaster is None:
            self.session_activated_callback = None
            return
        toasts = [
            getattr(self, "session_completion_toast", None),
            getattr(self, "time_shortening_toast", None),
            getattr(self, "monthly_report_toast", None),
            *getattr(self, "transient_toasts", []),
        ]
        seen = set()
        for toast in toasts:
            if toast is None or id(toast) in seen:
                continue
            seen.add(id(toast))
            try:
                if hasattr(toast, "on_activated"):
                    toast.on_activated = None
            except Exception:
                LOGGER.exception("Failed to detach notification callback")
            try:
                toaster.remove_toast(toast)
            except Exception:
                LOGGER.exception("Failed to remove notification during shutdown")
        try:
            toaster.clear_toasts()
        except Exception:
            LOGGER.exception("Failed to clear notifications during shutdown")
        self.session_completion_toast = None
        self.time_shortening_toast = None
        self.monthly_report_toast = None
        self.transient_toasts = []
        self.session_activated_callback = None
        self.toaster = None


class IntegrationSignals(QObject):
    sync_finished = Signal(list, str)
    session_notification_activated = Signal()


class OperationTutorialDialog(QDialog):
    """Four-page first-run tutorial that can also be reopened from Help."""

    def __init__(self, parent=None, allow_skip=False):
        super().__init__(parent)
        self.setWindowTitle("PomodoroOverlay 操作チュートリアル")
        self.setMinimumSize(440, 300)
        base_point_size = self.font().pointSizeF()
        if base_point_size <= 0:
            base_point_size = 9
        self.tutorial_text_point_size = math.ceil(base_point_size * 1.2)
        tutorial_font = QFont(self.font())
        tutorial_font.setPointSize(self.tutorial_text_point_size)
        self.setFont(tutorial_font)
        self.setStyleSheet(
            "QDialog, QWidget { background: #f2f2f2; color: #202020; }"
            "QLabel { background: transparent; color: #202020; }"
            "QPushButton { background: #383838; color: #ffffff; "
            "border: 1px solid #555555; border-radius: 7px; padding: 7px 14px; }"
            "QPushButton:disabled { background: #c8c8c8; color: #707070; "
            "border-color: #aaaaaa; }"
        )

        self.pages = QStackedWidget(self)
        page_specs = (
            (
                "ようこそ",
                "<b>PomodoroOverlay</b>へようこそ。<br><br>"
                "作業と休憩を切り替えながら、集中時間を手軽に管理できます。",
            ),
            (
                "作業タイマー",
                "<b>Work 25m</b>を選び、<b>Start</b>で作業を開始します。<br><br>"
                "<b>Stop</b>で一時停止し、<b>Reset</b>で25:00へ戻せます。",
            ),
            (
                "休憩タイマー",
                "<b>Break 5m</b>を選び、<b>Start</b>で休憩を開始します。<br><br>"
                "作業完了後は<b>Break 5m</b>へ、休憩完了後は<b>Work 25m</b>へ自動で切り替わります。",
            ),
            (
                "設定と実績",
                "<b>⚙ 設定</b>から<b>通知</b>・<b>表示</b>・<b>実績</b>・<b>ヘルプ</b>を確認できます。<br><br>"
                "<b>表示</b>タブでは<b>背景色</b>の色替えや<b>公式スキン</b>を選択できます。<br><br>"
                "<b>連携</b>タブでは<b>Googleカレンダー連携</b>を設定できます。",
            ),
        )
        for heading, body in page_specs:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            heading_label = QLabel(heading)
            heading_font = QFont(heading_label.font())
            heading_font.setPointSize(16)
            heading_font.setBold(True)
            heading_label.setFont(heading_font)
            body_label = QLabel(body)
            body_label.setTextFormat(Qt.RichText)
            body_label.setWordWrap(True)
            body_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            page_layout.addWidget(heading_label)
            page_layout.addSpacing(12)
            page_layout.addWidget(body_label, 1)
            self.pages.addWidget(page)

        self.back_button = QPushButton("Back")
        self.back_button.setObjectName("tutorialBackButton")
        self.next_button = QPushButton("Next")
        self.next_button.setObjectName("tutorialNextButton")
        self.finish_button = QPushButton("Finish")
        self.finish_button.setObjectName("tutorialFinishButton")
        self.skip_button = None
        if allow_skip:
            self.skip_button = QPushButton("Skip")
            self.skip_button.setObjectName("tutorialSkipButton")
            self.skip_button.clicked.connect(self.accept)
        navigation_font = QFont(self.font())
        navigation_font.setBold(True)
        for button in (self.back_button, self.next_button, self.finish_button):
            button.setFont(navigation_font)
        if self.skip_button is not None:
            self.skip_button.setFont(navigation_font)
        self.back_button.clicked.connect(self.previous_page)
        self.next_button.clicked.connect(self.next_page)
        self.finish_button.clicked.connect(self.accept)

        navigation = QHBoxLayout()
        if self.skip_button is not None:
            navigation.addWidget(self.skip_button)
        navigation.addWidget(self.back_button)
        navigation.addStretch(1)
        navigation.addWidget(self.next_button)
        navigation.addWidget(self.finish_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pages, 1)
        layout.addLayout(navigation)
        self._update_navigation()

    def previous_page(self):
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
        self._update_navigation()

    def next_page(self):
        self.pages.setCurrentIndex(
            min(self.pages.count() - 1, self.pages.currentIndex() + 1)
        )
        self._update_navigation()

    def _update_navigation(self):
        index = self.pages.currentIndex()
        last_page = index == self.pages.count() - 1
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(not last_page)
        self.finish_button.setVisible(last_page)


class PomodoroOverlay(QMainWindow):
    COMPACT_SCALE = 2 / 3
    NORMAL_DURATIONS = {"work": 25 * 60, "break": 5 * 60}
    SHORT_DURATIONS = {"work": 25, "break": 5}

    def __init__(self):
        super().__init__()
        self.settings_path = self._get_settings_path()
        self.default_settings = {
            "mode": "work",
            "remaining_seconds": 25 * 60,
            "theme": "dark",
            "window": {"x": 100, "y": 100, "width": 320, "height": 260},
            "geometry": None,
            "general": {
                "always_on_top": True,
                "confirm_full_exit": True,
            },
            "notification_enabled": True,
            "notification_sound_enabled": True,
            "display_scale": 100,
            "background_preset": "cream",
            "skin": "none",
            "operation_tutorial_completed": False,
            "stats_state": {},
            "integration": {},
        }
        self.settings = self.load_settings()
        self.time_shortening_enabled = False
        self.statistics = StatisticsManager(self.settings)
        self.google_calendar = GoogleCalendarClient(
            self.settings_path.parent / "google_calendar_token.json"
        )
        integration = self.settings["integration"]
        if integration["google_calendar_enabled"] and not self.google_calendar.has_credentials():
            integration["google_calendar_enabled"] = False
            integration["google_calendar_account"] = None
        self.integration_signals = IntegrationSignals(self)
        self.integration_signals.sync_finished.connect(self._finish_calendar_sync)
        self.integration_signals.session_notification_activated.connect(
            self._restore_from_session_notification
        )
        self._calendar_sync_running = False
        self._calendar_sync_thread = None
        self._calendar_sync_cancel = threading.Event()
        self._calendar_sync_records = {}
        self._calendar_resync_requested = False
        self._manual_calendar_sync = False
        self._overlay_topmost_suspended = False
        self._active_pending_label = None
        self._calendar_failure_notified = False
        self._monthly_report_waiting = False
        self._pending_yearly_reports = []
        self.current_mode = self.settings.get("mode", "work")
        self.remaining_seconds = int(self.settings.get("remaining_seconds", 25 * 60))
        if self.remaining_seconds <= 0:
            self.remaining_seconds = 25 * 60 if self.current_mode == "work" else 5 * 60
        self.is_running = False
        self.drag_pos = None
        self._is_quitting = False
        self._shutdown_complete = False
        self._settings_dialog = None
        self.notification_service = NotificationService(
            self.integration_signals.session_notification_activated.emit
        )
        self._application_event_filter_installed = False
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
            self._application_event_filter_installed = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self._build_ui()
        self._apply_theme()
        self._restore_window_state()
        self.update_display()
        self.date_check_timer = QTimer(self)
        self.date_check_timer.timeout.connect(self._run_daily_maintenance)
        self.date_check_timer.start(60_000)
        if self.statistics.long_inactivity_reset:
            QTimer.singleShot(0, self._show_long_inactivity_notice)

    def _get_settings_path(self):
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / "PomodoroOverlay" / "pomodoro_settings.json"
        return Path.home() / ".pomodoro_overlay" / "pomodoro_settings.json"

    def load_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.settings_path.exists():
            return self.default_settings.copy()
        try:
            if self.settings_path.stat().st_size > MAX_SETTINGS_FILE_BYTES:
                return self.default_settings.copy()
            with self.settings_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (json.JSONDecodeError, OSError):
            return self.default_settings.copy()
        if not isinstance(data, dict):
            return self.default_settings.copy()
        merged = self.default_settings.copy()
        merged.update(data)
        if data.get("mode") not in self.NORMAL_DURATIONS:
            merged["mode"] = "work"
        mode = merged["mode"]
        remaining_seconds = data.get("remaining_seconds")
        if (
            not isinstance(remaining_seconds, int)
            or isinstance(remaining_seconds, bool)
            or not 1 <= remaining_seconds <= self.NORMAL_DURATIONS[mode]
        ):
            merged["remaining_seconds"] = self.NORMAL_DURATIONS[mode]
        if data.get("theme") != "dark":
            merged["theme"] = "dark"
        if not isinstance(data.get("notification_enabled", True), bool):
            merged["notification_enabled"] = True
        if not isinstance(data.get("notification_sound_enabled", True), bool):
            merged["notification_sound_enabled"] = True
        if data.get("display_scale") not in (100, 110, 120, 130, 140, 150):
            merged["display_scale"] = 100
        if data.get("background_preset") not in BACKGROUND_PRESETS:
            merged["background_preset"] = "cream"
        if data.get("skin", "none") not in (*SKINS.keys(), "none"):
            merged["skin"] = "none"
        if not isinstance(data.get("operation_tutorial_completed", False), bool):
            merged["operation_tutorial_completed"] = False
        geometry = data.get("geometry")
        if not isinstance(geometry, str) or len(geometry) > 4096:
            merged["geometry"] = None
        elif geometry:
            try:
                bytes.fromhex(geometry)
            except ValueError:
                merged["geometry"] = None
        default_window = self.default_settings["window"]
        raw_window = data.get("window")
        clean_window = dict(default_window)
        if isinstance(raw_window, dict):
            limits = {
                "x": (-100_000, 100_000),
                "y": (-100_000, 100_000),
                "width": (160, 4_000),
                "height": (140, 4_000),
            }
            for key, (minimum, maximum) in limits.items():
                value = raw_window.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    if minimum <= value <= maximum:
                        clean_window[key] = value
        merged["window"] = clean_window
        merged["general"] = self.default_settings["general"].copy()
        if isinstance(data.get("general"), dict):
            merged["general"].update(
                {
                    key: value
                    for key, value in data["general"].items()
                    if key in self.default_settings["general"]
                    and isinstance(value, bool)
                }
            )
        return merged

    def save_settings(self):
        payload = dict(self.settings)
        persisted_remaining = self.remaining_seconds
        if self.time_shortening_enabled:
            persisted_remaining = self.NORMAL_DURATIONS[self.current_mode]
        payload.update({
            "mode": self.current_mode,
            "remaining_seconds": persisted_remaining,
            "theme": self.settings.get("theme", "dark"),
            "window": {
                "x": int(self.x()),
                "y": int(self.y()),
                "width": int(self.width()),
                "height": int(self.height()),
            },
            "geometry": self.saveGeometry().data().hex() if self.saveGeometry() else None,
        })
        self.settings.clear()
        self.settings.update(payload)
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self.settings_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
        except OSError:
            pass

    def _build_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self._apply_window_flags(show_after=False)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContentsMargins(0, 0, 0, 0)

        self.central_widget = QWidget(self)
        self.central_widget.setObjectName("centralWidget")
        self.setCentralWidget(self.central_widget)

        self.container = SkinPanel(self.central_widget)
        self.container.setObjectName("overlayContainer")
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        self.close_button = QPushButton("×")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setToolTip("Pomodoro Overlayを終了")
        self.close_button.clicked.connect(self.confirm_full_exit)
        self.close_button.setStyleSheet("font-size: 16px; font-weight: 700; border: none; padding: 0px;")

        self.minimize_button = QPushButton("−")
        self.minimize_button.setFixedSize(28, 28)
        self.minimize_button.setToolTip("最小化")
        self.minimize_button.clicked.connect(self.showMinimized)
        self.minimize_button.setStyleSheet(
            "font-size: 16px; font-weight: 700; border: none; padding: 0px;"
        )

        self.settings_button = QPushButton("⚙")
        self.settings_button.setFixedSize(28, 28)
        self.settings_button.setToolTip("設定")
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.settings_button.setStyleSheet("font-size: 15px; border: none; padding: 0px;")

        title_row = QHBoxLayout()
        title_row.addWidget(self.settings_button)
        title_row.addStretch(1)
        title_row.addWidget(self.minimize_button)
        title_row.addWidget(self.close_button)
        layout.addLayout(title_row)

        self.title_label = QLabel("Pomodoro Overlay")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(self.title_label)

        mode_row = QHBoxLayout()
        self.mode_group = QButtonGroup(self)
        self.work_button = QPushButton("Work 25m")
        self.break_button = QPushButton("Break 5m")
        self.mode_group.addButton(self.work_button, 0)
        self.mode_group.addButton(self.break_button, 1)
        self.mode_group.buttonClicked.connect(self.handle_mode_selection)
        self.work_button.setCheckable(True)
        self.break_button.setCheckable(True)
        self.work_button.setChecked(self.current_mode == "work")
        self.break_button.setChecked(self.current_mode == "break")
        mode_row.addWidget(self.work_button)
        mode_row.addWidget(self.break_button)
        layout.addLayout(mode_row)

        self.timer_panel = QWidget()
        self.timer_panel.setObjectName("timerSurface")
        timer_row = QVBoxLayout(self.timer_panel)
        timer_row.setContentsMargins(6, 5, 6, 5)
        timer_row.setSpacing(6)
        self.timer_label = QLabel("25:00")
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setStyleSheet("font-size: 46px; font-weight: 700; color: #2f1e08;")
        self._update_timer_label_size()
        timer_row.addWidget(self.timer_label)

        self.status_label = QLabel("Ready to focus")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 13px; color: #5c4713;")
        self.status_label.setMinimumHeight(20)
        timer_row.addWidget(self.status_label)
        layout.addWidget(self.timer_panel)

        button_row = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.reset_button = QPushButton("Reset")
        self.start_button.clicked.connect(self.start_timer)
        self.stop_button.clicked.connect(self.stop_timer)
        self.reset_button.clicked.connect(self.reset_timer)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addWidget(self.reset_button)
        layout.addLayout(button_row)

        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        self._install_drag_handlers()
        self._apply_display_scale()

    def _general_setting(self, name):
        general = self.settings.get("general", {})
        return bool(general.get(name, self.default_settings["general"][name]))

    def _set_time_shortening_mode(self, enabled):
        self.time_shortening_enabled = bool(enabled)
        self.stop_timer()
        self.remaining_seconds = self._duration_seconds(self.current_mode)
        self.update_display()
        self.notification_service.notify_time_shortening_mode(
            self.time_shortening_enabled
        )

    def _settings_window_title(self):
        title = f"PomodoroOverlay v{APP_VERSION}"
        if self.time_shortening_enabled:
            title += " 時間短縮モード"
        return title

    def _duration_seconds(self, mode):
        durations = (
            self.SHORT_DURATIONS
            if self.time_shortening_enabled
            else self.NORMAL_DURATIONS
        )
        return durations[mode]

    def _apply_window_flags(self, show_after=True):
        # Qt.Window gives the overlay a normal taskbar button that Windows users
        # can pin. Qt.Tool would intentionally hide it from the taskbar.
        flags = Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint
        if self._general_setting("always_on_top") and not self._overlay_topmost_suspended:
            flags |= Qt.WindowStaysOnTopHint
        was_visible = self.isVisible()
        position = self.pos()
        self.setWindowFlags(flags)
        if show_after and was_visible:
            self.move(position)
            self.show()

    def _apply_display_scale(self):
        try:
            scale_percent = int(self.settings.get("display_scale", 100))
        except (TypeError, ValueError):
            scale_percent = 100
        if scale_percent not in (100, 110, 120, 130, 140, 150):
            scale_percent = 100
        self.settings["display_scale"] = scale_percent
        scale = (scale_percent / 100.0) * self.COMPACT_SCALE
        target_width = round(320 * scale)
        target_height = round(280 * scale)
        self.container.layout().setContentsMargins(*(round(20 * scale),) * 4)
        self.container.layout().setSpacing(round(10 * scale))
        self.close_button.setFixedSize(round(28 * scale), round(28 * scale))
        self.minimize_button.setFixedSize(round(28 * scale), round(28 * scale))
        self.settings_button.setFixedSize(round(28 * scale), round(28 * scale))
        self.setStyleSheet(self._theme_stylesheet(scale))
        self._apply_skin()
        palette = self._background_palette()
        surface_radius = max(8, round(12 * scale))
        self.title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {palette['text']}; "
            f"background: {palette['surface']}; border-radius: {surface_radius}px; "
            f"padding: {max(3, round(5 * scale))}px;"
        )
        self.timer_panel.setStyleSheet(
            f"QWidget#timerSurface {{ background: {palette['surface']}; "
            f"border-radius: {surface_radius}px; }}"
        )
        self.timer_panel.layout().setContentsMargins(
            round(7 * scale), round(5 * scale), round(7 * scale), round(5 * scale)
        )
        timer_font = QFont(self.timer_label.font())
        timer_font.setPixelSize(max(20, round(46 * scale)))
        timer_font.setBold(True)
        self.timer_label.setFont(timer_font)
        self.timer_label.setStyleSheet(f"color: {palette['text']};")

        status_font = QFont(self.status_label.font())
        status_font.setPixelSize(max(10, round(13 * scale)))
        self.status_label.setFont(status_font)
        self.status_label.setStyleSheet(f"color: {palette['text']};")
        self.status_label.setMinimumHeight(round(20 * scale))
        self._update_timer_label_size()
        self.container.layout().invalidate()
        self.container.layout().activate()
        required_height = self.container.sizeHint().height()
        self.setFixedSize(target_width, max(target_height, required_height))

    def open_settings_dialog(self):
        existing_dialog = self._settings_dialog
        if existing_dialog is not None and shiboken6.isValid(existing_dialog):
            existing_dialog.showNormal()
            existing_dialog.raise_()
            existing_dialog.activateWindow()
            return existing_dialog

        # Keep settings as a normal independent window. Making it an owned child
        # of an always-on-top overlay also makes it obstruct external apps on Windows.
        dialog = QDialog()
        self._settings_dialog = dialog
        dialog.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.setWindowTitle(self._settings_window_title())
        dialog.setMinimumWidth(430)
        dialog.setStyleSheet(
            "QDialog, QWidget { background: #f2f2f2; color: #202020; }"
            "QLabel, QCheckBox { color: #202020; background: transparent; }"
            "QTabWidget::pane { border: 1px solid #a8a8a8; background: #f2f2f2; }"
            "QTabBar::tab { background: #d8d8d8; color: #202020; padding: 7px 14px; "
            "border: 1px solid #a8a8a8; border-bottom: none; }"
            "QTabBar::tab:selected { background: #ffffff; }"
            "QComboBox { background: #ffffff; color: #202020; border: 1px solid #999999; "
            "padding: 5px 8px; min-height: 22px; }"
            "QPushButton { background: #383838; color: #ffffff; border: 1px solid #555555; "
            "border-radius: 7px; padding: 7px 14px; }"
            "QPushButton#openGoogleCalendarButton:disabled { background: #c8c8c8; "
            "color: #202020; border-color: #a0a0a0; }"
        )
        tabs = QTabWidget(dialog)

        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        always_on_top = BorderedCheckBox("常に最前面に表示")
        confirm_exit = BorderedCheckBox("完全終了時に確認する")
        time_shortening_mode = None
        if ENABLE_TIME_SHORTENING_MODE:
            time_shortening_mode = BorderedCheckBox("時間短縮モード（Work 25秒 / Break 5秒）")
            time_shortening_mode.setChecked(self.time_shortening_enabled)
        always_on_top.setChecked(self._general_setting("always_on_top"))
        confirm_exit.setChecked(self._general_setting("confirm_full_exit"))
        general_layout.addWidget(always_on_top)
        general_layout.addWidget(confirm_exit)
        general_layout.addStretch(1)
        if time_shortening_mode is not None:
            general_layout.addSpacing(18)
            general_layout.addWidget(time_shortening_mode)
        tabs.addTab(general_tab, "一般")

        notification_tab = QWidget()
        notification_layout = QVBoxLayout(notification_tab)
        notification_enabled = BorderedCheckBox("タイマー完了通知")
        notification_enabled.setChecked(self.settings.get("notification_enabled", True))
        notification_sound_enabled = BorderedCheckBox("通知サウンド")
        notification_sound_enabled.setChecked(
            self.settings.get("notification_sound_enabled", True)
        )
        notification_layout.addWidget(notification_enabled)
        notification_layout.addWidget(notification_sound_enabled)
        notification_help = QLabel(
            "通知が表示されない場合は、Windowsの\n"
            "「設定 → システム → 通知」でPomodoroOverlayの通知を許可してください。"
        )
        notification_help.setWordWrap(True)
        notification_layout.addSpacing(8)
        notification_layout.addWidget(notification_help)
        notification_layout.addStretch(1)
        tabs.addTab(notification_tab, "通知")

        display_tab = QWidget()
        display_layout = QVBoxLayout(display_tab)
        display_form = QFormLayout()
        scale_choice = QComboBox()
        scale_choice.setObjectName("displayScaleChoice")
        for percent in (100, 110, 120, 130, 140, 150):
            scale_choice.addItem(f"{percent}%", percent)
        scale_choice.setCurrentIndex(max(0, scale_choice.findData(self.settings.get("display_scale", 100))))
        display_form.addRow("表示倍率:", scale_choice)

        def apply_scale_preview():
            scale_percent = scale_choice.currentData()
            if scale_percent not in (100, 110, 120, 130, 140, 150):
                return
            position = self.pos()
            self.settings["display_scale"] = scale_percent
            self._apply_display_scale()
            self.move(position)
            self.save_settings()

        scale_choice.currentIndexChanged.connect(apply_scale_preview)
        background_choice = QComboBox()
        background_choice.setObjectName("backgroundPresetChoice")
        for preset_key, preset in BACKGROUND_PRESETS.items():
            background_choice.addItem(preset["label"], preset_key)
        background_choice.setCurrentIndex(
            max(0, background_choice.findData(self.settings.get("background_preset", "cream")))
        )
        display_form.addRow("背景色:", background_choice)

        def apply_background_preview():
            preset_key = background_choice.currentData()
            if preset_key not in BACKGROUND_PRESETS:
                return
            self.settings["background_preset"] = preset_key
            self._apply_background_colors()
            self.save_settings()

        background_choice.currentIndexChanged.connect(apply_background_preview)
        selected_skin = {"key": self.settings.get("skin", "none")}
        original_skin = selected_skin["key"]
        skin_button = QPushButton("スキン")
        skin_button.setObjectName("displaySkinButton")
        skin_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        def choose_skin():
            skin_dialog = SkinSelectionDialog(selected_skin["key"], dialog)
            if skin_dialog.exec() == QDialog.Accepted:
                selected_skin["key"] = skin_dialog.selected_skin
                # Display scaling reapplies the persisted setting, so update it
                # together with the live preview rather than keeping a scale-local value.
                self.settings["skin"] = selected_skin["key"]
                self._apply_skin(selected_skin["key"])

        skin_button.clicked.connect(choose_skin)
        display_form.addRow(skin_button)
        display_layout.addLayout(display_form)
        display_layout.addStretch(1)
        splash_artwork_button = QPushButton("起動スプラッシュのイラストを見る")
        splash_artwork_button.setObjectName("splashArtworkButton")
        splash_artwork_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        splash_artwork_button.clicked.connect(
            lambda: self.show_splash_artwork(dialog)
        )
        display_layout.addWidget(splash_artwork_button)
        tabs.addTab(display_tab, "表示")

        statistics_tab = QWidget()
        statistics_layout = QVBoxLayout(statistics_tab)
        statistics_data = self.settings["stats_state"]["today"]
        statistics_layout.addWidget(
            QLabel(f"ポモドーロ完了数: {statistics_data['pomodoro_completed']}回")
        )
        statistics_layout.addWidget(
            QLabel(f"休憩完了数: {statistics_data['short_break_completed']}回")
        )
        if (
            statistics_data["cheat_pomodoro_completed"]
            or statistics_data["cheat_short_break_completed"]
        ):
            statistics_layout.addSpacing(12)
            statistics_layout.addWidget(
                QLabel(
                    f"ポモドーロ完了数（ズル）: "
                    f"{statistics_data['cheat_pomodoro_completed']}回"
                )
            )
            statistics_layout.addWidget(
                QLabel(
                    f"休憩完了数（ズル）: "
                    f"{statistics_data['cheat_short_break_completed']}回"
                )
            )
        statistics_description = QLabel(
            "Googleカレンダーと連携すると、\n月報・年報を自動で記録できます。"
        )
        statistics_description.setWordWrap(True)
        statistics_layout.addSpacing(8)
        statistics_layout.addWidget(statistics_description)
        statistics_layout.addStretch(1)
        statistics_separator = QFrame()
        statistics_separator.setFrameShape(QFrame.HLine)
        statistics_separator.setFrameShadow(QFrame.Sunken)
        statistics_layout.addWidget(statistics_separator)
        write_calendar_button = QPushButton("カレンダーに書き込み")
        write_calendar_button.setObjectName("writeCalendarButton")
        write_calendar_button.clicked.connect(
            lambda: self._write_calendar(pending_label, dialog)
        )
        statistics_layout.addWidget(write_calendar_button)
        tabs.addTab(statistics_tab, "実績")

        integration_tab = QWidget()
        integration_layout = QVBoxLayout(integration_tab)
        integration = self.settings["integration"]
        connection_text = "連携済み" if integration["google_calendar_enabled"] else "未連携"
        account = integration.get("google_calendar_account")
        connection_label = QLabel(f"連携状態: {connection_text}")
        account_label = QLabel(f"アカウント: {account}") if account else QLabel("")
        pending_label = QLabel(f"未記録: {self.statistics.pending_count()}件")
        integration_description = QLabel(
            "Googleカレンダーと連携すると、\n"
            "前月の月間実績と前年の年間実績を、\n"
            "月・年の変更後に自動で記録します。\n\n"
            "この連携はPomodoroOverlayからGoogleカレンダーへの\n"
            "一方通行です。\n\n"
            "通信状況によって同じ実績が重複して記録される場合があります。\n"
            "重複した予定はGoogleカレンダー上で削除してください。"
        )
        integration_description.setWordWrap(True)
        connect_button = QPushButton("Googleカレンダーと連携")
        disconnect_button = QPushButton("連携を解除")
        open_calendar_button = QPushButton("Googleカレンダーに飛ぶ")
        open_calendar_button.setObjectName("openGoogleCalendarButton")
        open_calendar_button.setEnabled(integration["google_calendar_enabled"])
        connect_button.clicked.connect(
            lambda: self._connect_google_calendar(
                dialog,
                connection_label,
                account_label,
                pending_label,
                open_calendar_button,
            )
        )
        disconnect_button.clicked.connect(
            lambda: self._disconnect_google_calendar(
                dialog, connection_label, account_label, open_calendar_button
            )
        )
        open_calendar_button.clicked.connect(
            lambda: self._open_google_calendar(dialog)
        )
        integration_layout.addWidget(connection_label)
        integration_layout.addWidget(account_label)
        integration_layout.addWidget(pending_label)
        integration_layout.addWidget(integration_description)
        integration_layout.addSpacing(8)
        integration_layout.addWidget(connect_button)
        integration_layout.addWidget(open_calendar_button)
        integration_layout.addWidget(disconnect_button)
        integration_layout.addStretch(1)
        tabs.addTab(integration_tab, "連携")

        help_tab = QWidget()
        help_layout = QVBoxLayout(help_tab)

        tutorial_font = QFont()
        tutorial_font.setBold(True)
        tutorial_text = QLabel("初回起動時の4ページチュートリアルを再表示できます。")
        tutorial_text.setWordWrap(True)
        tutorial_button = QPushButton("操作チュートリアルを開く")
        tutorial_button.clicked.connect(lambda: self.show_operation_tutorial(dialog))

        contact_heading = QLabel("連絡先")
        contact_heading.setFont(tutorial_font)
        contact_text = QLabel("開発者: BOUYA\nX: @xbouyax")
        contact_button = QPushButton("開発者連絡先")
        contact_button.clicked.connect(
            lambda: self._open_external_target(dialog, "https://x.com/xbouyax")
        )

        support_heading = QLabel("開発支援")
        support_heading.setFont(tutorial_font)
        support_text = QLabel(
            "OFUSEからPomodoroOverlayの開発を支援できます。"
        )
        support_text.setWordWrap(True)
        support_button = QPushButton("OFUSEで開発を支援")
        support_button.clicked.connect(
            lambda: self._open_external_target(dialog, "https://ofuse.me/df740631")
        )

        help_layout.addWidget(tutorial_text)
        help_layout.addWidget(tutorial_button)
        help_layout.addSpacing(14)
        help_layout.addWidget(contact_heading)
        help_layout.addWidget(contact_text)
        help_layout.addWidget(contact_button)
        help_layout.addSpacing(14)
        help_layout.addWidget(support_heading)
        help_layout.addWidget(support_text)
        help_layout.addWidget(support_button)
        help_layout.addStretch(1)
        tabs.addTab(help_tab, "ヘルプ")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("キャンセル")
        dialog_layout = QVBoxLayout(dialog)
        dialog_layout.addWidget(tabs)
        dialog_layout.addWidget(buttons)

        committed = {"value": False}

        def save_and_close():
            committed["value"] = True
            self.settings["general"] = {
                "always_on_top": always_on_top.isChecked(),
                "confirm_full_exit": confirm_exit.isChecked(),
            }
            self.settings["notification_enabled"] = notification_enabled.isChecked()
            self.settings["notification_sound_enabled"] = notification_sound_enabled.isChecked()
            self.settings["display_scale"] = scale_choice.currentData()
            self.settings["background_preset"] = background_choice.currentData()
            self.settings["skin"] = selected_skin["key"]
            if time_shortening_mode is not None and (
                time_shortening_mode.isChecked() != self.time_shortening_enabled
            ):
                self._set_time_shortening_mode(time_shortening_mode.isChecked())
            self._apply_window_flags()
            self._apply_display_scale()
            self.save_settings()
            dialog.accept()

        def restore_preview():
            if not committed["value"]:
                self.settings["skin"] = original_skin
                self._apply_skin(original_skin)
                self.save_settings()

        def clear_dialog_reference(*_args):
            if self._settings_dialog is dialog:
                self._settings_dialog = None

        buttons.accepted.connect(save_and_close)
        buttons.rejected.connect(dialog.reject)
        dialog.rejected.connect(restore_preview)
        dialog.finished.connect(clear_dialog_reference)
        dialog.destroyed.connect(clear_dialog_reference)
        dialog.show()
        return dialog

    def show_operation_tutorial(self, parent=None, allow_skip=False):
        tutorial = OperationTutorialDialog(parent or self, allow_skip=allow_skip)
        if tutorial.exec() != QDialog.Accepted:
            return False
        if not self.settings.get("operation_tutorial_completed", False):
            self.settings["operation_tutorial_completed"] = True
            self.save_settings()
        return True

    def show_initial_operation_tutorial(self):
        if self.settings.get("operation_tutorial_completed", False):
            return False
        return self.show_operation_tutorial(self, allow_skip=True)

    def _startup_artwork_path(self):
        manager = getattr(self, "splash_assets", None)
        if manager is not None:
            path = manager.startup_image()
            if path is not None and Path(path).is_file():
                return Path(path)
        bundled = bundled_path("assets/splash_default.png")
        return bundled if bundled.is_file() else None

    def show_splash_artwork(self, parent=None):
        image_path = self._startup_artwork_path()
        if image_path is None:
            return False
        self._overlay_topmost_suspended = True
        self._apply_window_flags()
        viewer = SplashArtworkViewer(image_path, parent or self)
        try:
            viewer.show_on_parent_screen()
        finally:
            self._overlay_topmost_suspended = False
            self._apply_window_flags()
        return True

    def _install_drag_handlers(self):
        self.central_widget.installEventFilter(self)
        self.container.installEventFilter(self)
        for child in self.container.findChildren(QWidget):
            child.installEventFilter(self)

    def _restore_window_state(self):
        window_state = self.settings.get("window")
        if isinstance(window_state, dict):
            x = window_state.get("x")
            y = window_state.get("y")
            width = window_state.get("width")
            height = window_state.get("height")
            if all(value is not None for value in (x, y, width, height)):
                self.setGeometry(int(x), int(y), int(width), int(height))
                return

        if self.settings.get("geometry"):
            try:
                geometry_bytes = bytes.fromhex(self.settings["geometry"])
                self.restoreGeometry(geometry_bytes)
            except ValueError:
                pass

    def _apply_theme(self):
        self.setStyleSheet(
            self._theme_stylesheet(
                (self.settings.get("display_scale", 100) / 100.0) * self.COMPACT_SCALE
            )
        )
        self._apply_display_scale()
        self.work_button.setChecked(self.current_mode == "work")
        self.break_button.setChecked(self.current_mode == "break")

    def _background_palette(self):
        preset_key = self.settings.get("background_preset", "cream")
        return BACKGROUND_PRESETS.get(preset_key, BACKGROUND_PRESETS["cream"])

    @staticmethod
    def _skin_label(skin_key):
        if skin_key == "none":
            return "スキンなし"
        return SKINS.get(skin_key, {}).get("label", "スキンなし")

    def _apply_skin(self, skin_key=None):
        palette = self._background_palette()
        if skin_key is None:
            skin_key = self.settings.get("skin", "none")
        self.container.set_skin(
            skin_asset_path(skin_key), palette["border"]
        )

    def _apply_background_colors(self):
        """Update theme colors without changing geometry, fonts, timer state, or skin."""
        scale = (
            self.settings.get("display_scale", 100) / 100.0
        ) * self.COMPACT_SCALE
        palette = self._background_palette()
        surface_radius = max(8, round(12 * scale))
        self.setStyleSheet(self._theme_stylesheet(scale))
        self.container.set_border_color(palette["border"])
        self.title_label.setStyleSheet(
            f"font-size: 18px; font-weight: 700; color: {palette['text']}; "
            f"background: {palette['surface']}; border-radius: {surface_radius}px; "
            f"padding: {max(3, round(5 * scale))}px;"
        )
        self.timer_panel.setStyleSheet(
            f"QWidget#timerSurface {{ background: {palette['surface']}; "
            f"border-radius: {surface_radius}px; }}"
        )
        self.timer_label.setStyleSheet(f"color: {palette['text']};")
        self.status_label.setStyleSheet(f"color: {palette['text']};")

    def _theme_stylesheet(self, scale=1.0):
        radius = round(10 * scale)
        vertical_padding = round(8 * scale)
        horizontal_padding = round(12 * scale)
        palette = self._background_palette()
        return (
            f"QWidget {{ color: {palette['text']}; background: transparent; }}"
            f"QPushButton {{ background: {palette['button']}; border: 1px solid {palette['button_border']}; border-radius: {radius}px; padding: {vertical_padding}px {horizontal_padding}px; color: #F5F5F5; }}"
            f"QPushButton:hover {{ background: {palette['hover']}; }}"
            f"QPushButton:pressed {{ background: {palette['pressed']}; }}"
            f"QPushButton:checked {{ background: {palette['checked']}; color: #FFFFFF; }}"
            f"QPushButton:disabled {{ background: {palette['disabled']}; color: #FFFFFF; }}"
            f"#overlayContainer {{ background: {palette['background']}; border: 1px solid {palette['border']}; border-radius: 18px; }}"
            f"QLabel {{ color: {palette['text']}; }}"
        )

    def _update_timer_label_size(self):
        metrics = QFontMetrics(self.timer_label.font())
        height = metrics.boundingRect("25:00").height() + 6
        self.timer_label.setMinimumHeight(height)
        self.timer_label.setMaximumHeight(height)

    def handle_mode_selection(self, button):
        if button is self.work_button:
            self.set_mode("work")
        else:
            self.set_mode("break")

    def set_mode(self, mode):
        self._run_daily_maintenance()
        self.current_mode = mode
        self.remaining_seconds = self._duration_seconds(mode)
        self.stop_timer()
        self.update_display()
        self.save_settings()

    def update_display(self):
        minutes, seconds = divmod(self.remaining_seconds, 60)
        self.timer_label.setText(f"{minutes:02d}:{seconds:02d}")
        label_text = "Focus time" if self.current_mode == "work" else "Break time"
        self.status_label.setText(label_text)
        self.work_button.setChecked(self.current_mode == "work")
        self.break_button.setChecked(self.current_mode == "break")

    def start_timer(self):
        self.notification_service.dismiss_session_completion()
        self._run_daily_maintenance()
        if self.is_running:
            return
        self.is_running = True
        self.timer.start(1000)
        self.status_label.setText("Running")

    def _restore_from_session_notification(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def stop_timer(self):
        self._rollover_if_needed()
        self.is_running = False
        self.timer.stop()
        self.status_label.setText("Paused")

    def reset_timer(self):
        self._run_daily_maintenance()
        self.stop_timer()
        self.remaining_seconds = self._duration_seconds(self.current_mode)
        self.update_display()
        self.save_settings()

    def tick(self):
        if self.remaining_seconds > 1:
            self.remaining_seconds -= 1
            self.update_display()
            return
        if self.remaining_seconds == 1:
            self.remaining_seconds = 0

        self.timer.stop()
        self.is_running = False
        completed_mode = self.current_mode
        self.statistics.record_completion(
            completed_mode, cheat=self.time_shortening_enabled
        )
        self.save_settings()
        if self.settings.get("notification_enabled", True):
            self.notification_service.notify_session_completed(
                completed_mode,
                self.settings.get("notification_sound_enabled", True),
            )
        self.current_mode = "break" if self.current_mode == "work" else "work"
        self.remaining_seconds = self._duration_seconds(self.current_mode)
        self.update_display()
        self.save_settings()

    def confirm_full_exit(self):
        if not self._general_setting("confirm_full_exit"):
            self.quit_application()
            return
        dialog = QMessageBox(self)
        dialog.setStyleSheet(
            "QMessageBox { background-color: #202020; }"
            "QMessageBox QLabel { color: #ffffff; background-color: transparent; }"
            "QMessageBox QPushButton { background-color: #383838; color: #ffffff; "
            "border: 1px solid #666666; border-radius: 6px; padding: 6px 14px; }"
        )
        dialog.setWindowTitle("Pomodoro Overlayを終了しますか？")
        dialog.setText("Pomodoro Overlayを完全に終了しますか？")
        exit_button = dialog.addButton("終了", QMessageBox.AcceptRole)
        cancel_button = dialog.addButton("キャンセル", QMessageBox.RejectRole)
        dialog.setDefaultButton(cancel_button)
        dialog.setEscapeButton(cancel_button)
        dialog.exec()
        if dialog.clickedButton() == exit_button:
            self.quit_application()

    def quit_application(self):
        if self._is_quitting:
            return
        self._is_quitting = True
        self.stop_timer()
        self.save_settings()
        self._shutdown_runtime()
        self.close()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def _shutdown_runtime(self):
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        settings_dialog = self._settings_dialog
        self._settings_dialog = None
        if settings_dialog is not None and shiboken6.isValid(settings_dialog):
            settings_dialog.close()
        self.timer.stop()
        self.date_check_timer.stop()
        self._calendar_sync_cancel.set()
        calendar_thread = self._calendar_sync_thread
        if (
            calendar_thread is not None
            and calendar_thread.is_alive()
            and calendar_thread is not threading.current_thread()
        ):
            calendar_thread.join(16)
            if calendar_thread.is_alive():
                LOGGER.error("Calendar sync worker did not stop before shutdown")
        self._calendar_sync_thread = None
        self._calendar_sync_running = False
        if hasattr(self, "splash_assets"):
            self.splash_assets.cancel(wait=True)
        try:
            self.integration_signals.sync_finished.disconnect(
                self._finish_calendar_sync
            )
        except RuntimeError:
            pass
        try:
            self.integration_signals.session_notification_activated.disconnect(
                self._restore_from_session_notification
            )
        except RuntimeError:
            pass
        self.notification_service.shutdown()
        self._remove_application_event_filter()
        lock_socket = getattr(self, "_lock_socket", None)
        if lock_socket is not None:
            try:
                lock_socket.close()
            except OSError:
                LOGGER.exception("Failed to close single-instance socket")
            self._lock_socket = None

    def _remove_application_event_filter(self):
        if not getattr(self, "_application_event_filter_installed", False):
            return
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self)
        self._application_event_filter_installed = False

    def _rollover_if_needed(self):
        if self.statistics.rollover(today_text()):
            self.save_settings()
            return True
        return False

    def _run_daily_maintenance(self):
        if self._is_quitting:
            return
        self._rollover_if_needed()
        integration = self.settings["integration"]
        if integration["google_calendar_enabled"] and self.statistics.pending_count():
            self._start_calendar_sync()

    def _connect_google_calendar(
        self, parent, connection_label, account_label, pending_label, open_calendar_button=None
    ):
        if getattr(sys, "frozen", False):
            credentials_path = Path(sys._MEIPASS) / "oauth" / "google_oauth_client.json"
        else:
            credentials_path = Path(__file__).resolve().parent / "local_credentials" / "google_oauth_client.json"
        if not credentials_path.is_file():
            LOGGER.error("Bundled Google OAuth client configuration is missing")
            self._show_calendar_message(parent, QMessageBox.Warning, "連携できませんでした。")
            return
        self._minimize_for_external_target(parent)
        account = None
        try:
            account = self.google_calendar.connect(str(credentials_path))
        except Exception:
            LOGGER.warning("Google Calendar connection failed")
        finally:
            self._restore_after_external_target(parent)
        if account is None:
            self._show_calendar_message(parent, QMessageBox.Warning, "連携できませんでした。")
            return
        integration = self.settings["integration"]
        integration["google_calendar_enabled"] = True
        integration["google_calendar_account"] = account
        self.save_settings()
        connection_label.setText("連携状態: 連携済み")
        account_label.setText(f"アカウント: {account}")
        if open_calendar_button is not None:
            open_calendar_button.setEnabled(True)
        self._start_calendar_sync(pending_label)

    def _disconnect_google_calendar(
        self, parent, connection_label, account_label, open_calendar_button=None
    ):
        confirmation = QMessageBox(parent)
        self._style_calendar_message_box(confirmation)
        confirmation.setWindowTitle("Googleカレンダー連携")
        confirmation.setText("Googleカレンダーとの連携を解除しますか？")
        disconnect_button = confirmation.addButton("解除", QMessageBox.AcceptRole)
        confirmation.addButton("キャンセル", QMessageBox.RejectRole)
        confirmation.exec()
        if confirmation.clickedButton() is not disconnect_button:
            return
        self.google_calendar.disconnect()
        integration = self.settings["integration"]
        integration["google_calendar_enabled"] = False
        integration["google_calendar_account"] = None
        self.save_settings()
        connection_label.setText("連携状態: 未連携")
        account_label.setText("")
        if open_calendar_button is not None:
            open_calendar_button.setEnabled(False)

    def _write_calendar(self, pending_label=None, settings_dialog=None):
        self._rollover_if_needed()
        self.statistics.enqueue_current_daily_report(today_text())
        self.save_settings()
        self._manual_calendar_sync = True
        if self._calendar_sync_running:
            self._calendar_resync_requested = True
            self._active_pending_label = pending_label
        elif not self._start_calendar_sync(pending_label):
            self._manual_calendar_sync = False
        self._open_google_calendar(settings_dialog)

    @staticmethod
    def _minimize_for_external_target(settings_dialog):
        if settings_dialog is None:
            return
        settings_dialog.showMinimized()
        QApplication.processEvents()

    @staticmethod
    def _restore_after_external_target(settings_dialog):
        if settings_dialog is None:
            return
        settings_dialog.showNormal()
        settings_dialog.raise_()
        settings_dialog.activateWindow()

    def _open_external_target(self, settings_dialog, target):
        self._minimize_for_external_target(settings_dialog)
        try:
            return webbrowser.open(target)
        except Exception:
            LOGGER.exception("Failed to open external target: %s", target)
            return False

    def _open_google_calendar(self, settings_dialog=None):
        return self._open_external_target(
            settings_dialog, "https://calendar.google.com/"
        )

    def _start_calendar_sync(self, pending_label=None):
        integration = self.settings["integration"]
        if (
            self._is_quitting
            or self._calendar_sync_cancel.is_set()
            or self._calendar_sync_running
            or not integration["google_calendar_enabled"]
            or not self.google_calendar.has_credentials()
        ):
            if pending_label is not None:
                pending_label.setText(f"未記録: {self.statistics.pending_count()}件")
            return False
        records = [
            dict(item) for item in self.settings["stats_state"]["pending_reports"]
        ]
        if not records:
            return False
        self._calendar_sync_running = True
        self._calendar_sync_cancel.clear()
        self._calendar_sync_records = {
            record["report_id"]: dict(record) for record in records
        }
        self._active_pending_label = pending_label

        def worker():
            sent_ids = []
            error_text = ""
            for record in records:
                if self._calendar_sync_cancel.is_set():
                    return
                try:
                    self.google_calendar.send_record(record)
                    sent_ids.append(record["report_id"])
                except Exception:
                    LOGGER.warning("Google Calendar record submission failed")
                    error_text = "calendar record submission failed"
                    break
            if not self._calendar_sync_cancel.is_set() and not self._is_quitting:
                self.integration_signals.sync_finished.emit(sent_ids, error_text)

        self._calendar_sync_thread = threading.Thread(
            target=worker, name="PomodoroCalendarSync", daemon=True
        )
        self._calendar_sync_thread.start()
        return True

    @staticmethod
    def _calendar_report_matches(left, right):
        fields = ("report_id", "report_type", "period", *COUNTER_KEYS)
        return all(left.get(field) == right.get(field) for field in fields)

    def _restart_requested_calendar_sync(self):
        if not self._start_calendar_sync():
            self._manual_calendar_sync = False

    def _finish_calendar_sync(self, sent_ids, error_text):
        self._calendar_sync_running = False
        manual_sync = self._manual_calendar_sync
        resync_requested = self._calendar_resync_requested
        self._calendar_resync_requested = False
        sent = set(sent_ids)
        sent_reports = []
        active_records = self._calendar_sync_records
        self._calendar_sync_records = {}
        if sent:
            state = self.settings["stats_state"]
            remaining_reports = []
            for item in state["pending_reports"]:
                report_id = item["report_id"]
                if report_id not in sent:
                    remaining_reports.append(item)
                    continue
                sent_record = active_records.get(report_id)
                if sent_record is not None and not self._calendar_report_matches(
                    item, sent_record
                ):
                    # The report changed while an older snapshot was being sent.
                    remaining_reports.append(item)
                    continue
                sent_reports.append(dict(sent_record or item))
            state["pending_reports"] = remaining_reports
            self.save_settings()
        if self._active_pending_label is not None:
            try:
                self._active_pending_label.setText(
                    f"未記録: {self.statistics.pending_count()}件"
                )
            except RuntimeError:
                pass
        self._active_pending_label = None
        self._notify_completed_reports(sent_reports)
        if resync_requested:
            # A manual write updated the queue while the previous worker was active.
            # Suppress the obsolete result and retry once with the latest snapshot.
            QTimer.singleShot(0, self._restart_requested_calendar_sync)
            return
        self._manual_calendar_sync = False
        if error_text:
            LOGGER.error("Google Calendar sync stopped")
            if not self._calendar_failure_notified:
                self.notification_service.notify_calendar_write(
                    False, self.settings.get("notification_sound_enabled", True)
                )
                self._calendar_failure_notified = True
        else:
            self._calendar_failure_notified = False
        if manual_sync and not sent_reports and not error_text:
            self.notification_service.notify_calendar_write(
                True, self.settings.get("notification_sound_enabled", True)
            )

    def _notify_completed_reports(self, reports):
        if not reports or not self.settings.get("notification_enabled", True):
            return
        sound_enabled = self.settings.get("notification_sound_enabled", True)
        monthly_shown = False
        for report in reports:
            report_type = report.get("report_type")
            if report_type == "daily":
                self.notification_service.notify_daily_report(report, sound_enabled)
            elif report_type == "monthly" and not monthly_shown:
                monthly_shown = self.notification_service.notify_monthly_report(
                    report, sound_enabled
                )
            elif report_type == "yearly":
                self._pending_yearly_reports.append(report)
        if monthly_shown:
            self._monthly_report_waiting = True
        elif self._pending_yearly_reports:
            QTimer.singleShot(0, self._show_next_year_report_dialog)

    def _dismiss_monthly_report_and_continue(self):
        if not self._monthly_report_waiting:
            return
        self._monthly_report_waiting = False
        self.notification_service.dismiss_monthly_report()
        if self._pending_yearly_reports:
            QTimer.singleShot(0, self._show_next_year_report_dialog)

    def _show_next_year_report_dialog(self):
        if self._monthly_report_waiting or not self._pending_yearly_reports:
            return
        report = self._pending_yearly_reports.pop(0)
        year = report["period"]
        dialog = QMessageBox(self)
        self._style_calendar_message_box(dialog)
        dialog.setWindowTitle("年報")
        dialog.setText(f"{year}年の年間実績をGoogleカレンダーへ記録しました。")
        dialog.setIcon(QMessageBox.Information)
        dialog.setStandardButtons(QMessageBox.Close)
        dialog.button(QMessageBox.Close).setText("閉じる")
        dialog.exec()
        self.notification_service.notify_happy_new_year(
            year, self.settings.get("notification_sound_enabled", True)
        )
        if self._pending_yearly_reports:
            QTimer.singleShot(0, self._show_next_year_report_dialog)

    def _show_long_inactivity_notice(self):
        self.save_settings()
        message_box = QMessageBox(self)
        self._style_calendar_message_box(message_box)
        message_box.setWindowTitle("PomodoroOverlay")
        message_box.setIcon(QMessageBox.Information)
        message_box.setText(
            "長期間利用がなかったため、\n古い実績データをリセットしました。\n\n"
            "本日から新しい実績集計を開始します。"
        )
        message_box.exec()

    @staticmethod
    def _style_calendar_message_box(message_box):
        message_box.setStyleSheet(
            "QMessageBox { background-color: #f2f2f2; }"
            "QMessageBox QLabel { color: #202020; background-color: transparent; }"
            "QMessageBox QPushButton { background-color: #383838; color: #ffffff; "
            "border: 1px solid #555555; border-radius: 6px; padding: 6px 14px; }"
        )

    def _show_calendar_message(self, parent, icon, text):
        message_box = QMessageBox(parent)
        self._style_calendar_message_box(message_box)
        message_box.setWindowTitle("Googleカレンダー連携")
        message_box.setIcon(icon)
        message_box.setText(text)
        message_box.exec()

    def quit_app(self):
        self.quit_application()

    def eventFilter(self, obj, event):
        if self._monthly_report_waiting and event.type() in (
            QEvent.MouseButtonPress,
            QEvent.KeyPress,
            QEvent.WindowActivate,
        ):
            widget = obj if isinstance(obj, QWidget) else None
            belongs_to_app = False
            while widget is not None:
                if widget is self:
                    belongs_to_app = True
                    break
                widget = widget.parentWidget()
            if belongs_to_app:
                QTimer.singleShot(0, self._dismiss_monthly_report_and_continue)
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if obj in (self.container, self.central_widget):
                self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()
                return True
        if event.type() == QEvent.MouseMove and self.drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
            return True
        if event.type() == QEvent.MouseButtonRelease:
            self.drag_pos = None
            return False
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        if self._is_quitting:
            self._remove_application_event_filter()
            event.accept()
            return
        event.ignore()
        self.confirm_full_exit()


def ensure_single_instance():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(("127.0.0.1", 58432))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None


def main():
    lock_socket = ensure_single_instance()
    if lock_socket is None:
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    if getattr(sys, "frozen", False):
        bundled_splash = Path(sys._MEIPASS) / "assets" / "splash_default.png"
        app_icon_path = Path(sys._MEIPASS) / "assets" / "app_icon.png"
    else:
        bundled_splash = Path(__file__).resolve().parent / "assets" / "splash_default.png"
        app_icon_path = Path(__file__).resolve().parent / "assets" / "app_icon.png"
    if app_icon_path.is_file():
        app.setWindowIcon(QIcon(str(app_icon_path)))
    local_appdata = os.getenv("LOCALAPPDATA")
    cache_root = (
        Path(local_appdata) / "PomodoroOverlay" / "splash_cache"
        if local_appdata
        else Path.home() / ".pomodoro_overlay" / "splash_cache"
    )
    splash_assets = SplashAssetManager(
        cache_root, bundled_splash, app_version=APP_VERSION
    )
    if splash_assets.needs_initial_preparation():
        preparation = QProgressDialog(
            "最適化中\nこのままお待ちください", "", 0, 0
        )
        preparation.setWindowTitle("PomodoroOverlay")
        preparation.setCancelButton(None)
        preparation.setWindowFlag(Qt.WindowCloseButtonHint, False)
        preparation.setWindowModality(Qt.ApplicationModal)
        preparation.setMinimumDuration(0)
        preparation.setAutoClose(False)
        preparation.setAutoReset(False)
        def prepare_asset():
            splash_assets.prepare_initial_asset()

        worker = threading.Thread(target=prepare_asset, daemon=True)
        worker.start()
        poller = QTimer(preparation)

        def finish_when_ready():
            if not worker.is_alive():
                poller.stop()
                preparation.close()

        poller.timeout.connect(finish_when_ready)
        poller.start(20)
        preparation.exec()
        worker.join()
    splash = SplashWindow(APP_VERSION, splash_assets.startup_image())
    splash_lifetime = SplashLifetime(splash)
    splash.show_centered()
    app.processEvents()
    window = PomodoroOverlay()
    window.splash_assets = splash_assets
    def finish_splash():
        splash_lifetime.close()
        window.show()
        QTimer.singleShot(0, window.show_initial_operation_tutorial)

    QTimer.singleShot(SPLASH_DISPLAY_MS, finish_splash)
    QTimer.singleShot(120_000, splash_assets.start_background_update)
    window._lock_socket = lock_socket
    exit_code = app.exec()
    if not window._shutdown_complete:
        window._is_quitting = True
        window._shutdown_runtime()
        window.close()
    splash_lifetime.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    lock_socket.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
