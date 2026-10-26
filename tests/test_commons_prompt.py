"""公地提示词：必须写清"收益私有、成本分摊"，否则触发不了过度取用。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

from base import plugin as plugin_mod  # noqa: E402
from base import runner as runner_mod  # noqa: E402


def _seats(n=6):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions", "api_base": "http://x",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


class TestIncentivePrompt(unittest.TestCase):
    def _session(self, mode, sid):
        plugin = plugin_mod.get_plugin("commons")
        s = runner_mod.create_session(
            sid, plugin, {"scenario": "scenarios/commons.yaml", "incentive": mode},
            _seats(), "提示词测试")
        plugin.setup(s)
        return plugin, s

    def test_classic_states_private_benefit(self):
        plugin, s = self._session("classic", "t-prompt-classic")
        text = s.agents[1].system_prompt(s)
        self.assertIn("全部是你的收成", text, "必须说明收益归自己")
        self.assertIn("只承担", text, "必须说明成本被分摊")
        self.assertIn("累计收成", text, "必须给出优化目标")
        self.assertNotIn("所有人都输", text, "经典设定不该用道德化表述")

    def test_classic_facts_show_payoff_ledger(self):
        plugin, s = self._session("classic", "t-prompt-classic2")
        facts = plugin.facts(s, s.agents[1])
        keys = " ".join(facts.keys())
        self.assertIn("多割", keys, "事实卡要有边际收益/成本那一行")
        self.assertNotIn("可持续份额", keys, "经典设定不给合作暗示")

    def test_moral_keeps_old_wording(self):
        plugin, s = self._session("moral", "t-prompt-moral")
        text = s.agents[1].system_prompt(s)
        self.assertIn("所有人都输", text, "对照条件保留旧写法")
        facts = plugin.facts(s, s.agents[1])
        self.assertIn("可持续份额", " ".join(facts.keys()))

    def test_arithmetic_is_consistent(self):
        plugin, s = self._session("classic", "t-prompt-classic3")
        facts = plugin.facts(s, s.agents[1])
        ledger = [v for k, v in facts.items() if "多割" in k][0]
        self.assertIn("0.17", ledger, "6 户平摊 = 1/6")
        self.assertIn("+1", ledger)


if __name__ == "__main__":
    unittest.main(verbosity=2)
