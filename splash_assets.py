import hashlib
import json
import logging
import os
import ssl
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


LOGGER = logging.getLogger("PomodoroOverlay")
SPLASH_MANIFEST_URL = ""  # Set when the GitHub asset location is ready.
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_EDGE = 3000
CHECK_INTERVAL = timedelta(hours=24)
NETWORK_TIMEOUT_SECONDS = 8
ALLOWED_FORMATS = {"png", "jpeg", "jpg", "webp"}
TITLE_FILL_COLOR = "#E8D58A"
TITLE_OUTLINE_COLOR = "#202020"


def utc_now_text():
    return datetime.now(timezone.utc).isoformat()


class OutlinedLabel(QWidget):
    def __init__(self, text, point_size, parent=None):
        super().__init__(parent)
        self.text = text
        self.font = QFont("Segoe UI", point_size, QFont.Bold)
        self.setFixedHeight(round(point_size * 2.0))

    def sizeHint(self):
        return QSize(360, self.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        metrics = painter.fontMetrics() if painter.font() == self.font else None
        painter.setFont(self.font)
        metrics = painter.fontMetrics()
        x = (self.width() - metrics.horizontalAdvance(self.text)) / 2
        y = (self.height() + metrics.ascent() - metrics.descent()) / 2
        path.addText(x, y, self.font, self.text)
        painter.setPen(QColor(TITLE_OUTLINE_COLOR))
        painter.setBrush(QColor(TITLE_FILL_COLOR))
        painter.drawPath(path)


class SplashTextLayer(QWidget):
    """Text-only layer kept independent from illustration decoding/rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 4)
        layout.setSpacing(0)
        layout.addWidget(OutlinedLabel("Pomodoro Overlay", 25))
        credit_label = OutlinedLabel("by BOUYA", 15)
        layout.addWidget(credit_label)


class SplashIllustrationLayer(QLabel):
    """Image-only layer; application text is never composited into the bitmap."""

    def __init__(self, image_path=None, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.source_pixmap = QPixmap(str(image_path)) if image_path else QPixmap()
        self._fit_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_pixmap()

    def _fit_pixmap(self):
        if self.source_pixmap.isNull() or self.width() <= 0 or self.height() <= 0:
            return
        self.setPixmap(
            self.source_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )


class SplashWindow(QWidget):
    def __init__(self, version, image_path=None):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("splashWindow")
        self.setFixedSize(560, 680)
        self.setStyleSheet(
            "#splashWindow { background-color: #FFF9E1; }"
            "#splashWindow QWidget { background-color: transparent; }"
            "#splashWindow QLabel { color: #202020; background-color: transparent; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.text_header = SplashTextLayer()
        self.text_header.setFixedHeight(92)
        self.illustration_layer = SplashIllustrationLayer(image_path)
        self.version_label = QLabel(f"v{version}")
        self.version_label.setObjectName("splashVersion")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setFont(QFont("Segoe UI", 9))
        self.version_label.setStyleSheet("color: #000000;")
        self.version_label.setFixedHeight(28)
        layout.addWidget(self.text_header)
        layout.addWidget(self.illustration_layer)
        layout.addWidget(self.version_label)

    def show_centered(self):
        screen = self.screen()
        if screen is not None:
            side = self.side_for_screen(screen.availableGeometry())
            self.illustration_layer.setFixedSize(side, side)
            self.setFixedSize(side, side + 120)
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())
        self.show()
        self.raise_()

    @staticmethod
    def side_for_screen(available_geometry):
        short_edge = min(available_geometry.width(), available_geometry.height())
        return max(1, round(short_edge * 0.70))


class SplashAssetManager:
    def __init__(
        self, cache_directory, bundled_image=None, manifest_url=None, app_version=""
    ):
        self.cache_directory = Path(cache_directory)
        self.bundled_image = Path(bundled_image) if bundled_image else None
        self.manifest_url = manifest_url if manifest_url is not None else SPLASH_MANIFEST_URL
        self.app_version = str(app_version)
        self.state_path = self.cache_directory / "asset_state.json"
        self.cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._worker = None
        self.bundled_asset_id = self._calculate_bundled_asset_id()

    def startup_image(self):
        state = self._read_state()
        filename = state.get("filename")
        if isinstance(filename, str):
            candidate = self.cache_directory / Path(filename).name
            if candidate.is_file() and self._validate_image(candidate):
                return candidate
        if self.bundled_image and self.bundled_image.is_file():
            return self.bundled_image
        return None

    def needs_initial_preparation(self):
        state = self._read_state()
        expected_asset_id = self.bundled_asset_id
        if expected_asset_id and state.get("asset_id") != expected_asset_id:
            return True
        filename = state.get("filename")
        if not isinstance(filename, str):
            return True
        candidate = self.cache_directory / Path(filename).name
        return not candidate.is_file() or not self._validate_image(candidate)

    def prepare_initial_asset(self):
        """Atomically seed the local cache without changing the supplied artwork."""
        if not self.needs_initial_preparation():
            return True
        if not self.bundled_image or not self.bundled_image.is_file():
            return False
        if not self._validate_image(self.bundled_image):
            LOGGER.error("Bundled splash image is invalid")
            return False
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        suffix = self.bundled_image.suffix.lower()
        temporary = self.cache_directory / f"initial{suffix}.tmp"
        final_name = f"splash_current{suffix}"
        final_path = self.cache_directory / final_name
        try:
            with self.bundled_image.open("rb") as source, temporary.open("wb") as target:
                for chunk in iter(lambda: source.read(64 * 1024), b""):
                    if self.cancel_event.is_set():
                        return False
                    target.write(chunk)
            if not self._validate_image(temporary):
                raise ValueError("Initial splash cache validation failed")
            os.replace(temporary, final_path)
            reader = QImageReader(str(final_path))
            reader.setDecideFormatFromContent(True)
            size = reader.size()
            state = self._read_state()
            state.update(
                {
                    "asset_id": self.bundled_asset_id,
                    "filename": final_name,
                    "sha256": self._sha256(final_path),
                    "width": size.width(),
                    "height": size.height(),
                }
            )
            self._write_json_atomic(self.state_path, state)
            return True
        except Exception:
            LOGGER.exception("Initial splash asset preparation failed")
            return False
        finally:
            if temporary.exists():
                try:
                    temporary.unlink()
                except OSError:
                    LOGGER.warning("Could not remove initial splash temporary file")

    def start_background_update(self):
        if not self.manifest_url or self.cancel_event.is_set():
            return False
        if not self._is_https(self.manifest_url) or not self._check_due():
            return False
        with self._lock:
            if self._worker and self._worker.is_alive():
                return False
            self._worker = threading.Thread(target=self._update_worker, daemon=True)
            self._worker.start()
        return True

    def cancel(self, wait=False, timeout=NETWORK_TIMEOUT_SECONDS + 1):
        self.cancel_event.set()
        worker = self._worker
        if (
            wait
            and worker is not None
            and worker.is_alive()
            and worker is not threading.current_thread()
        ):
            worker.join(timeout)
        return worker is None or not worker.is_alive()

    def _check_due(self):
        value = self._read_state().get("last_checked_at")
        if not isinstance(value, str):
            return True
        try:
            checked = datetime.fromisoformat(value)
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - checked >= CHECK_INTERVAL
        except ValueError:
            return True

    def _update_worker(self):
        state = self._read_state()
        temporary_path = None
        try:
            state["last_checked_at"] = utc_now_text()
            self._write_json_atomic(self.state_path, state)
            manifest = self._download_json(self.manifest_url)
            self._validate_manifest(manifest)
            if manifest["asset_id"] == state.get("asset_id"):
                return
            asset_url = urllib.parse.urljoin(self.manifest_url, manifest["filename"])
            if not self._is_https(asset_url):
                raise ValueError("Splash asset URL must use HTTPS")
            suffix = Path(manifest["filename"]).suffix.lower()
            temporary_path = self.cache_directory / f"download{suffix}.tmp"
            self._download_file(asset_url, temporary_path, manifest["size_bytes"])
            if self.cancel_event.is_set():
                return
            if self._sha256(temporary_path) != manifest["sha256"].lower():
                raise ValueError("Splash asset hash mismatch")
            if not self._validate_image(
                temporary_path, manifest["width"], manifest["height"]
            ):
                raise ValueError("Downloaded splash image is invalid")
            final_name = f"splash_current{suffix}"
            final_path = self.cache_directory / final_name
            os.replace(temporary_path, final_path)
            temporary_path = None
            state.update(
                {
                    "asset_id": manifest["asset_id"],
                    "filename": final_name,
                    "sha256": manifest["sha256"].lower(),
                    "width": manifest["width"],
                    "height": manifest["height"],
                }
            )
            self._write_json_atomic(self.state_path, state)
        except Exception:
            LOGGER.exception("Splash asset update failed")
        finally:
            if temporary_path and temporary_path.exists():
                try:
                    temporary_path.unlink()
                except OSError:
                    LOGGER.warning("Could not remove temporary splash file")

    def _download_json(self, url):
        data = self._download_bytes(url, 256 * 1024)
        value = json.loads(data.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Splash manifest must be a JSON object")
        return value

    def _download_file(self, url, target, declared_size):
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        data = self._download_bytes(url, MAX_DOWNLOAD_BYTES)
        if len(data) != declared_size:
            raise ValueError("Splash asset size mismatch")
        target.write_bytes(data)

    def _download_bytes(self, url, maximum):
        if self.cancel_event.is_set():
            raise RuntimeError("Splash update cancelled")
        request = urllib.request.Request(url, headers={"User-Agent": "PomodoroOverlay"})
        context = ssl.create_default_context()
        with urllib.request.urlopen(
            request, timeout=NETWORK_TIMEOUT_SECONDS, context=context
        ) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > maximum:
                raise ValueError("Splash download exceeds size limit")
            chunks = []
            total = 0
            while True:
                if self.cancel_event.is_set():
                    raise RuntimeError("Splash update cancelled")
                chunk = response.read(min(64 * 1024, maximum + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > maximum:
                    raise ValueError("Splash download exceeds size limit")
            return b"".join(chunks)

    def _validate_manifest(self, value):
        required = {
            "asset_id": str,
            "filename": str,
            "sha256": str,
            "size_bytes": int,
            "width": int,
            "height": int,
        }
        if any(not isinstance(value.get(key), kind) for key, kind in required.items()):
            raise ValueError("Splash manifest fields are invalid")
        suffix = Path(value["filename"]).suffix.lower().lstrip(".")
        if suffix not in ALLOWED_FORMATS:
            raise ValueError("Unsupported splash image format")
        if Path(value["filename"]).name != value["filename"]:
            raise ValueError("Splash filename must not contain a path")
        if not (0 < value["size_bytes"] <= MAX_DOWNLOAD_BYTES):
            raise ValueError("Splash asset size is invalid")
        if not (0 < value["width"] <= MAX_IMAGE_EDGE and 0 < value["height"] <= MAX_IMAGE_EDGE):
            raise ValueError("Splash image dimensions are invalid")
        if len(value["sha256"]) != 64:
            raise ValueError("Splash hash is invalid")

    @staticmethod
    def _validate_image(path, expected_width=None, expected_height=None):
        reader = QImageReader(str(path))
        reader.setDecideFormatFromContent(True)
        image_format = bytes(reader.format()).decode("ascii", errors="ignore").lower()
        if image_format not in ALLOWED_FORMATS or reader.supportsAnimation():
            return False
        size = reader.size()
        if not size.isValid() or size.width() > MAX_IMAGE_EDGE or size.height() > MAX_IMAGE_EDGE:
            return False
        if expected_width is not None and size.width() != expected_width:
            return False
        if expected_height is not None and size.height() != expected_height:
            return False
        return not reader.read().isNull()

    def _read_state(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_json_atomic(self, path, value):
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)

    @staticmethod
    def _sha256(path):
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _calculate_bundled_asset_id(self):
        if not self.bundled_image or not self.bundled_image.is_file():
            return ""
        try:
            digest = self._sha256(self.bundled_image)[:12]
        except OSError:
            return ""
        version = self.app_version or "unversioned"
        return f"bundled-v{version}-{digest}"

    @staticmethod
    def _is_https(url):
        return urllib.parse.urlparse(url).scheme.lower() == "https"
