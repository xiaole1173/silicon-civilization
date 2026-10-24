"""体检器测试：正常局应通过，人为注入的错误要被抓住。"""
from __future__ import annotations

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import game  # noqa: E402
from engine.monitor import audit, render  # noqa: E402
from engine.scenario import Scenario  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "scenarios", "werewolf.yaml")


def normal_events(seed: int = 4) -> list:
    scenario = Scenario.load(SCENARIO)
    return game.run_game(scenario, players={}, seed=seed)["log"].events


class TestCleanGame(unittest.TestCase):
    def test_normal_game_passes(self):
        report = audit(normal_events())
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["stats"]["players"], 9)
        self.assertGreater(report["stats"]["actions"], 0)

    def test_render_contains_verdict(self):
        text = render(audit(normal_events()))
        self.assertIn("体检结论", text)


class TestDetectsProblems(unittest.TestCase):
    def test_seq_gap(self):
        events = copy.deepcopy(normal_events())
        events[5]["seq"] = 999
        report = audit(events)
        self.assertFalse(report["ok"])
        self.assertTrue(any("序号" in e for e in report["errors"]))

    def test_duplicate_death(self):
        events = copy.deepcopy(normal_events())
        # 找一条夜杀事件，人为把同一个人再杀一次
        idx = next(i for i, e in enumerate(events) if e["event"] == "night_resolve"
                   and e.get("deaths"))
        victim = events[idx]["deaths"][0]["seat"]
        events.insert(idx + 1, {"seq": 0, "event": "elimination", "day": events[idx]["day"],
                                "seat": victim, "role": "villager"})
        for i, e in enumerate(events, start=1):
            e["seq"] = i
        report = audit(events)
        self.assertFalse(report["ok"])
        self.assertTrue(any("重复死亡" in e for e in report["errors"]), report["errors"])

    def test_winner_mismatch(self):
        events = copy.deepcopy(normal_events())
        events[-1]["winner"] = "good" if events[-1].get("winner") != "good" else "werewolves"
        report = audit(events)
        self.assertFalse(report["ok"])
        self.assertTrue(any("胜负" in e for e in report["errors"]), report["errors"])

    def test_consecutive_guard_detected(self):
        events = [
            {"seq": 1, "event": "run_meta", "seed": 1},
            {"seq": 2, "event": "role_layout", "seats": {"1": "guard", "2": "villager"}},
            {"seq": 3, "event": "guard_action", "day": 1, "seat": 1, "target": 2, "last_night": None},
            {"seq": 4, "event": "guard_action", "day": 2, "seat": 1, "target": 2, "last_night": 2},
        ]
        report = audit(events)
        self.assertFalse(report["ok"])
        self.assertTrue(any("连续" in e for e in report["errors"]))

    def test_empty_events(self):
        report = audit([])
        self.assertFalse(report["ok"])

    def test_unfinished_game_is_info_only(self):
        events = normal_events()[:-1]   # 去掉 game_end
        report = audit(events)
        self.assertTrue(any("尚未结束" in i for i in report["infos"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
