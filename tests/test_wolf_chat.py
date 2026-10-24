"""狼队夜间密聊 + 上下文窗口 + 全文落盘。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import game, rules  # noqa: E402
from engine.prompts import build_messages  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO12 = os.path.join(ROOT, "scenarios", "werewolf12.yaml")


class TestWolfChatConfig(unittest.TestCase):
    def test_defaults_enabled(self):
        s = Scenario.load(SCENARIO12)
        self.assertTrue(s.wolf_discussion["enabled"])
        self.assertEqual(s.wolf_discussion["rounds"], 1)
        self.assertGreater(s.wolf_discussion["max_chars"], 0)

    def test_context_window_unlimited_by_default(self):
        s = Scenario.load(SCENARIO12)
        self.assertEqual(s.speech["include_transcript"], -1)


class TestWolfChatRules(unittest.TestCase):
    def test_wolf_can_speak(self):
        state = GameState.new(Scenario.load(SCENARIO12), 3)
        wolf = state.alive_wolves()[0]
        ok, msg = rules.validate_action(state, wolf, {"kind": "speak", "text": "刀 5 号"},
                                        context="wolf_speak")
        self.assertTrue(ok, msg)

    def test_villager_cannot_speak_in_wolf_chat(self):
        state = GameState.new(Scenario.load(SCENARIO12), 3)
        villager = state.seats_of("villager")[0]
        ok, msg = rules.validate_action(state, villager, {"kind": "speak", "text": "我来了"},
                                        context="wolf_speak")
        self.assertFalse(ok)
        self.assertIn("身份", msg)

    def test_empty_chat_rejected(self):
        state = GameState.new(Scenario.load(SCENARIO12), 3)
        wolf = state.alive_wolves()[0]
        ok, _ = rules.validate_action(state, wolf, {"kind": "speak", "text": "  "},
                                      context="wolf_speak")
        self.assertFalse(ok)


class TestWolfChatInGame(unittest.TestCase):
    def test_chat_events_per_night(self):
        scenario = Scenario.load(SCENARIO12)
        result = game.run_game(scenario, players={}, seed=5)
        events = result["log"].events
        chats = [e for e in events if e["event"] == "action" and e.get("context") == "wolf_speak"]
        wolves = scenario.roles["werewolf"]
        self.assertTrue(chats, "应当有狼队密聊事件")
        # 第一夜：全员存活，密聊条数 = 狼人数 × 轮数
        first_night = [c for c in chats if c["day"] == 1 and c.get("kind") == "speak"]
        self.assertEqual(len(first_night), wolves)  # 默认 1 轮

    def test_chat_only_from_wolves(self):
        scenario = Scenario.load(SCENARIO12)
        result = game.run_game(scenario, players={}, seed=5)
        events = result["log"].events
        layout = {}
        for e in events:
            if e["event"] == "role_layout":
                layout = {int(k): v for k, v in e["seats"].items()}
        for e in events:
            if e["event"] == "action" and e.get("context") == "wolf_speak":
                self.assertEqual(layout.get(e["seat"]), "werewolf", e)

    def test_chat_end_summary_emitted(self):
        scenario = Scenario.load(SCENARIO12)
        result = game.run_game(scenario, players={}, seed=5)
        ends = [e for e in result["log"].events if e["event"] == "wolf_chat_end"]
        self.assertTrue(ends)
        self.assertGreater(ends[0]["messages"], 0)


class TestContextWindow(unittest.TestCase):
    def _view(self, limit: int, n: int = 12) -> dict:
        return {
            "context": "day_speak", "seat": 1, "role": "villager", "day": 3,
            "players": 12, "alive": list(range(1, 13)),
            "transcript": [{"day": 1, "seat": i, "text": "第{}条".format(i)}
                           for i in range(1, n + 1)],
            "transcript_limit": limit, "max_chars": 220,
        }

    def test_unlimited_includes_all(self):
        text = build_messages(self._view(-1))[1]["content"]
        for i in range(1, 13):
            self.assertIn("第{}条".format(i), text)

    def test_limited_keeps_tail_only(self):
        text = build_messages(self._view(3))[1]["content"]
        self.assertNotIn("第1条", text)
        self.assertIn("第12条", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
