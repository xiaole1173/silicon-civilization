"""T8：LLM judge（质性编码）。"""
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
import base.judge as judge_mod  # noqa: E402

FENCE = chr(96) * 3


def _conf():
    return {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
            "model": "judge-x", "api_key": "x"}


class TestParse(unittest.TestCase):
    def test_parse_plain_array(self):
        raw = json.dumps([{"index": 1, "scores": {"cooperation": 4, "deception": 0.1},
                            "note": "克制"}], ensure_ascii=False)
        out = judge_mod.parse_scores(raw, 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["scores"]["cooperation"], 4.0)

    def test_parse_with_fence_and_prose(self):
        payload = json.dumps([{"index": 1, "scores": {"cooperation": "5"}}])
        raw = "好的，结果如下：" + FENCE + "json" + payload + FENCE + "完成"
        out = judge_mod.parse_scores(raw, 1)
        self.assertEqual(out[0]["scores"]["cooperation"], 5.0)

    def test_parse_garbage_returns_empty(self):
        self.assertEqual(judge_mod.parse_scores("我不知道", 2), [])

    def test_aggregate(self):
        scored = [{"scores": {"cooperation": 4}}, {"scores": {"cooperation": 2}}]
        agg = judge_mod.aggregate(scored, [{"id": "cooperation", "q": ""}])
        self.assertAlmostEqual(agg["cooperation"], 3.0, places=3)
        self.assertEqual(agg["n"], 2)


class TestJudgeCall(unittest.TestCase):
    def test_judge_returns_scores_and_saves(self):
        def fake(conf, messages, **kw):
            content = json.dumps([
                {"index": 1, "scores": {"cooperation": 5, "deception": 0.1,
                                        "rule_following": 5}, "note": "很克制"},
                {"index": 2, "scores": {"cooperation": 1, "deception": 0.8,
                                        "rule_following": 2}, "note": "明显自私"},
            ], ensure_ascii=False)
            return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}

        items = [{"seat": 1, "text": "我只拿一点"}, {"seat": 2, "text": "我全拿走"}]
        with mock.patch.object(providers, "call_chat", side_effect=fake):
            result = judge_mod.judge(_conf(), items, context="公地实验")
        self.assertEqual(len(result["scores"]), 2)
        self.assertEqual(result["scores"][0]["seat"], 1)
        self.assertAlmostEqual(result["aggregate"]["cooperation"], 3.0, places=3)
        path = judge_mod.save(result, "test")
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["aggregate"]["n"], 2)

    def test_build_messages_contains_rubric(self):
        msgs = judge_mod.build_messages([{"seat": 1, "text": "x"}], context="背景")
        text = msgs[1]["content"]
        self.assertIn("cooperation", text)
        self.assertIn("只输出一个 JSON 数组", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)