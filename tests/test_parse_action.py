"""解析容错：真模型常见"伪 JSON"要能救回来。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.prompts import parse_action  # noqa: E402

FENCE = chr(96) * 3


class TestParseAction(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(parse_action('{"kind": "take", "amount": 8}'),
                         {"kind": "take", "amount": 8})

    def test_fence(self):
        raw = FENCE + 'json\n{"kind":"pass"}\n' + FENCE
        self.assertEqual(parse_action(raw), {"kind": "pass"})

    def test_single_quotes(self):
        self.assertEqual(parse_action("{'kind': 'take', 'amount': 5}"),
                         {"kind": "take", "amount": 5})

    def test_fullwidth_quotes_and_prose(self):
        raw = "我决定 {\u201ckind\u201d: \u201ctake\u201d, \u201camount\u201d: 8} 就这样"
        self.assertEqual(parse_action(raw), {"kind": "take", "amount": 8})

    def test_bare_keys_and_values(self):
        self.assertEqual(parse_action("{kind: take, amount: 8}"),
                         {"kind": "take", "amount": 8})

    def test_trailing_comma(self):
        self.assertEqual(parse_action('{"kind": "take", "amount": 8,}'),
                         {"kind": "take", "amount": 8})

    def test_booleans_not_quoted(self):
        self.assertEqual(parse_action('{"ok": true, "n": 3}'), {"ok": True, "n": 3})

    def test_garbage(self):
        self.assertEqual(parse_action("我觉得应该少拿一点"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
