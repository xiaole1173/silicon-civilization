"""T3：成本金额与报告图表。"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402
import base.report as report_mod  # noqa: E402
from base import batch as batch_mod  # noqa: E402


def _seats(n=3):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


def fake_call(conf, messages, **kw):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": "继续讨论公共资源。"}}]}


class TestSvgChart(unittest.TestCase):
    def test_svg_has_bars_and_labels(self):
        svg = report_mod.svg_chart(
            [{"label": "a", "mean": 1.0, "ci": 0.1},
             {"label": "b", "mean": 2.0, "ci": 0.2}], "标题", "指标")
        self.assertIn("<svg", svg)
        self.assertGreaterEqual(svg.count("<rect"), 2)
        self.assertIn("标题", svg)

    def test_empty_points_returns_empty(self):
        self.assertEqual(report_mod.svg_chart([], "t"), "")


class TestCostAndChart(unittest.TestCase):
    def test_batch_writes_cost_and_chart(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(providers, "call_chat", side_effect=fake_call):
            summary = batch_mod.run_batch(
                "discussion", seats=_seats(3),
                base_config={"rounds": 1, "price_in_per_m": 1.0, "price_out_per_m": 2.0},
                sweep={"communication": ["on", "off"]}, seeds=[1, 2],
                out_root=td, concurrency=2)
            rows = list(csv.DictReader(open(summary["index"], encoding="utf-8-sig")))
            self.assertTrue(all("cost_usd" in r for r in rows))
            self.assertGreater(sum(float(r["cost_usd"]) for r in rows), 0)
            chart = os.path.join(summary["dir"], "chart.svg")
            self.assertTrue(os.path.exists(chart), "两个以上条件时应生成图表")
            md = open(summary["report"], encoding="utf-8").read()
            self.assertIn("chart.svg", md)
            self.assertIn("估算成本合计", md)

    def test_no_price_no_cost_column(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(providers, "call_chat", side_effect=fake_call):
            summary = batch_mod.run_batch(
                "discussion", seats=_seats(3), base_config={"rounds": 1},
                seeds=[1], out_root=td)
            rows = list(csv.DictReader(open(summary["index"], encoding="utf-8-sig")))
            self.assertNotIn("cost_usd", rows[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
