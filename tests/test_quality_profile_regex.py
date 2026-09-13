"""
Unit tests for Quality Profile Release Title Regex functionality and 44 voiceover presets.
"""
from __future__ import annotations

import re
import unittest
from unittest.mock import MagicMock

from app.constants.voiceover_presets import (
    VOICEOVER_PRESETS,
    VOICEOVER_PRESET_BY_NAME,
    VOICEOVER_PRESET_BY_ID,
    find_preset_by_regex,
)
from app.services.decision_engine import DecisionEngine


class TestQualityProfileRegex(unittest.TestCase):
    def test_all_44_presets_valid_regex(self):
        """Все 44 пресета озвучек должны содержать валидные регулярные выражения."""
        self.assertEqual(len(VOICEOVER_PRESETS), 44)
        for preset in VOICEOVER_PRESETS:
            with self.subTest(preset=preset["name"]):
                try:
                    compiled = re.compile(preset["regex"], re.IGNORECASE)
                    self.assertIsNotNone(compiled)
                except Exception as ex:
                    self.fail(f"Ошибка компиляции regex для {preset['name']}: {ex}")

    def test_presets_match_their_examples(self):
        """Каждый пресет должен успешно сопоставляться со своим примером релиза."""
        for preset in VOICEOVER_PRESETS:
            with self.subTest(preset=preset["name"]):
                matches = bool(re.search(preset["regex"], preset["example"], re.IGNORECASE))
                self.assertTrue(matches, f"Шаблон {preset['name']} не совпал с примером: {preset['example']}")

    def test_find_preset_by_regex(self):
        """Поиск пресета по строке регулярного выражения."""
        hdrezka = VOICEOVER_PRESET_BY_NAME["HDrezka Studio"]
        found = find_preset_by_regex(hdrezka["regex"])
        self.assertIsNotNone(found)
        self.assertEqual(found["name"], "HDrezka Studio")

        # Поиск с пробелами/нормализацией
        found_spaced = find_preset_by_regex(" " + hdrezka["regex"] + " ")
        self.assertIsNotNone(found_spaced)
        self.assertEqual(found_spaced["id"], "hdrezka_studio")

        # Несуществующий regex
        self.assertIsNone(find_preset_by_regex(r"\b(unknown_studio_12345)\b"))
        self.assertIsNone(find_preset_by_regex(None))
        self.assertIsNone(find_preset_by_regex(""))

    def test_decision_engine_rejects_non_matching_regex(self):
        """DecisionEngine отклоняет релизы, не соответствующие release_title_regex профиля."""
        mock_qp = MagicMock()
        mock_qp.name = "HDrezka-1080p"
        mock_qp.allowed_qualities = []  # Разрешены любые качества
        mock_qp.min_size_mb = None
        mock_qp.max_size_mb = None
        mock_qp.upgrade_allowed = True
        mock_qp.cutoff_quality = None
        mock_qp.cutoff_score = 0
        mock_qp.format_items = []
        mock_qp.release_title_regex = r"\b(hdrezka|rezka|хдрезка|резка)\b"

        # 1. Релиз с чужой озвучкой (LostFilm) -> должен быть отклонен
        dec_rejected = DecisionEngine.evaluate_release(
            db=None,
            title="House.of.the.Dragon.S02E01.1080p.LostFilm.mkv",
            quality_profile=mock_qp,
        )
        self.assertFalse(dec_rejected.approved)
        self.assertTrue(any("не соответствует фильтру Regex профиля «HDrezka-1080p»" in r for r in dec_rejected.rejections))

        # 2. Релиз с нужной озвучкой (HDrezka) -> должен быть одобрен
        dec_approved = DecisionEngine.evaluate_release(
            db=None,
            title="House.of.the.Dragon.S02E01.1080p.HDrezka.Studio.mkv",
            quality_profile=mock_qp,
        )
        self.assertTrue(dec_approved.approved, f"Ожидалось одобрение, но отклонено: {dec_approved.rejections}")
        self.assertEqual(len(dec_approved.rejections), 0)

    def test_decision_engine_empty_regex_allows_all(self):
        """DecisionEngine без regex одобряет любые раздачи (стандартное поведение)."""
        mock_qp = MagicMock()
        mock_qp.name = "Standard"
        mock_qp.allowed_qualities = []
        mock_qp.min_size_mb = None
        mock_qp.max_size_mb = None
        mock_qp.upgrade_allowed = True
        mock_qp.cutoff_quality = None
        mock_qp.cutoff_score = 0
        mock_qp.format_items = []
        mock_qp.release_title_regex = None

        dec1 = DecisionEngine.evaluate_release(
            db=None,
            title="Show.S01E01.1080p.BaibaKo.mkv",
            quality_profile=mock_qp,
        )
        self.assertTrue(dec1.approved, f"Ожидалось одобрение, но отклонено: {dec1.rejections}")

        # Пустая строка regex тоже одобряет всё
        mock_qp.release_title_regex = "   "
        dec2 = DecisionEngine.evaluate_release(
            db=None,
            title="Show.S01E01.1080p.LostFilm.mkv",
            quality_profile=mock_qp,
        )
        self.assertTrue(dec2.approved, f"Ожидалось одобрение, но отклонено: {dec2.rejections}")

    def test_decision_engine_anime_voiceovers(self):
        """Проверка фильтрации для аниме озвучек (AniLibria vs AniDUB vs Студийная банда)."""
        mock_qp = MagicMock()
        mock_qp.name = "Anime AniLibria"
        mock_qp.allowed_qualities = []
        mock_qp.min_size_mb = None
        mock_qp.max_size_mb = None
        mock_qp.upgrade_allowed = True
        mock_qp.cutoff_quality = None
        mock_qp.cutoff_score = 0
        mock_qp.format_items = []
        mock_qp.release_title_regex = r"\b(anilibria|анилибрия)\b"

        # Релиз AniLibria -> одобряется
        dec_al = DecisionEngine.evaluate_release(
            db=None,
            title="[AniLibria] Frieren - Beyond Journeys End [01-28 из 28] [WEBRip 1080p]",
            quality_profile=mock_qp,
        )
        self.assertTrue(dec_al.approved, f"Ожидалось одобрение, но отклонено: {dec_al.rejections}")

        # Релиз AniDUB -> отклоняется
        dec_ad = DecisionEngine.evaluate_release(
            db=None,
            title="[AniDUB] Frieren - Beyond Journeys End [01-28 из 28] [WEBRip 1080p]",
            quality_profile=mock_qp,
        )
        self.assertFalse(dec_ad.approved)
        self.assertTrue(any("не соответствует фильтру Regex" in r for r in dec_ad.rejections))

    def test_list_quality_profile_voiceovers_endpoint(self):
        """Эндпоинт list_quality_profile_voiceovers возвращает 44 пресета."""
        try:
            from app.api.operations import list_quality_profile_voiceovers
        except ImportError:
            self.skipTest("fastapi not installed in host runner")

        mock_user = MagicMock()
        res = list_quality_profile_voiceovers(current_user=mock_user)
        self.assertEqual(len(res), 44)
        names = {item["name"] for item in res}
        self.assertIn("HDrezka Studio", names)
        self.assertIn("LostFilm", names)
        self.assertIn("Кубик в кубе", names)
        self.assertIn("AniLibria", names)
        self.assertIn("Студийная банда", names)
        self.assertIn("Crunchyroll", names)


if __name__ == "__main__":
    unittest.main()
