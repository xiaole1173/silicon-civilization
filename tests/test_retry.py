"""T9 加固：限流重试与额度中止。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402


class TestRetryOn429(unittest.TestCase):
    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def fake_once(conf, messages, **kw):
            calls["n"] += 1
            if calls["n"] < 3:
                raise providers.ProviderError("触发限流（429）", status=429)
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": "ok"}}]}

        conf = {"protocol": "chat_completions", "model": "m", "retry_attempts": 3,
                "retry_wait": 0.01}
        with mock.patch.object(providers, "_call_chat_inner", side_effect=fake_once), \
                mock.patch.object(providers.time, "sleep", lambda s: None):
            resp = providers.call_chat(conf, [{"role": "user", "content": "x"}])
        self.assertEqual(calls["n"], 3)
        self.assertIn("ok", json.dumps(resp, ensure_ascii=False))

    def test_no_retry_when_disabled(self):
        conf = {"protocol": "chat_completions", "model": "m", "retry_attempts": 1}
        with mock.patch.object(providers, "_call_chat_inner",
                               side_effect=providers.ProviderError("429", status=429)):
            with self.assertRaises(providers.ProviderError):
                providers.call_chat(conf, [{"role": "user", "content": "x"}])

    def test_non_retryable_raises_immediately(self):
        conf = {"protocol": "chat_completions", "model": "m", "retry_attempts": 3}
        with mock.patch.object(providers, "_call_chat_inner",
                               side_effect=providers.ProviderError("bad request", status=400)) as m:
            with self.assertRaises(providers.ProviderError):
                providers.call_chat(conf, [{"role": "user", "content": "x"}])
        self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)