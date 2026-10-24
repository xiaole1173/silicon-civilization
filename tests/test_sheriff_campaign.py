"""警长竞选流程：上警 → 竞选发言 → 退水 → 警下投票 → PK。"""
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


def _seats(n=12):
    return [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}, "name": "{}号".format(i)}
            for i in range(1, n + 1)]


class TestSheriffRules(unittest.TestCase):
    def _state(self):
        st = GameState.new(Scenario.load(os.path.join(ROOT, STANDARD)), 3)
        st.meta["sheriff_candidates"] = [1, 4]
        return st

    def test_only_alive_can_run(self):
        st = self._state()
        ok, _ = rules.validate_action(st, 2, {"kind": "run"}, context="sheriff_run")
        self.assertTrue(ok)

    def test_candidate_cannot_vote(self):
        st = self._state()
        ok, reason = rules.validate_action(st, 1, {"kind": "vote", "target": 4},
                                           context="sheriff_vote")
        self.assertFalse(ok)
        self.assertIn("警上", reason)

    def test_vote_must_target_candidate(self):
        st = self._state()
        ok, reason = rules.validate_action(st, 2, {"kind": "vote", "target": 3},
                                           context="sheriff_vote")
        self.assertFalse(ok)
        self.assertIn("候选人", reason)
        ok2, _ = rules.validate_action(st, 2, {"kind": "vote", "target": 1},
                                       context="sheriff_vote")
        self.assertTrue(ok2)

    def test_withdraw_context(self):
        st = self._state()
        ok, _ = rules.validate_action(st, 1, {"kind": "withdraw"}, context="sheriff_withdraw")
        self.assertTrue(ok)


class TestSheriffFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = plugin_mod.get_plugin("werewolf")

    def _session(self, sid):
        s = runner_mod.create_session(sid, self.plugin, {"scenario": STANDARD, "seed": 4},
                                      _seats(), "竞选局")
        self.plugin.setup(s)
        return s

    def _run(self, s, run_seats, votes_for, withdraw=()):
        def reply(conf, messages, **kw):
            user = messages[1]["content"]
            seat = int(re.search(r"座位 (\d+)", messages[0]["content"]).group(1))
            if "【日间·上警】" in user:
                payload = {"kind": "run"} if seat in run_seats else {"kind": "pass"}
            elif "【日间·竞选发言】" in user:
                payload = {"kind": "speak", "text": "我是{}号，我上警".format(seat)}
            elif "【日间·退水】" in user:
                payload = {"kind": "withdraw"} if seat in withdraw else {"kind": "stay"}
            elif "【日间·警长投票】" in user:
                target = votes_for.get(seat, 1)
                payload = {"kind": "vote", "target": target}
            else:
                payload = {"kind": "pass"}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload, ensure_ascii=False)}}]}
        with mock.patch.object(providers, "call_chat", side_effect=reply):
            self.plugin._elect_sheriff(s)

    def test_full_campaign_elects_candidate(self):
        s = self._session("t-camp1")
        st = s.meta["game"]
        # 1、4 上警；警下都投 1
        self._run(s, run_seats={1, 4}, votes_for={s2: 1 for s2 in st.alive})
        self.assertEqual(st.sheriff, 1)
        texts = " ".join(m.text or "" for m in s.messages)
        self.assertIn("上警", texts)
        self.assertIn("当选警长", texts)

    def test_no_candidate_means_no_sheriff(self):
        s = self._session("t-camp2")
        st = s.meta["game"]
        self._run(s, run_seats=set(), votes_for={})
        self.assertIsNone(st.sheriff)

    def test_all_withdraw_means_no_sheriff(self):
        s = self._session("t-camp3")
        st = s.meta["game"]
        self._run(s, run_seats={1}, votes_for={}, withdraw={1})
        self.assertIsNone(st.sheriff)

    def test_single_candidate_wins_without_vote(self):
        s = self._session("t-camp4")
        st = s.meta["game"]
        self._run(s, run_seats={5}, votes_for={})
        self.assertEqual(st.sheriff, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
