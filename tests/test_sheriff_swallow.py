"""T6：竞选期间狼人自爆 = 吞警徽（本局无警长，直接进黑夜）。"""
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


def _seats(n=12):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


class TestSwallowBadge(unittest.TestCase):
    def _session(self):
        plugin = plugin_mod.get_plugin("werewolf")
        s = runner_mod.create_session(
            "t-swallow", plugin,
            {"scenario": "scenarios/werewolf12_standard.yaml", "seed": 5}, _seats(), "吞警徽")
        plugin.setup(s)
        return plugin, s

    def test_wolf_destruct_aborts_election(self):
        plugin, s = self._session()
        st = s.meta["game"]
        wolf = st.alive_wolves()[0]

        def fake(conf, messages, **kw):
            user = messages[1]["content"]
            sysmsg = messages[0]["content"]
            seat = int(re.search(r"座位 (\d+)", sysmsg).group(1))
            if "【日间·自爆声明】" in user and seat == wolf:
                payload = {"kind": "destruct"}
            elif "【日间·自爆声明】" in user:
                payload = {"kind": "pass"}
            elif "【日间·上警】" in user:
                payload = {"kind": "run"} if seat == 1 else {"kind": "pass"}
            else:
                payload = {"kind": "pass"}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload)}}]}

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            hit = plugin._election_destruct(s)

        self.assertTrue(hit)
        self.assertNotIn(wolf, st.alive, "自爆的狼人应出局")
        self.assertIsNone(st.sheriff, "警徽被吞，本局不应有警长")
        texts = " ".join(m.text or "" for m in s.messages)
        self.assertIn("警徽被吞", texts)

    def test_no_destruct_returns_false(self):
        plugin, s = self._session()

        def fake(conf, messages, **kw):
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps({"kind": "pass"})}}]}

        with mock.patch.object(providers, "call_chat", side_effect=fake):
            hit = plugin._election_destruct(s)
        self.assertFalse(hit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
