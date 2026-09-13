from __future__ import annotations

import re
import unittest
from pathlib import Path


class TestFrontendUrlSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_js = Path("web/js/app.js").read_text(encoding="utf-8")

    def test_background_image_urls_use_central_sanitizer(self):
        unsafe_interpolations = re.findall(
            r"background-image:url\('\$\{(?:show\.poster_url|coll\.poster_url|posterImg|bg|backdropImg|e\.poster_url|p\.poster_url)\}\'\)",
            self.app_js,
        )
        self.assertEqual(unsafe_interpolations, [])
        self.assertGreaterEqual(self.app_js.count("safeBackgroundImageStyle("), 11)

    def test_sanitizer_restricts_protocols_and_encodes_attribute_breakout(self):
        self.assertIn('parsed.protocol !== "http:" && parsed.protocol !== "https:"', self.app_js)
        self.assertIn('.replace(/\'/g, "%27")', self.app_js)
        self.assertIn('.replace(/"/g, "%22")', self.app_js)


if __name__ == "__main__":
    unittest.main()
