"""角色卡、日志字段与权力分析器（文档 v2 承诺的实现）。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402
from base import cards as cards_mod  # noqa: E402
from base import plugin as plugin_mod  # noqa: E402
from base import power  # noqa: E402
from base import runner as runner_mod  # noqa: E402


def _seats(n=3):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions", "api_base": "http://x",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


class TestCards(unittest.TestCase):
    def test_load_and_render(self):
        card = cards_mod.load("cards/c1_director.yaml")
        self.assertTrue(card["version"].startswith("card-"))
        text = cards_mod.render(card)
        self.assertIn("角色卡", text)
        self.assertIn("目标", text)
        self.assertIn("不可违反", text)

    def test_session_receives_card_and_records_version(self):
        plugin = plugin_mod.get_plugin("discussion")
        seats = _seats(2)
        seats[0]["role_card"] = "cards/c1_director.yaml"
        s = runner_mod.create_session("t-card-on", plugin, {"rounds": 1}, seats, "卡测试")
        self.assertIn("角色卡", s.agents[1].persona)
        self.assertTrue(s.agents[1].role_card_version.startswith("card-"))
        self.assertEqual(s.agents[2].role_card_version, "")

    def test_persona_off_disables_card(self):
        plugin = plugin_mod.get_plugin("discussion")
        seats = _seats(2)
        seats[0]["role_card"] = "cards/c1_director.yaml"
        s = runner_mod.create_session("t-card-off", plugin,
                                      {"rounds": 1, "persona": "off"}, seats, "卡关闭")
        self.assertEqual(s.agents[1].persona, "")
        self.assertEqual(s.agents[1].role_card_version, "")


class TestLogFields(unittest.TestCase):
    def test_meta_has_reproduction_fields(self):
        plugin = plugin_mod.get_plugin("discussion")
        s = runner_mod.create_session("t-meta", plugin, {"rounds": 1}, _seats(2), "字段测试")

        def fake(conf, messages, **kw):
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": "好"}}]}

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            msg = s.ask(s.agents[1], "说一句", label="probe")
        meta = msg.meta
        self.assertIn("harness", meta)
        self.assertIn("temperature", meta)
        self.assertIn("max_tokens", meta)
        self.assertIn("role_card_version", meta)


class TestPower(unittest.TestCase):
    def _log(self, path):
        evs = [
            {"type": "meta", "agents": [{"id": 1, "model": "m1"}, {"id": 2, "model": "m2"}]},
            {"type": "round_start", "round": {"id": "r1", "title": "议约"}},
            {"type": "message_start", "message": {"id": "m1", "sender": 1, "text": ""}},
            {"type": "message_end", "id": "m1", "text": "我先说，2号你觉得呢",
             "meta": {"action": {"kind": "propose", "amount": 5}, "round": "r1"}},
            {"type": "message_start", "message": {"id": "m2", "sender": 2, "text": ""}},
            {"type": "message_end", "id": "m2", "text": "行",
             "meta": {"action": {"kind": "accept"}, "round": "r1"}},
            {"type": "message_start", "message": {"id": "m3", "sender": 2, "text": ""}},
            {"type": "message_end", "id": "m3", "text": "我接着说两句，1号",
             "meta": {"action": {"kind": "take", "amount": 3}, "round": "r1"}},
        ]
        with open(path, "w", encoding="utf-8") as fh:
            for e in evs:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")

    def test_metrics(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "s.jsonl")
            self._log(p)
            r = power.analyze(p)
        self.assertEqual(r["seats"], 2)
        self.assertEqual(r["proposals"], 1)
        self.assertEqual(r["accepts"], 1)
        self.assertEqual(r["adoption_rate"], 0.0, "只 1 个附议，未达采纳门槛")
        self.assertGreater(r["speak_concentration"], 0)
        self.assertEqual(r["actions"].get("take"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)