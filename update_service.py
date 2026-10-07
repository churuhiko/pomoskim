"""Small, dependency-free GitHub Releases updater for the Windows build."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


VERSION_PATTERN = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(alpha|beta|preview)[-.]?(\d+))?",
    re.IGNORECASE,
)


def version_key(version: str) -> tuple[int, int, int, int, int] | None:
    """Return a comparable key; stable releases sort after previews."""

    match = VERSION_PATTERN.match(str(version).strip())
    if not match:
        return None
    major, minor, patch, channel, channel_number = match.groups()
    channel_rank = {"alpha": 0, "beta": 1, "preview": 1}.get(
        (channel or "").lower(), 2
    )
    return (
        int(major),
        int(minor),
        int(patch),
        channel_rank,
        int(channel_number or 0),
    )


class GitHubUpdateService:
    """Find and stage a newer Windows release without third-party packages."""

    API_BASE = "https://api.github.com/repos"
    MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024

    def __init__(
        self,
        repository: str,
        current_version: str,
        asset_names=("PomoSkin.exe", "PomodoroOverlay.exe"),
        opener=None,
    ):
        self.repository = str(repository or "").strip().strip("/")
        self.current_version = str(current_version)
        self.asset_names = tuple(asset_names)
        self._opener = opener or urllib.request.urlopen

    @property
    def is_configured(self):
        return bool(re.fullmatch(r"[^/\s]+/[^/\s]+", self.repository))

    def _request_json(self, url, timeout=5):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "Pomo-Skin-Updater",
            },
        )
        with self._opener(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def check_latest_release(self, timeout=5):
        if not self.is_configured:
            return None
        url = f"{self.API_BASE}/{self.repository}/releases?per_page=20"
        try:
            releases = self._request_json(url, timeout=timeout)
        except (OSError, ValueError, urllib.error.URLError):
            return None
        if not isinstance(releases, list):
            return None

        current_key = version_key(self.current_version)
        candidates = []
        for release in releases:
            if not isinstance(release, dict) or release.get("draft"):
                continue
            tag_name = release.get("tag_name")
            release_key = version_key(tag_name or "")
            if release_key is None:
                continue
            if current_key is not None and release_key <= current_key:
                continue
            assets = release.get("assets")
            if not isinstance(assets, list):
                continue
            asset = next(
                (
                    item
                    for item in assets
                    if isinstance(item, dict)
                    and item.get("name") in self.asset_names
                    and item.get("browser_download_url")
                ),
                None,
            )
            if asset is None:
                continue
            candidates.append((release_key, release, asset))
        if not candidates:
            return None
        _, release, asset = max(candidates, key=lambda item: item[0])
        return {
            "version": release.get("tag_name", ""),
            "url": release.get("html_url", ""),
            "asset_name": asset.get("name", ""),
            "asset_url": asset.get("browser_download_url", ""),
            "asset_digest": asset.get("digest"),
        }

    def download_asset(self, release, directory, timeout=30):
        """Download to a temporary file and verify the optional GitHub digest."""

        asset_url = str((release or {}).get("asset_url", ""))
        if not asset_url.startswith("https://github.com/"):
            raise ValueError("unexpected release asset URL")
        target_directory = Path(directory)
        target_directory.mkdir(parents=True, exist_ok=True)
        temp_path = None
        digest = hashlib.sha256()
        size = 0
        request = urllib.request.Request(
            asset_url,
            headers={
                "Accept": "application/octet-stream",
                "User-Agent": "Pomo-Skin-Updater",
            },
        )
        try:
            with self._opener(request, timeout=timeout) as response:
                with tempfile.NamedTemporaryFile(
                    mode="wb", prefix="pomo-skin-", suffix=".new", dir=target_directory, delete=False
                ) as handle:
                    temp_path = Path(handle.name)
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > self.MAX_DOWNLOAD_BYTES:
                            raise ValueError("release asset is too large")
                        digest.update(chunk)
                        handle.write(chunk)
            expected_digest = str((release or {}).get("asset_digest") or "")
            if expected_digest.startswith("sha256:"):
                expected_digest = expected_digest.removeprefix("sha256:")
            if expected_digest and digest.hexdigest().lower() != expected_digest.lower():
                raise ValueError("release asset digest mismatch")
            return temp_path
        except Exception:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def schedule_windows_replace(downloaded_path, target_path):
        """Replace the running EXE after this process exits and relaunch it."""

        downloaded = Path(downloaded_path).resolve()
        target = Path(target_path).resolve()
        if os.name != "nt":
            raise OSError("automatic replacement is only supported on Windows")
        script = downloaded.with_suffix(".update.cmd")
        quoted_downloaded = str(downloaded).replace('"', '""')
        quoted_target = str(target).replace('"', '""')
        script.write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            "set /a attempts=0\r\n"
            ":replace\r\n"
            f"move /Y \"{quoted_downloaded}\" \"{quoted_target}\" >nul 2>&1\r\n"
            "if not errorlevel 1 goto start\r\n"
            "set /a attempts+=1\r\n"
            "if %attempts% GEQ 15 goto cleanup\r\n"
            "timeout /t 1 /nobreak >nul\r\n"
            "goto replace\r\n"
            ":start\r\n"
            f"start \"\" \"{quoted_target}\"\r\n"
            ":cleanup\r\n"
            f"del /q \"{str(script).replace(chr(34), chr(34) * 2)}\" >nul 2>&1\r\n",
            encoding="mbcs",
        )
        subprocess.Popen(
            ["cmd.exe", "/c", str(script)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )


def current_executable_path():
    if not getattr(sys, "frozen", False):
        return None
    path = Path(sys.executable)
    return path if path.suffix.lower() == ".exe" else None
