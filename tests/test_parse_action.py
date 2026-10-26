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


class TestAliasForms(unittest.TestCase):
    """真模型常见的几种写法都要能救回来。"""

    def test_action_key_instead_of_kind(self):
        self.assertEqual(parse_action('{"action": "speak", "content": "好"}'),
                         {"action": "speak", "content": "好", "kind": "speak", "text": "好"})

    def test_content_instead_of_text(self):
        out = parse_action('{"kind": "speak", "content": "好"}')
        self.assertEqual(out["kind"], "speak")
        self.assertEqual(out["text"], "好")

    def test_action_name_as_key(self):
        out = parse_action('{"speak": "我这边没法确认"}')
        self.assertEqual(out["kind"], "speak")
        self.assertEqual(out["text"], "我这边没法确认")

    def test_action_name_as_key_with_number(self):
        out = parse_action('{"take": 8}')
        self.assertEqual(out["kind"], "take")
        self.assertEqual(out["amount"], 8)

    def test_value_key_for_amount(self):
        out = parse_action('{"kind": "take", "value": 6}')
        self.assertEqual(out["amount"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
