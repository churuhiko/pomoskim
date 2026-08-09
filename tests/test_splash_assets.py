import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QImage
from PySide6.QtWidgets import QApplication, QLabel

from splash_assets import (
    OutlinedLabel,
    SplashAssetManager,
    SplashIllustrationLayer,
    SplashTextLayer,
    SplashWindow,
)


class SplashAssetManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def make_png(path, width=320, height=240):
        image = QImage(width, height, QImage.Format_RGB32)
        image.fill(QColor("#f2e8b8"))
        assert image.save(str(path), "PNG")

    def test_startup_prefers_valid_cache_over_bundled_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.png"
            cache = root / "cache"
            cached = cache / "splash_current.png"
            cache.mkdir()
            self.make_png(bundled)
            self.make_png(cached)
            (cache / "asset_state.json").write_text(
                json.dumps({"filename": cached.name}), encoding="utf-8"
            )
            manager = SplashAssetManager(cache, bundled, app_version="0.2.999")
            self.assertEqual(manager.startup_image(), cached)

    def test_invalid_cache_falls_back_to_bundled_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.png"
            cache = root / "cache"
            cache.mkdir()
            self.make_png(bundled)
            (cache / "broken.png").write_text("not an image", encoding="utf-8")
            (cache / "asset_state.json").write_text(
                json.dumps({"filename": "broken.png"}), encoding="utf-8"
            )
            self.assertEqual(SplashAssetManager(cache, bundled).startup_image(), bundled)

    def test_first_launch_prepares_bundled_image_in_local_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / "bundled.png"
            cache = root / "cache"
            self.make_png(bundled, 720, 720)
            manager = SplashAssetManager(cache, bundled, app_version="0.2.999")
            self.assertTrue(manager.needs_initial_preparation())
            self.assertTrue(manager.prepare_initial_asset())
            self.assertFalse(manager.needs_initial_preparation())
            self.assertEqual(manager.startup_image(), cache / "splash_current.png")
            state = json.loads((cache / "asset_state.json").read_text(encoding="utf-8"))
            self.assertTrue(state["asset_id"].startswith("bundled-v0.2.999-"))
            self.assertEqual(state["width"], 720)
            self.assertEqual(state["height"], 720)

            upgraded = SplashAssetManager(cache, bundled, app_version="0.4")
            self.assertTrue(upgraded.needs_initial_preparation())
            self.assertTrue(upgraded.prepare_initial_asset())
            upgraded_state = json.loads(
                (cache / "asset_state.json").read_text(encoding="utf-8")
            )
            self.assertTrue(upgraded_state["asset_id"].startswith("bundled-v0.4-"))

    def test_manifest_rejects_oversize_and_non_https(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = SplashAssetManager(directory, manifest_url="http://example.test/a.json")
            self.assertFalse(manager.start_background_update())
            manifest = {
                "asset_id": "too-large",
                "filename": "splash.png",
                "sha256": "0" * 64,
                "size_bytes": 100,
                "width": 3001,
                "height": 2000,
            }
            with self.assertRaises(ValueError):
                manager._validate_manifest(manifest)

    def test_cancel_waits_for_background_worker_to_stop(self):
        manager = SplashAssetManager(tempfile.gettempdir())
        manager._worker = threading.Thread(
            target=lambda: manager.cancel_event.wait(2), daemon=True
        )
        manager._worker.start()
        self.assertTrue(manager.cancel(wait=True))
        self.assertTrue(manager.cancel_event.is_set())
        self.assertFalse(manager._worker.is_alive())

    def test_verified_download_is_only_used_on_next_manager_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            self.make_png(source, 400, 300)
            payload = source.read_bytes()
            manifest = {
                "asset_id": "splash-test",
                "filename": "splash.png",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "width": 400,
                "height": 300,
            }
            cache = root / "cache"
            manager = SplashAssetManager(cache, manifest_url="https://example.test/manifest.json")
            self.assertIsNone(manager.startup_image())

            def write_download(url, target, declared_size):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)

            with (
                patch.object(manager, "_download_json", return_value=manifest),
                patch.object(manager, "_download_file", side_effect=write_download),
            ):
                manager._update_worker()
            next_launch = SplashAssetManager(cache)
            self.assertEqual(next_launch.startup_image(), cache / "splash_current.png")

    def test_splash_text_is_rendered_by_ui_without_image(self):
        import main

        self.assertEqual(main.SPLASH_DISPLAY_MS, 1000)
        window = SplashWindow("0.2.999")
        labels = [label.text() for label in window.findChildren(QLabel)]
        self.assertIn("v0.2.999", labels)
        outlined = [label.text for label in window.findChildren(OutlinedLabel)]
        self.assertEqual(outlined, ["Pomodoro Overlay", "by BOUYA"])
        self.assertEqual(window.size().width(), 560)
        self.assertEqual(window.size().height(), 680)
        self.assertEqual(len(window.findChildren(SplashIllustrationLayer)), 1)
        self.assertEqual(len(window.findChildren(SplashTextLayer)), 1)
        self.assertFalse(
            window.findChild(SplashTextLayer).testAttribute(Qt.WA_TranslucentBackground)
        )
        self.assertEqual(SplashWindow.side_for_screen(QRect(0, 0, 1920, 1080)), 756)
        self.assertEqual(SplashWindow.side_for_screen(QRect(0, 0, 1280, 720)), 504)
        window.close()

    def test_windows_icon_contains_required_sizes(self):
        icon_path = Path(__file__).resolve().parents[1] / "assets" / "pomodoro_overlay.ico"
        icon = QIcon(str(icon_path))
        self.assertFalse(icon.isNull())
        sizes = {(size.width(), size.height()) for size in icon.availableSizes()}
        self.assertTrue({(16, 16), (32, 32), (48, 48), (256, 256)}.issubset(sizes))

    def test_splash_lifetime_never_reuses_deleted_qobject(self):
        import main
        import shiboken6
        from PySide6.QtCore import QCoreApplication, QEvent

        splash = SplashWindow("0.2.999")
        lifetime = main.SplashLifetime(splash)
        self.assertTrue(lifetime.is_alive)
        self.assertTrue(lifetime.close())
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(lifetime.is_alive)
        self.assertFalse(shiboken6.isValid(splash))
        self.assertFalse(lifetime.close())

    def test_official_skin_assets_are_bundled_by_spec(self):
        root = Path(__file__).resolve().parents[1]
        skin_names = {
            "pop_camouflage_1.png",
            "carbon.png",
            "galaxy_1.png",
            "hairline.png",
            "pop_tile.png",
            "takeda_bishi.png",
            "flower.png",
            "botanical.png",
            "clover.png",
        }
        for skin_name in skin_names:
            with self.subTest(skin_name=skin_name):
                self.assertTrue((root / "assets" / "skins" / skin_name).is_file())
        spec = (root / "PomodoroOverlay.spec").read_text(encoding="utf-8")
        self.assertIn('skin_dir.glob("*.png")', spec)
        self.assertIn('"assets/skins"', spec)


if __name__ == "__main__":
    unittest.main()
