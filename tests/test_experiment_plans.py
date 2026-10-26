"""实验预设与座位解析（不联网）。"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

spec = importlib.util.spec_from_file_location(
    "run_experiment", os.path.join(ROOT, "scripts", "run_experiment.py"))
rx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rx)


class TestPlans(unittest.TestCase):
    def test_plans_exist(self):
        for name in ("main", "main_hard", "contract", "horror"):
            self.assertIn(name, rx.PLANS)
            self.assertIn("plugin", rx.PLANS[name])
            self.assertIn("sweep", rx.PLANS[name])

    def test_main_plan_shape(self):
        plan = rx.PLANS["main"]
        self.assertEqual(plan["plugin"], "commons")
        self.assertEqual(plan["sweep"]["regen_rate"], [0.02, 0.05, 0.1])
        self.assertEqual(plan["sweep"]["communication"], ["on", "off"])

    def test_hard_plan_mitigates_ceiling(self):
        plan = rx.PLANS["main_hard"]
        self.assertGreater(plan["rounds"], rx.PLANS["main"]["rounds"])
        self.assertLess(plan["per_round_max"], 25)


class TestSeatResolution(unittest.TestCase):
    def test_only_filter(self):
        fake = {"protocol": "chat_completions", "model": "m", "api_base": "x"}
        with mock.patch.object(rx.store, "list_models", return_value=[{"id": "a"}, {"id": "b"}]):
            with mock.patch.object(rx.store, "get_model", return_value=fake):
                seats = rx.resolve_seats(6, "a,b")
        self.assertEqual(len(seats), 2)
        self.assertEqual([s["model_conf"]["model"] for s in seats], ["m", "m"])

    def test_missing_model_skipped(self):
        def get(mid, **kw):
            return None if mid == "bad" else {"protocol": "chat_completions", "model": mid}

        with mock.patch.object(rx.store, "get_model", side_effect=get):
            seats = rx.resolve_seats(3, "ok,bad")
        self.assertEqual(len(seats), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
