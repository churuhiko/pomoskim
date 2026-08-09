import unittest

from version import APP_NAME, APP_VERSION


class VersionMetadataTests(unittest.TestCase):
    def test_preview_version_is_semver_like_and_named(self):
        self.assertEqual(APP_NAME, "Pomodoro Overlay")
        self.assertRegex(APP_VERSION, r"^0\.3\.0-preview\.\d+$")


if __name__ == "__main__":
    unittest.main()

