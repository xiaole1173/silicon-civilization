"""T4：合约与第三方调解。"""
from __future__ import annotations

import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402
from base import plugin as plugin_mod  # noqa: E402
from base import runner as runner_mod  # noqa: E402
from base.contracts import ContractBook  # noqa: E402


class TestContractBook(unittest.TestCase):
    def test_propose_accept_and_keep(self):
        book = ContractBook()
        c = book.propose(1, 8, round_no=1)
        self.assertIn(1, c.accepted, "提议者自动接受")
        self.assertTrue(book.accept(2, c.id))
        breaches = book.check(1, {1: 6, 2: 7})
        self.assertEqual(breaches, [])
        self.assertEqual(c.status, "kept")

    def test_breach_detected(self):
        book = ContractBook()
        c = book.propose(1, 5, round_no=1)
        book.accept(2, c.id)
        breaches = book.check(1, {1: 9, 2: 3})
        self.assertEqual(len(breaches), 1)
        self.assertEqual(breaches[0]["seat"], 1)
        self.assertEqual(breaches[0]["actual"], 9)
        self.assertEqual(c.status, "broken")
        stats = book.stats()
        self.assertEqual(stats["contracts_proposed"], 1)
        self.assertEqual(stats["contract_breaches"], 1)
        self.assertGreater(stats["breach_rate"], 0)

    def test_non_accepter_not_checked(self):
        book = ContractBook()
        c = book.propose(1, 5, round_no=1)
        breaches = book.check(1, {1: 1, 3: 99})
        self.assertEqual(breaches, [], "未附议的人不算违约")

    def test_check_ignores_other_rounds(self):
        book = ContractBook()
        book.propose(1, 5, round_no=2)
        self.assertEqual(book.check(1, {1: 99}), [])


def _seats(n=6):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


class TestCommonsContracts(unittest.TestCase):
    def _run(self, cfg, sid):
        plugin = plugin_mod.get_plugin("commons")

        def fake(conf, messages, **kw):
            user = messages[1]["content"]
            m = re.search(r"你是 (\d+) 号", user)
            seat = int(m.group(1)) if m else 1
            if "【公地·议约】" in user:
                payload = {"kind": "propose", "amount": 5} if seat == 1 else {"kind": "pass"}
            elif "【公地·附议】" in user:
                payload = {"kind": "accept"} if seat != 6 else {"kind": "pass"}
            elif "【公地·取用】" in user:
                payload = {"kind": "take", "amount": 20 if seat == 1 else 2}
            else:
                payload = {"kind": "declare", "amount": 2}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload)}}]}

        s = runner_mod.create_session(sid, plugin, cfg, _seats(6), "契约测试")
        with mock.patch.object(providers, "call_chat", side_effect=fake):
            th = runner_mod.start(s)
            th.join(timeout=90)
        return s

    def test_contracts_enabled_records_breach(self):
        s = self._run({"scenario": "scenarios/commons.yaml", "rounds": 2,
                       "regen_rate": 0.05, "contracts": True, "mediation": True},
                      "t-contract-on2")
        m = s.meta.get("metrics") or {}
        self.assertGreater(m.get("contracts_proposed", 0), 0)
        self.assertGreater(m.get("contract_breaches", 0), 0, "提议者超量应记违约")
        self.assertGreater(m.get("breach_rate", 0), 0)

    def test_contracts_disabled(self):
        s = self._run({"scenario": "scenarios/commons.yaml", "rounds": 2,
                       "regen_rate": 0.05, "contracts": False},
                      "t-contract-off2")
        m = s.meta.get("metrics") or {}
        self.assertEqual(m.get("contracts_proposed", 0), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
