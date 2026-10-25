"""P1：报告生成、清单冻结/比对、成本统计、信息开关与声誉。"""
from __future__ import annotations

import csv
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
import base.manifest as manifest_mod  # noqa: E402
import base.report as report_mod  # noqa: E402
from base import batch as batch_mod  # noqa: E402
from base import plugin as plugin_mod  # noqa: E402
from base import runner as runner_mod  # noqa: E402


def _seats(n=3):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


def fake_call(conf, messages, **kw):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": "我认为应该优先保证公共资源的可持续。"}}]}


class TestManifestFreeze(unittest.TestCase):
    def test_scenario_digest_recorded(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False,
                                         encoding="utf-8") as fh:
            fh.write("name: demo\nplayers: 3\n")
            path = fh.name
        try:
            m = manifest_mod.freeze(plugin="discussion", scenario="demo.yaml",
                                    config={"rounds": 1}, seats=["m1"], seeds=[1],
                                    metrics=["m_utterances"], scenario_path=path)
            self.assertEqual(len(m["scenario_digest"]), 64)
            self.assertTrue(manifest_mod.verify(m))
        finally:
            os.unlink(path)

    def test_compare_detects_config_change(self):
        a = manifest_mod.freeze(plugin="p", scenario="s", config={"rho": 0.05},
                                seats=["m1"], seeds=[1], metrics=["g"])
        b = manifest_mod.freeze(plugin="p", scenario="s", config={"rho": 0.10},
                                seats=["m1"], seeds=[1], metrics=["g"])
        self.assertIn("config", manifest_mod.compare(a, b))
        same = manifest_mod.compare(a, dict(a))
        self.assertEqual(same, [])


class TestReport(unittest.TestCase):
    def _rows(self):
        return [
            {"run_id": "r1", "condition": "comm-on", "seed": 1, "state": "ended",
             "winner": "good", "m_utterances": 10, "tokens_in": 100, "tokens_out": 50,
             "usage_estimated": True},
            {"run_id": "r2", "condition": "comm-on", "seed": 2, "state": "ended",
             "winner": "good", "m_utterances": 12, "tokens_in": 110, "tokens_out": 55,
             "usage_estimated": True},
            {"run_id": "r3", "condition": "comm-off", "seed": 1, "state": "ended",
             "winner": "werewolves", "m_utterances": 3, "tokens_in": 90, "tokens_out": 20,
             "usage_estimated": True},
            {"run_id": "r4", "condition": "comm-off", "seed": 2, "state": "ended",
             "winner": "werewolves", "m_utterances": 4, "tokens_in": 95, "tokens_out": 22,
             "usage_estimated": True},
        ]

    def test_one_liner_picks_extremes(self):
        comps = report_mod.compare(self._rows(), ["m_utterances"])
        text = report_mod.one_liner(comps, "m_utterances", "发言量")
        self.assertIn("comm-off", text)
        self.assertIn("comm-on", text)
        self.assertIn("相差", text)

    def test_report_contains_sections(self):
        md = report_mod.build(self._rows(),
                              {"plugin": "werewolves", "seeds": [1, 2],
                               "digest": "abc1234567", "path": "x/manifest.json"})
        for key in ("# 实验报告", "## 结论", "## 条件对比", "## 成本", "## 复现"):
            self.assertIn(key, md)
        self.assertIn("输入 tokens 合计：395", md)


class TestBatchCostAndReport(unittest.TestCase):
    def test_tokens_and_report_written(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(providers, "call_chat", side_effect=fake_call):
            summary = batch_mod.run_batch(
                "discussion", seats=_seats(3), base_config={"rounds": 1},
                sweep={"communication": ["on", "off"]}, seeds=[1],
                out_root=td, resume=False)
            rows = list(csv.DictReader(open(summary["index"], encoding="utf-8-sig")))
            self.assertTrue(all("tokens_in" in r for r in rows))
            self.assertTrue(all(int(r["tokens_total"]) > 0 for r in rows),
                            "网关不回 usage 时应按字符估算出非零 token")
            self.assertTrue(all(r["usage_estimated"] == "True" for r in rows))
            self.assertTrue(os.path.exists(summary["report"]))
            md = open(summary["report"], encoding="utf-8").read()
            self.assertIn("## 结论", md)


class TestInfoSwitchAndReputation(unittest.TestCase):
    def _session(self, sid, cfg):
        plugin = plugin_mod.get_plugin("discussion")
        s = runner_mod.create_session(sid, plugin, cfg, _seats(3), "开关局")
        plugin.setup(s)
        return s

    def test_public_only_hides_private_channel(self):
        s = self._session("t-vis1", {"rounds": 1, "info_visibility": "public"})
        s.add_channel("wolves", "狼队", subscribers=[1])
        hidden = s.add_message("wolves", 1, text="私下说")
        self.assertFalse(s.visible_to(1, hidden), "public 模式下私密频道不可见")

    def test_self_only_hides_others(self):
        s = self._session("t-vis2", {"rounds": 1, "info_visibility": "self"})
        msg = s.add_message("public", 2, kind="speak", text="我是2号")
        self.assertFalse(s.visible_to(1, msg))
        self.assertTrue(s.visible_to(2, msg))

    def test_reputation_switch(self):
        s = self._session("t-rep1", {"rounds": 1, "show_reputation": "off"})
        s.adjust_reputation(1, 1.5, "合作")
        self.assertEqual(s.reputation_snapshot(), {}, "关闭展示时不对外暴露")

        s2 = self._session("t-rep2", {"rounds": 1, "show_reputation": "on"})
        s2.adjust_reputation(1, 1.5, "合作")
        s2.adjust_reputation(2, -1.0, "搭便车")
        snap = s2.reputation_snapshot()
        self.assertEqual(snap["1"], 1.5)
        self.assertEqual(snap["2"], -1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
