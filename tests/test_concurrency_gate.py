"""并发闸门：未获授权时只能串行跑（用户 2026-10-28 的硬性要求）。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

from base.batch import check_concurrency  # noqa: E402


class TestConcurrencyGate(unittest.TestCase):
    def test_default_is_serial(self):
        self.assertEqual(check_concurrency(1), 1)
        self.assertEqual(check_concurrency(None), 1)
        self.assertEqual(check_concurrency(0), 1)
        self.assertEqual(check_concurrency("x"), 1)

    def test_parallel_requires_authorization(self):
        with self.assertRaises(ValueError) as ctx:
            check_concurrency(4)
        self.assertIn("未获授权", str(ctx.exception))

    def test_parallel_allowed_when_authorized(self):
        self.assertEqual(check_concurrency(4, True), 4)
        self.assertEqual(check_concurrency(2, allow_parallel=True), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
