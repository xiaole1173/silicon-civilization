"""流式链路测试：增量回调 + 拼接结果 + 侧车日志。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

import providers  # noqa: E402
from engine.events import EventLog  # noqa: E402


class FakeSSE:
    """模拟 urlopen 返回的可迭代响应：一行一个 data: ..."""

    def __init__(self, lines):
        self._lines = [l.encode("utf-8") for l in lines]

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def sse(*payloads):
    return ["data: " + json.dumps(p, ensure_ascii=False) + "\n" for p in payloads]


class TestStreamCallbacks(unittest.TestCase):
    def test_chat_stream_emits_thinking_and_answer(self):
        seen = []
        lines = sse(
            {"choices": [{"delta": {"reasoning_content": "先想想"}}]},
            {"choices": [{"delta": {"reasoning_content": "要不要救"}}]},
            {"choices": [{"delta": {"content": "{\"kind\": "}}]},
            {"choices": [{"delta": {"content": "\"save\"}"}}]},
        )
        resp = providers._read_stream(FakeSSE(lines), "chat_completions",
                                      lambda kind, piece: seen.append((kind, piece)))
        self.assertEqual(providers.extract_reasoning(resp), "先想想要不要救")
        self.assertEqual(providers.extract_text(resp), "{\"kind\": \"save\"}")
        kinds = {k for k, _ in seen}
        self.assertEqual(kinds, {"thinking", "answer"})
        self.assertGreaterEqual(len(seen), 4)

    def test_responses_stream_reasoning_delta(self):
        seen = []
        lines = sse(
            {"type": "response.reasoning_summary_text.delta", "delta": "分析局势"},
            {"type": "response.output_text.delta", "delta": "{\"kind\": \"pass\"}"},
            {"type": "response.completed", "response": {
                "id": "r1", "object": "response", "model": "m",
                "output": [{"type": "message", "content": [
                    {"type": "output_text", "text": "{\"kind\": \"pass\"}"}]}]}},
        )
        resp = providers._read_stream(FakeSSE(lines), "responses",
                                      lambda kind, piece: seen.append((kind, piece)))
        self.assertEqual(providers.extract_reasoning(resp, "responses"), "分析局势")
        self.assertEqual(providers.extract_text(resp, "responses"), "{\"kind\": \"pass\"}")
        self.assertIn(("thinking", "分析局势"), seen)

    def test_delta_callback_failure_does_not_break_stream(self):
        def boom(kind, piece):
            raise RuntimeError("页面挂了也别影响对局")
        lines = sse({"choices": [{"delta": {"content": "ok"}}]})
        resp = providers._read_stream(FakeSSE(lines), "chat_completions", boom)
        self.assertEqual(providers.extract_text(resp), "ok")


class TestRetryReset(unittest.TestCase):
    """重试会从头再生成，必须先发 reset，否则页面把两段思考拼在一起。"""

    def test_reset_marker_sent_before_each_attempt(self):
        from engine.players import LLMPlayer
        conf = {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                "model": "m", "api_key": "sk-x", "temperature": 0.0, "max_tokens": 256}
        player = LLMPlayer(1, "villager", conf)
        events = []

        def fake(conf, messages, **kw):
            cb = kw.get("on_delta")
            if cb:
                cb("thinking", "思考中")
            raise providers.ProviderError("请求超时（60 秒）")

        def on_delta(kind, piece):
            events.append(kind)

        import unittest.mock as mock
        with mock.patch.object(providers, "call_chat", side_effect=fake):
            player.act({"context": "day_vote", "seat": 1, "role": "villager",
                        "day": 1, "players": 9, "alive": [1, 2, 3]}, None, on_delta=on_delta)
        # 首次调用不 reset（避免页面闪烁），只有重试才 reset：
        # 顺序应为 thinking(第1次) -> reset(第2次开始) -> thinking(第2次)
        self.assertEqual(events.count("reset"), 1)
        self.assertEqual(events[0], "thinking")
        self.assertEqual(events[1], "reset")
        self.assertEqual(events[2], "thinking")


class TestLiveLog(unittest.TestCase):
    def test_live_sidecar_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "run.jsonl")
            log = EventLog(path)
            self.assertIsNotNone(log.live)
            log.live.emit(seat=3, kind="thinking", text="想到一半")
            log.emit("action", seat=3, kind="pass")
            live_path = os.path.join(tmp, "run.live.jsonl")
            self.assertTrue(os.path.exists(live_path))
            rows = [json.loads(l) for l in open(live_path, encoding="utf-8") if l.strip()]
            self.assertEqual(rows[0]["text"], "想到一半")
            events = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
            self.assertEqual(events[0]["event"], "action")


class TestSeatExtraction(unittest.TestCase):
    def test_extract_from_text(self):
        from engine.game import _extract_seat, normalize_action
        self.assertEqual(_extract_seat("我投 3 号"), 3)
        self.assertEqual(_extract_seat("先刀 12 号吧"), 12)
        self.assertIsNone(_extract_seat("我不确定"))

    def test_vote_falls_back_to_text_target(self):
        from engine.game import normalize_action
        action, note = normalize_action({}, "day_vote", "我投 7 号")
        self.assertEqual(action.get("kind"), "vote")
        self.assertEqual(action.get("target"), 7)
        self.assertIn("抽取", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
