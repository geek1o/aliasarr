from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.services.auto_search import evaluate_torrent_file_priority
from app.services.matcher import match_special_episode
from app.services.parser import parse_episode, ParsedRelease


class TestSpecialsInSeasonPacks(unittest.TestCase):
    def test_match_special_episode_with_season_pack_naming(self):
        # Создаем список спецвыпусков (Сезон 0)
        sp1 = SimpleNamespace(id=1, season_number=0, episode_number=1, title="Star Wars Special")
        sp2 = SimpleNamespace(id=2, season_number=0, episode_number=22, title="The Bleepin' Robot Chicken Archie Comics Special")
        sp3 = SimpleNamespace(id=3, season_number=0, episode_number=23, title="Self-Discovery Special")
        specials = [sp1, sp2, sp3]

        # 1. Тест S11E00 с подзаголовком спешла
        fname1 = "Robot.Chicken.S11E00.The.Bleepin.Robot.Chicken.Archie.Comics.Special.mkv"
        parsed1 = parse_episode(fname1)
        matched1 = match_special_episode(fname1, specials, parsed1)
        self.assertIsNotNone(matched1)
        self.assertEqual(matched1.id, 2)
        self.assertEqual(matched1.episode_number, 22)

        # 2. Тест S11E21 с подзаголовком Self-Discovery Special
        fname2 = "Robot.Chicken.S11E21.Self-Discovery.Special.mkv"
        parsed2 = parse_episode(fname2)
        matched2 = match_special_episode(fname2, specials, parsed2)
        self.assertIsNotNone(matched2)
        self.assertEqual(matched2.id, 3)
        self.assertEqual(matched2.episode_number, 23)

    def test_determine_torrent_file_priority_includes_specials(self):
        ep_reg = SimpleNamespace(id=10, show_id=1, season_number=11, episode_number=1, absolute_number=None, status="wanted")
        ep_sp = SimpleNamespace(id=22, show_id=1, season_number=0, episode_number=22, absolute_number=None, title="Archie Comics Special", status="wanted")
        target_episodes = [ep_reg, ep_sp]

        # Обычная серия сезона 11 -> 1
        p_reg = evaluate_torrent_file_priority("Robot.Chicken.S11E01.mkv", 0, target_episodes)
        self.assertEqual(p_reg, 1)

        # Спецэпизод S11E00 -> 1
        p_sp00 = evaluate_torrent_file_priority("Robot.Chicken.S11E00.The.Bleepin.Robot.Chicken.Archie.Comics.Special.mkv", 1, target_episodes)
        self.assertEqual(p_sp00, 1)

        # Спецэпизод S11E21 Special -> 1
        p_sp21 = evaluate_torrent_file_priority("Robot.Chicken.S11E21.Self-Discovery.Special.mkv", 2, target_episodes)
        self.assertEqual(p_sp21, 1)

        # Серия другого сезона без спецвыпуска -> 0
        p_other = evaluate_torrent_file_priority("Robot.Chicken.S05E01.mkv", 3, target_episodes)
        self.assertEqual(p_other, 0)
