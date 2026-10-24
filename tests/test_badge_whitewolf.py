"""警徽流（警长出局移交）与白狼王（自爆带人）。"""
from __future__ import annotations

import json
import os
import re
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

STANDARD = "scenarios/werewolf12_standard.yaml"
WHITEWOLF = "scenarios/werewolf12_whitewolf.yaml"


def _seats(n=12):
    return [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}, "name": "{}号".format(i)}
            for i in range(1, n + 1)]


class TestWhiteWolfComposition(unittest.TestCase):
    def test_preset(self):
        s = Scenario.load(os.path.join(ROOT, WHITEWOLF))
        self.assertEqual(s.roles["white_wolf_king"], 1)
        self.assertEqual(s.roles["werewolf"], 3)
        self.assertEqual(sum(s.roles.values()), 12)

    def test_counts_as_wolf(self):
        st = GameState.new(Scenario.load(os.path.join(ROOT, WHITEWOLF)), 4)
        king = st.seats_of("white_wolf_king")[0]
        self.assertIn(king, st.wolf_seats())
        self.assertTrue(st.is_wolf(king))


class TestBadgeRules(unittest.TestCase):
    def _state(self):
        st = GameState.new(Scenario.load(os.path.join(ROOT, STANDARD)), 6)
        st.sheriff = sorted(st.alive)[0]
        return st

    def test_only_sheriff_can_pass(self):
        st = self._state()
        other = sorted(st.alive)[1]
        ok, reason = rules.validate_action(st, other, {"kind": "pass_badge", "target": 3},
                                           context="badge")
        self.assertFalse(ok)
        self.assertIn("警长", reason)

    def test_sheriff_passes_to_alive(self):
        st = self._state()
        sheriff = st.sheriff
        target = sorted(st.alive)[2]
        ok, msg = rules.validate_action(st, sheriff, {"kind": "pass_badge", "target": target},
                                        context="badge")
        self.assertTrue(ok, msg)

    def test_cannot_pass_to_self_or_dead(self):
        st = self._state()
        sheriff = st.sheriff
        ok, _ = rules.validate_action(st, sheriff,
                                      {"kind": "pass_badge", "target": sheriff}, context="badge")
        self.assertFalse(ok)
        dead = [s for s in sorted(st.alive) if s != sheriff][0]
        st.alive.discard(dead)
        ok2, _ = rules.validate_action(st, sheriff,
                                       {"kind": "pass_badge", "target": dead}, context="badge")
        self.assertFalse(ok2)


class TestBadgeFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = plugin_mod.get_plugin("werewolf")

    def _session(self, sid="t-badge"):
        s = runner_mod.create_session(sid, self.plugin, {"scenario": STANDARD, "seed": 2},
                                      _seats(), "警徽局")
        self.plugin.setup(s)
        return s

    def test_badge_moves_on_sheriff_death(self):
        s = self._session("t-badge1")
        st = s.meta["game"]
        sheriff = sorted(st.alive)[0]
        st.sheriff = sheriff
        successor = sorted(st.alive)[5]

        def reply(conf, messages, **kw):
            payload = {"kind": "pass_badge", "target": successor}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload)}}]}

        rules.apply_deaths(st, [{"seat": sheriff, "cause": "wolf"}])
        with mock.patch.object(providers, "call_chat", side_effect=reply):
            self.plugin._death_trigger(s, sheriff, "wolf")
        self.assertEqual(st.sheriff, successor)
        self.assertTrue(any("警徽移交" in (m.text or "") for m in s.messages))

    def test_badge_lost_when_destroyed(self):
        s = self._session("t-badge2")
        st = s.meta["game"]
        sheriff = sorted(st.alive)[0]
        st.sheriff = sheriff

        def reply(conf, messages, **kw):
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps({"kind": "destroy"})}}]}

        rules.apply_deaths(st, [{"seat": sheriff, "cause": "vote"}])
        with mock.patch.object(providers, "call_chat", side_effect=reply):
            self.plugin._death_trigger(s, sheriff, "vote")
        self.assertIsNone(st.sheriff)
        self.assertTrue(any("警徽流失" in (m.text or "") for m in s.messages))


class TestWhiteWolfDestruct(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = plugin_mod.get_plugin("werewolf")

    def test_white_wolf_takes_someone_on_destruct(self):
        s = runner_mod.create_session("t-ww", self.plugin, {"scenario": WHITEWOLF, "seed": 3},
                                      _seats(), "白狼王局")
        self.plugin.setup(s)
        st = s.meta["game"]
        king = st.seats_of("white_wolf_king")[0]
        victim = [s2 for s2 in sorted(st.alive) if s2 != king][3]

        def reply(conf, messages, **kw):
            user = messages[1]["content"]
            seat = int(re.search(r"座位 (\d+)", messages[0]["content"]).group(1))
            if "【日间·自爆声明】" in user:
                # 只有白狼王自爆；普通狼人不自爆
                payload = {"kind": "destruct"} if seat == king else {"kind": "pass"}
            elif "【出局·狼王反制】" in user:
                payload = {"kind": "shoot", "target": victim}
            else:
                payload = {"kind": "pass"}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload)}}]}

        with mock.patch.object(providers, "call_chat", side_effect=reply):
            happened = self.plugin._try_self_destruct(s)

        self.assertTrue(happened)
        self.assertNotIn(king, st.alive, "白狼王自爆后应出局")
        self.assertNotIn(victim, st.alive, "被带走的人也应当出局")
        texts = " ".join(m.text or "" for m in s.messages)
        self.assertIn("白狼王", texts)


if __name__ == "__main__":
    unittest.main(verbosity=2)
