import unittest

from version import APP_NAME, APP_VERSION, GITHUB_REPOSITORY


class VersionMetadataTests(unittest.TestCase):
    def test_preview_version_is_semver_like_and_named(self):
        self.assertEqual(APP_NAME, "Pomo Skin")
        self.assertRegex(APP_VERSION, r"^0\.3\.0-preview\.\d+$")
        self.assertEqual(GITHUB_REPOSITORY, "churuhiko/pomoskim")


if __name__ == "__main__":
    unittest.main()
