"""白痴规则：翻牌免死、失去投票权、屠边计数。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import rules  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STANDARD12 = os.path.join(ROOT, "scenarios", "werewolf12_standard.yaml")


class TestStandardPreset(unittest.TestCase):
    def test_composition_matches_official(self):
        s = Scenario.load(STANDARD12)
        self.assertEqual(s.players, 12)
        self.assertEqual(s.roles["werewolf"], 4)
        self.assertEqual(s.roles["idiot"], 1)
        self.assertEqual(s.roles.get("guard", 0), 0, "标准场不含守卫")
        self.assertEqual(sum(s.roles.values()), 12)

    def test_witch_cannot_self_save_by_default(self):
        self.assertFalse(Scenario.load(STANDARD12).witch["allow_self_save"])

    def test_last_words_first_night_only(self):
        conf = Scenario.load(STANDARD12).last_words
        self.assertEqual(conf["after_night"], "first_night")
        self.assertTrue(conf["after_vote"])


class TestIdiotVote(unittest.TestCase):
    def _state(self, seed=3):
        return GameState.new(Scenario.load(STANDARD12), seed)

    def test_idiot_survives_first_vote(self):
        st = self._state()
        idiot = st.seats_of("idiot")[0]
        outcome = rules.resolve_vote_death(st, idiot)
        self.assertFalse(outcome["died"])
        self.assertTrue(outcome["revealed"])
        self.assertIn(idiot, st.alive, "翻牌后应当还活着")
        self.assertIn(idiot, st.revealed)

    def test_idiot_cannot_vote_after_reveal(self):
        st = self._state()
        idiot = st.seats_of("idiot")[0]
        rules.resolve_vote_death(st, idiot)
        ok, reason = rules.validate_action(st, idiot, {"kind": "vote", "target": 1},
                                           context="day_vote")
        self.assertFalse(ok)
        self.assertIn("投票权", reason)

    def test_non_idiot_dies_on_vote(self):
        st = self._state()
        seat = st.seats_of("villager")[0]
        outcome = rules.resolve_vote_death(st, seat)
        self.assertTrue(outcome["died"])

    def test_idiot_counts_as_god_for_side_elimination(self):
        """屠边：狼杀光神 或 杀光民即胜。白痴算神，所以白痴活着时神职未空。"""
        st = self._state()
        wolves = set(st.seats_of("werewolf"))
        idiot = st.seats_of("idiot")[0]
        villager = st.seats_of("villager")[0]

        # 狼 + 白痴 + 1 民：双方都还有牌 -> 未结束
        st.alive = wolves | {idiot, villager}
        self.assertIsNone(rules.check_win(st))

        # 狼 + 白痴（民被杀光）-> 屠民，狼胜
        st.alive = wolves | {idiot}
        self.assertEqual(rules.check_win(st), "werewolves")

        # 狼 + 1 民（神被杀光，白痴不在场）-> 屠神，狼胜
        st.alive = wolves | {villager}
        self.assertEqual(rules.check_win(st), "werewolves")

        # 白痴 + 1 民（狼被杀光）-> 好人胜
        st.alive = {idiot, villager}
        self.assertEqual(rules.check_win(st), "good")


if __name__ == "__main__":
    unittest.main(verbosity=2)
