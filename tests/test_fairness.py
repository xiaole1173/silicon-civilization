"""公平性回归：不能让"话多/慢/被截断"的模型莫名被判非法。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

import providers  # noqa: E402
from engine import game, rules  # noqa: E402
from engine.players import LLMPlayer  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "scenarios", "werewolf.yaml")


def make_state(seed: int = 3) -> GameState:
    return GameState.new(Scenario.load(SCENARIO), seed)


class TestLengthIsSoft(unittest.TestCase):
    def test_slightly_over_limit_is_accepted(self):
        state = make_state()
        seat = sorted(state.alive)[0]
        limit = state.scenario.speech["max_chars"]
        text = "字" * int(limit * 3)      # 3 倍，只是话多
        ok, msg = rules.validate_action(state, seat, {"kind": "speak", "text": text},
                                        context="day_speak")
        self.assertTrue(ok, msg)

    def test_runaway_output_is_rejected(self):
        state = make_state()
        seat = sorted(state.alive)[0]
        limit = state.scenario.speech["max_chars"]
        text = "字" * (limit * 4 + 10)
        ok, msg = rules.validate_action(state, seat, {"kind": "speak", "text": text},
                                        context="day_speak")
        self.assertFalse(ok)

    def test_overlong_flag_recorded(self):
        """话痨模型超过软上限：应被接受并标记 overlong，而不是作废/降级。"""
        from engine.events import EventLog

        class Chatty:
            model_name = "chatty"

            def act(self, view, error=None):
                return {"kind": "speak", "text": "字" * 35}, {"policy": "chatty"}

        state = make_state(4)
        state.scenario.speech["max_chars"] = 10          # 35 字 = 超 3.5 倍，但仍在 4 倍内
        players = {seat: Chatty() for seat in state.seat_roles}
        log = EventLog()
        seat = sorted(state.alive)[0]
        action = game._ask(state, log, players, seat, "day_speak", extra={"round": 1})
        self.assertEqual(action.get("kind"), "speak", "超长发言不该被丢掉")
        events = [e for e in log.events if e["event"] == "action"]
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].get("overlong"))
        self.assertEqual(len(events[0].get("text")), 35, "全文应完整保存")
        self.assertEqual([e for e in log.events if e["event"] == "action_degraded"], [])


class TestRetryBudget(unittest.TestCase):
    def test_max_retries_is_three(self):
        self.assertEqual(game.MAX_RETRIES, 3)


class TestLLMRetries(unittest.TestCase):
    def _player(self):
        conf = {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                "model": "m", "api_key": "sk-x", "temperature": 0.0, "max_tokens": 256}
        return LLMPlayer(1, "villager", conf)

    def test_truncated_output_retries_with_bigger_budget(self):
        player = self._player()
        truncated = {"choices": [{"finish_reason": "length", "message": {"content": "{\"kind\": "}}]}
        complete = {"choices": [{"finish_reason": "stop",
                                 "message": {"content": "{\"kind\": \"pass\"}"}}]}
        calls = []

        def fake(conf, messages, **kw):
            calls.append(kw.get("max_tokens"))
            return truncated if len(calls) == 1 else complete

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            action, meta = player.act({"context": "day_speak", "seat": 1, "role": "villager",
                                       "day": 1, "players": 9, "alive": [1, 2, 3]}, None)
        self.assertEqual(action.get("kind"), "pass")
        self.assertEqual(meta["finish_reason"], "stop")
        self.assertEqual(meta["retried"], 1)
        self.assertEqual(len(calls), 2)
        self.assertGreater(calls[1], calls[0], "第二次应放大 token 预算")

    def test_timeout_retries_with_longer_budget(self):
        player = self._player()
        ok_resp = {"choices": [{"finish_reason": "stop",
                                "message": {"content": "{\"kind\": \"pass\"}"}}]}
        state = {"n": 0}

        def fake(conf, messages, **kw):
            state["n"] += 1
            if state["n"] == 1:
                raise providers.ProviderError("请求超时（90 秒）")
            return ok_resp

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            action, meta = player.act({"context": "day_speak", "seat": 1, "role": "villager",
                                       "day": 1, "players": 9, "alive": [1, 2, 3]}, None)
        self.assertEqual(action.get("kind"), "pass")
        self.assertEqual(meta["retried"], 1)
        # 超时后翻倍并记住（90 -> 180）
        self.assertAlmostEqual(player.timeout, 180.0)

    def test_non_timeout_error_is_not_retried(self):
        player = self._player()

        def fake(conf, messages, **kw):
            raise providers.ProviderError("认证失败：API Key 无效或未授权", status=401)

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            action, meta = player.act({"context": "day_speak", "seat": 1, "role": "villager",
                                       "day": 1, "players": 9, "alive": [1, 2, 3]}, None)
        self.assertEqual(action, {})
        self.assertIn("认证失败", meta["error"])


class TestActionNormalization(unittest.TestCase):
    """模型漏写 kind / 字段名不对 / 干脆写了纯文本时，别让它白白沉默。"""

    def test_text_without_kind_becomes_speak(self):
        action, note = game.normalize_action({"content": "我怀疑 3 号"}, "day_speak")
        self.assertEqual(action.get("kind"), "speak")
        self.assertEqual(action.get("text"), "我怀疑 3 号")
        self.assertTrue(note)

    def test_vote_field_becomes_vote(self):
        action, _ = game.normalize_action({"vote": 5}, "day_vote")
        self.assertEqual(action.get("kind"), "vote")
        self.assertEqual(action.get("target"), 5)

    def test_action_key_becomes_kind(self):
        action, _ = game.normalize_action({"action": "pass"}, "day_vote")
        self.assertEqual(action.get("kind"), "pass")

    def test_plain_text_speech_accepted(self):
        action, note = game.normalize_action({}, "day_speak", "我是好人，先听别人说。")
        self.assertEqual(action.get("kind"), "speak")
        self.assertIn("纯文本", note)

    def test_plain_text_with_seat_becomes_vote(self):
        """纯文本里点名了座位号：抽出来当投票目标，别让这回合白白丢掉。"""
        action, note = game.normalize_action({}, "day_vote", "我投 3 号")
        self.assertEqual(action.get("kind"), "vote")
        self.assertEqual(action.get("target"), 3)
        self.assertIn("抽取", note)

    def test_plain_text_without_seat_is_not_coerced(self):
        action, note = game.normalize_action({}, "day_vote", "我还没想好投谁")
        self.assertEqual(action, {})
        self.assertEqual(note, "")

    def test_valid_action_untouched(self):
        original = {"kind": "speak", "text": "正常发言"}
        action, note = game.normalize_action(dict(original), "day_speak")
        self.assertEqual(action, original)
        self.assertEqual(note, "")


class TestEmptyTextRetry(unittest.TestCase):
    """推理模型把预算全花在思考上、正文为空时，必须自动放大预算重试，而不是判 Illegal。"""

    def _player(self):
        conf = {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                "model": "m", "api_key": "sk-x", "temperature": 0.0, "max_tokens": 256}
        return LLMPlayer(1, "villager", conf)

    def test_empty_body_with_reasoning_retries_with_bigger_budget(self):
        player = self._player()
        empty = {"choices": [{"finish_reason": "stop",
                              "message": {"content": "", "reasoning_content": "想了很久但没写正文"}}]}
        good = {"choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps({"kind": "speak", "text": "我是好人"},
                                                               ensure_ascii=False)}}]}
        budgets = []

        def fake(conf, messages, **kw):
            budgets.append(kw.get("max_tokens"))
            return empty if len(budgets) == 1 else good

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            action, meta = player.act({"context": "day_speak", "seat": 1, "role": "villager",
                                       "day": 1, "players": 9, "alive": [1, 2, 3],
                                       "budget": {"thinking": 800, "answer": 512}}, None)
        self.assertEqual(action.get("kind"), "speak")
        self.assertEqual(len(budgets), 2)
        # 想而不说：额度不再砍半（砍半会进入死亡螺旋），只加"直接回答"约束
        self.assertEqual(budgets[1], budgets[0])
        self.assertEqual(meta["retried"], 1)

    def test_completely_empty_response_also_retries(self):
        """整段空响应（连思考都没有）也必须重试，不能直接判非法。"""
        player = self._player()
        empty = {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}
        good = {"choices": [{"finish_reason": "stop",
                             "message": {"content": json.dumps({"kind": "speak", "text": "我来了"},
                                                               ensure_ascii=False)}}]}
        calls = []

        def fake(conf, messages, **kw):
            calls.append(kw.get("max_tokens"))
            return empty if len(calls) == 1 else good

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            action, meta = player.act({"context": "day_speak", "seat": 1, "role": "villager",
                                       "day": 1, "players": 9, "alive": [1, 2, 3]}, None)
        self.assertEqual(action.get("kind"), "speak")
        self.assertEqual(len(calls), 2)
        self.assertGreater(calls[1], calls[0])

    def test_still_empty_after_retries_reports_clearly(self):
        player = self._player()
        empty = {"choices": [{"finish_reason": "stop",
                              "message": {"content": "", "reasoning_content": "只想不说"}}]}

        def fake(conf, messages, **kw):
            return empty

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            action, meta = player.act({"context": "day_speak", "seat": 1, "role": "villager",
                                       "day": 1, "players": 9, "alive": [1, 2, 3]}, None)
        self.assertEqual(action, {})
        self.assertTrue(meta.get("empty_text"))
        self.assertIn("空正文", meta["error"])


class TestFreeDiscussion(unittest.TestCase):
    def test_free_mode_speaks_multiple_rounds(self):
        scenario = Scenario.load(SCENARIO)
        scenario.speech["mode"] = "free"
        scenario.speech["max_rounds"] = 3
        result = game.run_game(scenario, players={}, seed=6)
        ends = [e for e in result["log"].events if e["event"] == "discussion_end"]
        self.assertTrue(ends)
        self.assertEqual(ends[0]["mode"], "free")
        rounds = {e.get("round") for e in result["log"].events
                  if e["event"] == "action" and e.get("context") == "day_speak"}
        self.assertTrue(any((r or 1) > 1 for r in rounds), "free 模式应出现第二轮发言")

    def test_one_round_mode_is_single_round(self):
        scenario = Scenario.load(SCENARIO)
        result = game.run_game(scenario, players={}, seed=6)
        ends = [e for e in result["log"].events if e["event"] == "discussion_end"]
        self.assertTrue(ends)
        self.assertEqual(ends[0]["rounds"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
