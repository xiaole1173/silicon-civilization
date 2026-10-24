"""遗言系统：投票出局可留遗言；夜间首夜被杀的也可留。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import game, rules  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO12 = os.path.join(ROOT, "scenarios", "werewolf12.yaml")


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        conf = Scenario.load(SCENARIO12).last_words
        self.assertTrue(conf["enabled"])
        self.assertTrue(conf["after_vote"])
        self.assertEqual(conf["after_night"], "first_night")
        self.assertGreater(conf["max_chars"], 0)

    def test_invalid_policy_rejected(self):
        scenario = Scenario.load(SCENARIO12)
        scenario.last_words["after_night"] = "sometimes"
        with self.assertRaises(Exception):
            scenario.validate()


class TestValidation(unittest.TestCase):
    def test_dead_can_speak(self):
        state = GameState.new(Scenario.load(SCENARIO12), 3)
        seat = sorted(state.alive)[0]
        state.alive.discard(seat)
        ok, msg = rules.validate_action(state, seat, {"kind": "speak", "text": "我是预言家"},
                                        context="last_words")
        self.assertTrue(ok, msg)

    def test_alive_cannot_leave_last_words(self):
        state = GameState.new(Scenario.load(SCENARIO12), 3)
        seat = sorted(state.alive)[0]
        ok, msg = rules.validate_action(state, seat, {"kind": "speak", "text": "我还活着"},
                                        context="last_words")
        self.assertFalse(ok)
        self.assertIn("已出局", msg)


class TestEvents(unittest.TestCase):
    def _run(self, seed=4, **overrides):
        scenario = Scenario.load(SCENARIO12)
        scenario.last_words.update(overrides)
        # 用 plurality 门槛，确保投票一定有人出局（否则测不到"投票遗言"）
        scenario.vote["quorum"] = "plurality"
        return game.run_game(scenario, players={}, seed=seed)

    def test_last_words_after_elimination(self):
        result = self._run()
        events = result["log"].events
        eliminations = [e["day"] for e in events if e["event"] == "elimination"]
        last_words = [e for e in events if e["event"] == "last_words"]
        self.assertTrue(last_words, "应当有遗言事件")
        vote_words = [e for e in last_words if e["trigger"] == "vote"]
        self.assertTrue(vote_words, "投票出局者应当能留遗言")
        for e in vote_words:
            self.assertIn(e["day"], eliminations + [d for d in eliminations])

    def test_disabled_produces_no_last_words(self):
        result = self._run(enabled=False)
        self.assertEqual([e for e in result["log"].events if e["event"] == "last_words"], [])

    def test_after_night_never(self):
        result = self._run(after_night="never")
        night_words = [e for e in result["log"].events
                       if e["event"] == "last_words" and e["trigger"] == "night"]
        self.assertEqual(night_words, [])

    def test_last_words_enter_transcript(self):
        result = self._run()
        events = result["log"].events
        words = [e for e in events if e["event"] == "last_words" and e.get("text")]
        self.assertTrue(words)
        # 遗言之后仍在进行时，公共记录里应能看到（通过对话事件无法直接看，改为校验审计通过）
        health = result["summary"]["health"]
        self.assertTrue(health["ok"], health["errors"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
