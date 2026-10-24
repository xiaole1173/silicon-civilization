"""预算与兜底：思考闸门已撤，只保留单一输出预算 + 4 分钟回合上限。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

import providers  # noqa: E402
from engine import game  # noqa: E402
from engine.events import EventLog  # noqa: E402
from engine.players import LLMPlayer  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "scenarios", "werewolf.yaml")


def player():
    conf = {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
            "model": "m", "api_key": "sk-x", "temperature": 0.0, "max_tokens": 8192}
    return LLMPlayer(1, "villager", conf)


def ok_resp(content="{\"kind\": \"pass\"}"):
    return {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}


class TestNoThinkingGate(unittest.TestCase):
    def test_no_thinking_cap_passed(self):
        p = player()
        seen = {}

        def fake(conf, messages, **kw):
            seen.update(kw)
            return ok_resp()

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            p.act({"context": "day_vote", "seat": 1, "role": "villager", "day": 1,
                   "players": 9, "alive": [1, 2, 3], "budget": 2048}, None)
        self.assertIsNone(seen.get("thinking_cap"), "不应再传思考闸门")

    def test_budget_used_as_max_tokens(self):
        p = player()
        seen = {}

        def fake(conf, messages, **kw):
            seen.update(kw)
            return ok_resp()

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            p.act({"context": "day_speak", "seat": 1, "role": "villager", "day": 1,
                   "players": 9, "alive": [1, 2, 3], "budget": 8192}, None)
        self.assertEqual(seen.get("max_tokens"), 8192)

    def test_legacy_dict_budget_still_works(self):
        p = player()
        seen = {}

        def fake(conf, messages, **kw):
            seen.update(kw)
            return ok_resp()

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            p.act({"context": "day_vote", "seat": 1, "role": "villager", "day": 1,
                   "players": 9, "alive": [1, 2, 3],
                   "budget": {"thinking": 800, "answer": 512}}, None)
        self.assertEqual(seen.get("max_tokens"), 1312)


class TestBudgetPerContext(unittest.TestCase):
    def test_speech_budget_bigger_than_vote(self):
        scenario = Scenario.load(SCENARIO)
        state = GameState.new(scenario, 1)
        seen = {}

        class P:
            model_name = "probe"

            def act(self, view, error=None, on_delta=None):
                seen[view["context"]] = view.get("budget")
                return {"kind": "abstain"}, {}

        players = {s: P() for s in state.seat_roles}
        seat = sorted(state.alive)[0]
        game._ask(state, EventLog(), players, seat, "day_vote")
        game._ask(state, EventLog(), players, seat, "day_speak")
        self.assertGreater(seen["day_speak"], seen["day_vote"])


class TestEmptyRetry(unittest.TestCase):
    def test_empty_response_retries_once_with_force_direct(self):
        p = player()
        calls = []

        def fake(conf, messages, **kw):
            calls.append(messages)
            if len(calls) == 1:
                return {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}
            return ok_resp()

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            action, meta = p.act({"context": "day_vote", "seat": 1, "role": "villager",
                                  "day": 1, "players": 9, "alive": [1, 2, 3],
                                  "budget": 2048}, None)
        self.assertEqual(action.get("kind"), "pass")
        self.assertEqual(meta["retried"], 1)
        # 第二次应带"直接给出 JSON"的强约束
        self.assertIn("直接给出 JSON", calls[1][1]["content"])


class TestTurnCap(unittest.TestCase):
    def test_single_cap_is_four_minutes(self):
        self.assertEqual(game.TURN_CAP, 240.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
