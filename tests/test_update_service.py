import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from update_service import GitHubUpdateService, version_key


class FakeResponse:
    def __init__(self, body):
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            result = self.body[self.offset:]
            self.offset = len(self.body)
            return result
        result = self.body[self.offset:self.offset + size]
        self.offset += len(result)
        return result


class UpdateServiceTests(unittest.TestCase):
    def test_preview_versions_sort_before_stable_versions(self):
        self.assertLess(version_key("v0.3.0-preview.2"), version_key("v0.3.0"))
        self.assertLess(version_key("v0.3.0-alpha.1"), version_key("v0.3.0-preview.1"))

    def test_check_latest_release_selects_newer_release_asset(self):
        releases = [
            {
                "tag_name": "v0.3.0-preview.3",
                "draft": False,
                "html_url": "https://github.com/example/pomo/releases/tag/v0.3.0-preview.3",
                "assets": [
                    {
                        "name": "PomoSkin.exe",
                        "browser_download_url": "https://github.com/example/pomo/releases/download/v0.3.0-preview.3/PomoSkin.exe",
                    }
                ],
            },
            {
                "tag_name": "v0.3.0-preview.1",
                "draft": False,
                "assets": [],
            },
        ]

        def opener(_request, timeout):
            self.assertEqual(timeout, 5)
            return FakeResponse(json.dumps(releases))

        service = GitHubUpdateService(
            "example/pomo", "0.3.0-preview.2", opener=opener
        )
        release = service.check_latest_release()
        self.assertEqual(release["version"], "v0.3.0-preview.3")
        self.assertEqual(release["asset_name"], "PomoSkin.exe")

    def test_download_asset_verifies_github_digest(self):
        payload = b"fake executable"
        digest = hashlib.sha256(payload).hexdigest()

        def opener(_request, timeout):
            self.assertEqual(timeout, 30)
            return FakeResponse(payload)

        service = GitHubUpdateService("example/pomo", "0.3.0", opener=opener)
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=project_root) as directory:
            path = service.download_asset(
                {
                    "asset_url": "https://github.com/example/pomo/releases/download/v0.4.0/PomoSkin.exe",
                    "asset_digest": f"sha256:{digest}",
                },
                directory,
            )
            self.assertEqual(Path(path).read_bytes(), payload)
            Path(path).unlink()


if __name__ == "__main__":
    unittest.main()
