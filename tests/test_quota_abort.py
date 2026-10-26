"""T9 加固：额度耗尽时批次应自动中止，而不是空跑。"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402
from base import batch as batch_mod  # noqa: E402


def _seats(n=3):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "quota-x", "api_key": "x",
                            "retry_attempts": 1}} for i in range(1, n + 1)]


def _always_429(*args, **kwargs):
    raise providers.ProviderError("触发限流或余额不足（429）", status=429)


class TestQuotaAbort(unittest.TestCase):
    def test_batch_marks_quota_and_stops(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(providers, "call_chat", side_effect=_always_429):
            summary = batch_mod.run_batch(
                "discussion", seats=_seats(3), base_config={"rounds": 1},
                seeds=[1, 2, 3, 4], out_root=td, concurrency=1)
            rows = list(csv.DictReader(open(summary["index"], encoding="utf-8-sig")))
            self.assertTrue(rows, "至少要记录已经跑过的局")
            self.assertEqual(rows[0]["state"], "quota", "429 为主的局应标记为 quota")
            self.assertGreater(int(rows[0].get("quota_errors") or 0), 0)
            self.assertEqual(summary["aborted"], "quota", "连续额度失败应中止批次")
            self.assertLess(len(rows), 4, "中止后不应把剩余局全跑完")


if __name__ == "__main__":
    unittest.main(verbosity=2)
