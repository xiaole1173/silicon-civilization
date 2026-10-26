"""公地困境插件：资源结算、指标、崩溃判定、world 事件。"""
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


def _seats(n=6):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


class TestRegistration(unittest.TestCase):
    def test_plugin_discovered(self):
        p = plugin_mod.get_plugin("commons")
        self.assertIsNotNone(p)
        self.assertEqual(p.name, "公地困境")
        self.assertIn("regen_rate", p.default_config)


class TestCommonsRun(unittest.TestCase):
    def _run(self, seat_amounts, rounds=3, regen=0.02):
        plugin = plugin_mod.get_plugin("commons")

        def fake(conf, messages, **kw):
            user = messages[1]["content"]
            m = re.search(r"你是 (\d+) 号", user)
            seat = int(m.group(1)) if m else 1
            amount = seat_amounts.get(seat, 5)
            kind = "declare" if "声明" in user else "take"
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(
                                     {"kind": kind, "amount": amount})}}]}

        s = runner_mod.create_session(
            "t-commons-test", plugin,
            {"scenario": "scenarios/commons.yaml", "rounds": rounds, "regen_rate": regen},
            _seats(6), "公地测试")
        with mock.patch.object(providers, "call_chat", side_effect=fake):
            th = runner_mod.start(s)
            th.join(timeout=60)
        return s

    def test_metrics_and_outcome(self):
        s = self._run({1: 20, 2: 20, 3: 20, 4: 5, 5: 5, 6: 5})
        m = s.meta.get("metrics") or {}
        self.assertGreater(m.get("total_extracted", 0), 0)
        self.assertGreater(m.get("gini", 0), 0, "不均时基尼应大于 0")
        self.assertLess(m.get("cooperation_rate", 1), 1, "有人超取时合作率应小于 1")
        out = s.meta.get("outcome") or {}
        self.assertIn("collapsed", out)
        self.assertIn("survived_rounds", out)

    def test_greedy_collapses(self):
        s = self._run({i: 25 for i in range(1, 7)}, rounds=4, regen=0.02)
        out = s.meta.get("outcome") or {}
        self.assertTrue(out.get("collapsed"), "全员贪心时草场应当崩溃")
        self.assertEqual(s.winner, "collapsed")

    def test_cooperative_sustains(self):
        s = self._run({i: 1 for i in range(1, 7)}, rounds=4, regen=0.05)
        out = s.meta.get("outcome") or {}
        self.assertFalse(out.get("collapsed"), "人人少取时不该崩溃")
        self.assertEqual(s.winner, "sustained")

    def test_world_events_persisted(self):
        s = self._run({i: 5 for i in range(1, 7)})
        path = os.path.join(ROOT, "runs", "sessions", "t-commons-test.jsonl")
        self.assertTrue(os.path.exists(path))
        kinds = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    kinds.append(json.loads(line).get("type"))
                except Exception:
                    pass
        self.assertIn("world", kinds, "资源状态必须落盘，供回放台画曲线")
        self.assertIn("round_start", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
