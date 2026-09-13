from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "web" / "css" / "style.css"
APP_JS_PATH = ROOT / "web" / "js" / "app.js"
HTML_PATHS = (
    ROOT / "web" / "index.html",
    ROOT / "web" / "api-docs.html",
    ROOT / "web" / "wiki.html",
    ROOT / "web" / "quality-guide.html",
)
GLASS_SOURCES = (STYLE_PATH, *HTML_PATHS[1:])


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def css_rule(source: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", source)
    if match is None:
        raise AssertionError(f"CSS rule not found: {selector}")
    return match.group("body")


class TestFrontendGpuSafety(unittest.TestCase):
    def test_glass_is_off_by_default_and_can_be_restored(self):
        for path in GLASS_SOURCES:
            source = read(path)
            self.assertRegex(source, r":root\s*\{\s*--glass-blur:\s*none;")
            self.assertRegex(
                source,
                r':root\[data-glass="on"\]\s*\{\s*--glass-blur:\s*initial;',
            )

    def test_every_active_backdrop_filter_is_glass_gated(self):
        declaration = re.compile(
            r"(?:-webkit-)?backdrop-filter\s*:\s*(?P<value>[^;]+);"
        )

        for path in GLASS_SOURCES:
            source = re.sub(r"/\*.*?\*/", "", read(path), flags=re.DOTALL)
            values = [match.group("value").strip() for match in declaration.finditer(source)]
            self.assertTrue(values, f"No backdrop-filter declarations found in {path}")

            for value in values:
                value = re.sub(r"\s*!important\s*$", "", value)
                if value == "none":
                    continue
                self.assertRegex(
                    value,
                    r"^var\(--glass-blur,\s*.+\)$",
                    f"Ungated backdrop-filter in {path}: {value}",
                )

    def test_glass_preference_is_applied_before_body_render(self):
        for path in HTML_PATHS:
            source = read(path)
            head = source.split("</head>", 1)[0]
            self.assertIn('localStorage.getItem("aliasarr_glass") || "off"', head)
            self.assertIn('setAttribute("data-glass"', head)

        app_js = read(APP_JS_PATH)
        self.assertIn("function applyGlassMode(mode, isUserAction = false)", app_js)
        self.assertIn('setAttribute("data-glass", m)', app_js)
        self.assertIn('localStorage.setItem("aliasarr_glass", m)', app_js)
        self.assertIn('getElementById("setting-glass")', app_js)

    def test_closed_release_drawer_is_not_rendered(self):
        source = read(STYLE_PATH)
        for selector in (".release-drawer-overlay", ".release-drawer-panel"):
            closed = css_rule(source, selector)
            opened = css_rule(source, f"{selector}.open")
            self.assertRegex(closed, r"visibility:\s*hidden;")
            self.assertRegex(opened, r"visibility:\s*visible;")

    def test_table_row_hover_does_not_animate(self):
        source = read(STYLE_PATH)
        row = css_rule(source, ".glass-table-wrap .data-table tbody tr")
        self.assertRegex(row, r"transition:\s*none;")


if __name__ == "__main__":
    unittest.main()
