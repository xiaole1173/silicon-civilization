"""基座原语：资源池、指标、实验清单。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from base.manifest import digest, freeze, load, save, verify  # noqa: E402
from base.metrics import (aggregate, cooperation_rate, depletion_round,  # noqa: E402
                          gini, summarize, write_csv)
from base.world import Resource, World  # noqa: E402


def make_world(amount=100, cap=100, rate=0.05, agents=(1, 2, 3)):
    res = Resource(name="fish", amount=amount, cap=cap, regen_rate=rate)
    return World(resources={"fish": res}, agents=list(agents))


class TestWorld(unittest.TestCase):
    def test_extract_reduces_stock_and_records(self):
        w = make_world()
        ev = w.extract(1, "fish", 30, round_no=1)
        self.assertEqual(ev["got"], 30)
        self.assertEqual(w.stock("fish"), 70)
        self.assertEqual(w.totals("fish")[1], 30)

    def test_extract_clipped_when_not_enough(self):
        w = make_world(amount=10)
        ev = w.extract(1, "fish", 50)
        self.assertEqual(ev["got"], 10)
        self.assertTrue(ev["clipped"])
        self.assertEqual(w.stock("fish"), 0)

    def test_regen_ratio_of_cap(self):
        w = make_world(amount=50, cap=100, rate=0.1)
        gained = w.settle(1)["fish"]
        self.assertAlmostEqual(gained, 10.0, places=3)
        self.assertAlmostEqual(w.stock("fish"), 60.0, places=3)

    def test_regen_capped_by_capacity(self):
        w = make_world(amount=99, cap=100, rate=0.5)
        w.settle(1)
        self.assertEqual(w.stock("fish"), 100)

    def test_scarcity(self):
        w = make_world(amount=25, cap=100)
        self.assertAlmostEqual(w.scarcity("fish"), 0.25, places=3)

    def test_invalid_amount_is_zero(self):
        w = make_world()
        ev = w.extract(1, "fish", None)
        self.assertEqual(ev["got"], 0)


class TestMetrics(unittest.TestCase):
    def test_gini_extremes(self):
        self.assertEqual(gini([5, 5, 5, 5]), 0.0)
        self.assertGreater(gini([0, 0, 0, 20]), 0.7)

    def test_cooperation_rate(self):
        events = [{"got": 5}, {"got": 5}, {"got": 50}]
        self.assertAlmostEqual(cooperation_rate(events, fair_share=5), 0.6667, places=3)

    def test_depletion_round(self):
        history = [{"round": 1, "stock": {"fish": 90}},
                   {"round": 2, "stock": {"fish": 40}},
                   {"round": 3, "stock": {"fish": 8}}]
        self.assertEqual(depletion_round(history, "fish", cap=100, threshold=0.1), 3)
        self.assertIsNone(depletion_round(history, "fish", cap=100, threshold=0.05))

    def test_summarize_bundle(self):
        w = make_world(amount=100, agents=(1, 2, 3))
        w.extract(1, "fish", 40, round_no=1)
        w.extract(2, "fish", 10, round_no=1)
        w.extract(3, "fish", 10, round_no=1)
        w.settle(1)
        s = summarize(w, resource="fish", fair_share=33.3, threshold=0.2)
        for key in ("gini", "total_extracted", "cooperation_rate",
                    "depletion_round", "per_agent"):
            self.assertIn(key, s)
        self.assertEqual(s["total_extracted"], 60)

    def test_aggregate_ci(self):
        rows = [{"coop": 0.4}, {"coop": 0.5}, {"coop": 0.6}]
        agg = aggregate(rows, ["coop"])
        self.assertEqual(agg["n"], 3)
        self.assertAlmostEqual(agg["coop"]["mean"], 0.5, places=3)
        self.assertGreater(agg["coop"]["ci95"], 0)

    def test_write_csv(self):
        rows = [{"seed": 1, "gini": 0.2}, {"seed": 2, "gini": 0.3}]
        with tempfile.TemporaryDirectory() as td:
            path = write_csv(os.path.join(td, "index.csv"), rows)
            text = open(path, encoding="utf-8-sig").read()
            self.assertIn("seed", text)
            self.assertEqual(len(text.strip().splitlines()), 3)


class TestManifest(unittest.TestCase):
    def _mk(self, note="baseline"):
        return freeze(plugin="commons", scenario="commons.yaml",
                      config={"regen_rate": 0.05, "agents": 6},
                      seats=["m1", "m2", "m3"],
                      seeds=[1, 2, 3],
                      metrics=["gini", "cooperation_rate"], notes=note)

    def test_digest_stable_and_verified(self):
        a = self._mk()
        b = self._mk()
        self.assertEqual(a["digest"], b["digest"], "同条件应得到同一份清单")
        self.assertTrue(verify(a))

    def test_tamper_detected(self):
        m = self._mk()
        m["config"]["regen_rate"] = 0.5
        self.assertFalse(verify(m), "改了条件必须被发现")

    def test_save_and_load(self):
        m = self._mk()
        with tempfile.TemporaryDirectory() as td:
            path = save(m, td)
            self.assertTrue(os.path.exists(path))
            back = load(path)
            self.assertEqual(back["digest"], m["digest"])
            self.assertTrue(verify(back))


if __name__ == "__main__":
    unittest.main(verbosity=2)
