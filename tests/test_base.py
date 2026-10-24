"""基座回归：上下文预算、事实卡、校验、插件发现。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from base import plugin as plugin_mod  # noqa: E402
from base.context import build as build_context  # noqa: E402
from base.facts import render_facts  # noqa: E402
from base.session import Agent, Session  # noqa: E402
from base.validation import compose_validator, default_validator, referenced_seats  # noqa: E402


class _FakeScenario:
    id = "fake"

    def system_text(self, session):
        return "这是测试场景。"

    def facts(self, session, agent):
        return {"测试事实": "值 A"}


def make_session(budget=2000, n_agents=3):
    s = Session("t1", "测试会话", _FakeScenario(), {"x": 1}, budget_chars=budget)
    for i in range(1, n_agents + 1):
        s.agents[i] = Agent(id=i, name="{}号".format(i),
                            model_conf={"model": "m", "protocol": "chat_completions"})
    return s


class TestPluginDiscovery(unittest.TestCase):
    def test_discussion_plugin_found(self):
        plugins = plugin_mod.list_plugins()
        self.assertTrue(any(p["id"] == "discussion" for p in plugins))

    def test_plugin_has_config_schema(self):
        p = plugin_mod.get_plugin("discussion")
        self.assertTrue(p.default_config)
        self.assertIn("topic", p.default_config)


class TestContextBudget(unittest.TestCase):
    def test_trim_keeps_newest_and_system(self):
        s = make_session(budget=600)
        s.narrate("开场旁白")
        for i in range(1, 41):
            s.add_message("public", 1, kind="speak", text="第{}条发言，".format(i) + "内容" * 10)
        agent = s.agents[1]
        messages, info = build_context(agent, s, "现在轮到你", s.budget_chars, "【事实】")
        content = messages[1]["content"]
        self.assertGreater(info["trimmed"].__len__(), 0, "预算不够时应当裁剪")
        self.assertIn("更早的", content, "应当提示已省略")
        self.assertIn("第40条发言", content, "最新一条必须保留")

    def test_system_narration_never_trimmed(self):
        s = make_session(budget=400)
        s.narrate("这条旁白必须留下")
        for i in range(1, 30):
            s.add_message("public", 1, kind="speak", text="填充" * 20)
        agent = s.agents[1]
        messages, info = build_context(agent, s, "轮到你", s.budget_chars, "")
        self.assertIn("这条旁白必须留下", messages[1]["content"])

    def test_prompt_under_budget(self):
        s = make_session(budget=800)
        for i in range(1, 30):
            s.add_message("public", 1, kind="speak", text="内容" * 30)
        messages, info = build_context(s.agents[1], s, "轮到你", s.budget_chars, "【事实】")
        self.assertLessEqual(info["prompt_chars"], 800 + 200)


class TestFacts(unittest.TestCase):
    def test_facts_include_alive_and_plugin_facts(self):
        s = make_session()
        s.meta["turn"] = 2
        text = render_facts(s, s.agents[1])
        self.assertIn("第 2 轮", text)
        self.assertIn("在场", text)
        self.assertIn("测试事实", text)
        self.assertIn("不要编造", text)


class TestValidation(unittest.TestCase):
    def test_referenced_seats(self):
        self.assertEqual(referenced_seats("我觉得 3 号和 12 号有问题"), [3, 12])

    def test_unknown_seat_rejected(self):
        s = make_session(n_agents=3)
        ok, reason = default_validator(s, s.agents[1], "我怀疑 9 号")
        self.assertFalse(ok)
        self.assertIn("不存在的座位", reason)

    def test_known_seat_passes(self):
        s = make_session(n_agents=3)
        ok, _ = default_validator(s, s.agents[1], "我怀疑 2 号")
        self.assertTrue(ok)

    def test_compose_runs_both(self):
        s = make_session(n_agents=3)
        plugin_check = lambda session, agent, text: (False, "插件规则不通过")
        check = compose_validator(plugin_check)
        ok, reason = check(s, s.agents[1], "正常发言")
        self.assertFalse(ok)
        self.assertIn("插件规则", reason)


class TestSessionUniqueness(unittest.TestCase):
    def test_message_ids_increment(self):
        s = make_session()
        a = s.add_message("public", 1, text="一")
        b = s.add_message("public", 2, text="二")
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(b.seq, a.seq + 1)

    def test_channel_visibility(self):
        s = make_session()
        s.add_channel("wolves", "狼队", subscribers=[1])
        private = s.add_message("wolves", 1, text="只给狼看")
        self.assertTrue(s.visible_to(1, private))
        self.assertFalse(s.visible_to(2, private))


if __name__ == "__main__":
    unittest.main(verbosity=2)
