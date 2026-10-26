"""T6：规则怪谈（结构化规则检查 + 违规/求助指标）。"""
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


class TestRuleChecks(unittest.TestCase):
    def setUp(self):
        self.p = plugin_mod.get_plugin("rules_horror")

    def test_forbidden_words(self):
        rule = {"check": {"type": "forbidden_words", "words": ["血"]}}
        self.assertTrue(self.p._check_one(rule, "地上有血迹"))
        self.assertFalse(self.p._check_one(rule, "地上有水"))

    def test_max_chars(self):
        rule = {"check": {"type": "max_chars", "value": 5}}
        self.assertTrue(self.p._check_one(rule, "一二三四五六"))
        self.assertFalse(self.p._check_one(rule, "一二三"))

    def test_must_speak(self):
        rule = {"check": {"type": "must_speak"}}
        self.assertTrue(self.p._check_one(rule, "   "))
        self.assertFalse(self.p._check_one(rule, "我说一句"))


class TestHorrorRun(unittest.TestCase):
    def _run(self, sid, rounds=3):
        plugin = plugin_mod.get_plugin("rules_horror")

        def fake(conf, messages, **kw):
            user = messages[1]["content"]
            m = re.search(r"你是 (\d+) 号", user)
            seat = int(m.group(1)) if m else 1
            if seat == 1:
                payload = {"kind": "speak", "text": "夜里很安静，我先检查门。"}
            elif seat == 2:
                payload = {"kind": "speak", "text": "走廊上有血迹。"}
            elif seat == 3:
                payload = {"kind": "ask_rule", "rule": 1}
            else:
                payload = {"kind": "speak", "text": "我守在东侧。"}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload)}}]}

        s = runner_mod.create_session(sid, plugin,
                                      {"scenario": "scenarios/rules_horror.yaml",
                                       "rounds": rounds, "max_violations": 2},
                                      _seats(6), "条例测试")
        with mock.patch.object(providers, "call_chat", side_effect=fake):
            th = runner_mod.start(s)
            th.join(timeout=90)
        return s

    def test_metrics_recorded(self):
        s = self._run("t-horror-test")
        m = s.meta.get("metrics") or {}
        self.assertGreaterEqual(m.get("violations", 0), 1, "说禁词的人应记违规")
        self.assertGreater(m.get("help_requests", 0), 0, "求助要被计数")
        self.assertIn("violation_rate", m)
        self.assertIn("survivors", m)

    def test_compliant_seat_has_no_violation(self):
        s = self._run("t-horror-test2")
        viol = s.meta.get("violations") or {}
        self.assertEqual(len(viol.get(1, [])), 0, "合规发言不应记违规")
        self.assertGreater(len(viol.get(2, [])), 0, "说禁词的座位应记违规")

    def test_violation_can_remove_agent(self):
        s = self._run("t-horror-test3", rounds=4)
        viol = s.meta.get("violations") or {}
        maxv = 2
        removed = [seat for seat, items in viol.items() if len(items) >= maxv]
        self.assertTrue(removed, "累计违规达到上限应被带走")
        self.assertNotIn(removed[0], (s.meta.get("alive") or []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
