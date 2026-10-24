"""警长竞选、狼人自爆、狼王：规则层与插件层。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402
from base import plugin as plugin_mod  # noqa: E402
from base import runner as runner_mod  # noqa: E402
from engine import rules  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

STANDARD = os.path.join(ROOT, "scenarios", "werewolf12_standard.yaml")
WOLFKING = os.path.join(ROOT, "scenarios", "werewolf12_wolfking.yaml")


class TestWeightedTally(unittest.TestCase):
    def test_sheriff_weight_breaks_tie(self):
        # 1 号是警长：A(2号) 得 1.5+1=2.5，B(3号) 得 2 -> A 胜；若不加权则平票
        votes = {1: 2, 2: 2, 3: 3, 4: 3}
        plain = rules.tally_votes(votes)
        self.assertTrue(plain["tie"], "不加权应当平票")
        weighted = rules.tally_votes(votes, {1: 1.5})
        self.assertFalse(weighted["tie"])
        self.assertEqual(weighted["eliminated"], 2)

    def test_weight_value_recorded(self):
        result = rules.tally_votes({1: 2}, {1: 1.5})
        self.assertAlmostEqual(result["tally"][2], 1.5)


class TestWolfKing(unittest.TestCase):
    def _state(self):
        return GameState.new(Scenario.load(WOLFKING), 5)

    def test_wolf_king_counts_as_wolf(self):
        st = self._state()
        king = st.seats_of("wolf_king")[0]
        self.assertIn(king, st.wolf_seats())
        self.assertIn(king, st.alive_wolves())
        self.assertTrue(st.is_wolf(king))

    def test_wolf_king_shoots_when_voted_not_poisoned(self):
        st = self._state()
        king = st.seats_of("wolf_king")[0]
        self.assertTrue(rules.can_wolf_king_shoot(st, king, "vote"))
        self.assertTrue(rules.can_wolf_king_shoot(st, king, "hunter"))
        self.assertFalse(rules.can_wolf_king_shoot(st, king, "poison"))

    def test_normal_wolf_cannot_shoot(self):
        st = self._state()
        wolf = [s for s in st.seats_of("werewolf")][0]
        self.assertFalse(rules.can_wolf_king_shoot(st, wolf, "vote"))

    def test_king_only_preset_composition(self):
        s = Scenario.load(WOLFKING)
        self.assertEqual(s.roles["wolf_king"], 1)
        self.assertEqual(s.roles["werewolf"], 3)
        self.assertEqual(sum(s.roles.values()), 12)


class TestDestructValidation(unittest.TestCase):
    def test_only_wolf_can_destruct(self):
        st = GameState.new(Scenario.load(STANDARD), 3)
        wolf = st.alive_wolves()[0]
        villager = st.seats_of("villager")[0]
        ok, _ = rules.validate_action(st, wolf, {"kind": "destruct"}, context="wolf_destruct")
        self.assertTrue(ok)
        ok2, reason = rules.validate_action(st, villager, {"kind": "destruct"},
                                            context="wolf_destruct")
        self.assertFalse(ok2)
        self.assertIn("狼", reason)

    def test_wolf_king_can_destruct(self):
        st = GameState.new(Scenario.load(WOLFKING), 5)
        king = st.seats_of("wolf_king")[0]
        ok, _ = rules.validate_action(st, king, {"kind": "destruct"}, context="wolf_destruct")
        self.assertTrue(ok)


def _seats(n=12):
    return [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}, "name": "{}号".format(i)}
            for i in range(1, n + 1)]


class TestPluginSheriff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = plugin_mod.get_plugin("werewolf")

    def _session(self, sid, scenario):
        s = runner_mod.create_session(sid, self.plugin,
                                      {"scenario": scenario, "seed": 2}, _seats(), "警长局")
        self.plugin.setup(s)
        return s

    def test_election_elects_top_vote(self):
        s = self._session("t-sheriff", "scenarios/werewolf12_standard.yaml")

        def vote_first(conf, messages, **kw):
            sysmsg, user = messages[0]["content"], messages[1]["content"]
            if "【日间·警长竞选】" in user:
                seat = int(__import__("re").search(r"座位 (\d+)", sysmsg).group(1))
                target = 1 if seat != 1 else 2
                payload = {"kind": "vote", "target": target}
            else:
                payload = {"kind": "pass"}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload)}}]}

        with mock.patch.object(providers, "call_chat", side_effect=vote_first):
            self.plugin._elect_sheriff(s)
        st = s.meta["game"]
        self.assertEqual(st.sheriff, 1, "1 号应高票当选")

    def test_self_destruct_ends_day_and_kills_wolf(self):
        s = self._session("t-sheriff2", "scenarios/werewolf12_standard.yaml")
        st = s.meta["game"]

        def destruct(conf, messages, **kw):
            user = messages[1]["content"]
            payload = {"kind": "destruct"} if "【日间·自爆声明】" in user else {"kind": "pass"}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload)}}]}

        wolves_before = list(st.alive_wolves())
        with mock.patch.object(providers, "call_chat", side_effect=destruct):
            happened = self.plugin._try_self_destruct(s)
        self.assertTrue(happened, "应当发生自爆")
        self.assertEqual(len(st.alive_wolves()), len(wolves_before) - 1)
        texts = " ".join(m.text or "" for m in s.messages)
        self.assertIn("自爆", texts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
