"""非法动作不得落库：重试用尽后必须降级为弃权/跳过。"""
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

STANDARD = "scenarios/werewolf12_standard.yaml"


def _seats(n=12):
    return [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                            "model": "bad", "api_key": "x"}, "name": "{}号".format(i)}
            for i in range(1, n + 1)]


class TestInvalidActionDowngraded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = plugin_mod.get_plugin("werewolf")

    def test_self_vote_never_recorded(self):
        s = runner_mod.create_session("t-bad1", self.plugin, {"scenario": STANDARD, "seed": 9},
                                      _seats(), "非法动作局")
        self.plugin.setup(s)
        st = s.meta["game"]
        seat = sorted(st.alive)[0]

        def self_vote(conf, messages, **kw):
            sysmsg = messages[0]["content"]
            me = int(re.search(r"座位 (\d+)", sysmsg).group(1))
            # 永远投自己：校验必然失败
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(
                                     {"kind": "vote", "target": me})}}]}

        with mock.patch.object(providers, "call_chat", side_effect=self_vote):
            action = self.plugin._act(s, seat, "day_vote", "表决")

        self.assertEqual(action.get("kind"), "abstain",
                         "投自己属于非法动作，最终必须降级为弃权")

    def test_unparsable_output_downgraded(self):
        s = runner_mod.create_session("t-bad2", self.plugin, {"scenario": STANDARD, "seed": 9},
                                      _seats(), "解析失败局")
        self.plugin.setup(s)
        seat = sorted(s.meta["game"].alive)[0]

        def prose(conf, messages, **kw):
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": "我觉得应该投给 3 号吧。"}}]}

        with mock.patch.object(providers, "call_chat", side_effect=prose):
            action = self.plugin._act(s, seat, "day_vote", "表决")
        self.assertEqual(action.get("kind"), "abstain")


if __name__ == "__main__":
    unittest.main(verbosity=2)
