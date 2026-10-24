"""协议适配测试：三种协议构造出的 URL / 请求体 / 响应解析。"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

import providers  # noqa: E402

MESSAGES = [
    {"role": "system", "content": "你是狼人"},
    {"role": "user", "content": "请行动"},
]


def conf(**kw):
    base = {"protocol": "chat_completions", "api_base": "https://api.example.com/v1",
            "model": "m-1", "api_key": "sk-abc", "temperature": 0.2, "max_tokens": 128}
    base.update(kw)
    return base


class TestChatCompletions(unittest.TestCase):
    def test_url_and_payload(self):
        spec = providers.build_request(conf(), MESSAGES)
        self.assertEqual(spec["url"], "https://api.example.com/v1/chat/completions")
        self.assertEqual(spec["payload"]["messages"], MESSAGES)
        self.assertEqual(spec["payload"]["max_tokens"], 128)
        self.assertEqual(spec["headers"]["Authorization"], "Bearer sk-abc")

    def test_trailing_slash_tolerated(self):
        spec = providers.build_request(conf(api_base="https://api.example.com/v1/"), MESSAGES)
        self.assertEqual(spec["url"], "https://api.example.com/v1/chat/completions")


class TestResponses(unittest.TestCase):
    def test_url_and_payload(self):
        spec = providers.build_request(conf(protocol="responses"), MESSAGES)
        self.assertEqual(spec["url"], "https://api.example.com/v1/responses")
        self.assertEqual(spec["payload"]["input"], MESSAGES)
        self.assertEqual(spec["payload"]["max_output_tokens"], 128)
        self.assertNotIn("messages", spec["payload"])
        self.assertNotIn("max_tokens", spec["payload"])

    def test_extract_output_text_field(self):
        resp = {"output_text": "连通"}
        self.assertEqual(providers.extract_text(resp, "responses"), "连通")

    def test_extract_nested_output(self):
        resp = {"output": [{"content": [{"type": "output_text", "text": "你好"}]}]}
        self.assertEqual(providers.extract_text(resp, "responses"), "你好")


class TestAnthropic(unittest.TestCase):
    def test_url_payload_and_headers(self):
        spec = providers.build_request(conf(protocol="anthropic_messages"), MESSAGES)
        self.assertEqual(spec["url"], "https://api.example.com/v1/messages")
        self.assertEqual(spec["payload"]["system"], "你是狼人")
        self.assertEqual(len(spec["payload"]["messages"]), 1)
        self.assertEqual(spec["payload"]["messages"][0]["role"], "user")
        self.assertEqual(spec["headers"]["x-api-key"], "sk-abc")
        self.assertEqual(spec["headers"]["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", spec["headers"])
        self.assertIn("max_tokens", spec["payload"])

    def test_extract_content_blocks(self):
        resp = {"content": [{"type": "text", "text": "连通"}]}
        self.assertEqual(providers.extract_text(resp, "anthropic_messages"), "连通")


class TestReasoning(unittest.TestCase):
    def test_responses_summary(self):
        resp = {"output": [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "先想想要不要救"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "救"}]},
        ]}
        self.assertEqual(providers.extract_reasoning(resp, "responses"), "先想想要不要救")
        self.assertEqual(providers.extract_text(resp, "responses"), "救")

    def test_chat_reasoning_content(self):
        resp = {"choices": [{"message": {"content": "{\"kind\": \"pass\"}",
                                         "reasoning_content": "信息不足，先过"}}]}
        self.assertEqual(providers.extract_reasoning(resp, "chat_completions"), "信息不足，先过")

    def test_anthropic_thinking(self):
        resp = {"content": [{"type": "thinking", "thinking": "让我算一下票"},
                            {"type": "text", "text": "投3号"}]}
        self.assertEqual(providers.extract_reasoning(resp, "anthropic_messages"), "让我算一下票")
        self.assertEqual(providers.extract_text(resp, "anthropic_messages"), "投3号")

    def test_missing_reasoning_is_empty(self):
        self.assertEqual(providers.extract_reasoning({"choices": [{"message": {"content": "x"}}]}), "")


class TestShared(unittest.TestCase):
    def test_unknown_protocol_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_request(conf(protocol="grpc"), MESSAGES)

    def test_empty_base_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_request(conf(api_base=""), MESSAGES)

    def test_empty_model_rejected(self):
        with self.assertRaises(providers.ProviderError):
            providers.build_request(conf(model=""), MESSAGES)

    def test_env_key_used_when_no_inline_key(self):
        os.environ["TEST_LLM_KEY"] = "sk-from-env"
        try:
            spec = providers.build_request(conf(api_key="", api_key_env="TEST_LLM_KEY"), MESSAGES)
            self.assertEqual(spec["headers"]["Authorization"], "Bearer sk-from-env")
        finally:
            os.environ.pop("TEST_LLM_KEY", None)

    def test_chat_extract_text(self):
        resp = {"choices": [{"message": {"content": "连通"}}]}
        self.assertEqual(providers.extract_text(resp), "连通")

    def test_presets_have_protocol(self):
        for preset in providers.PRESETS:
            self.assertIn(preset["protocol"], providers.PROTOCOLS, preset["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
