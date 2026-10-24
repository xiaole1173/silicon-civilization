"""狼人杀插件端到端：顺带压测基座（频道隔离、上下文装配、校验重说、会话收尾）。

用假的 call_chat 代替真实模型，几十毫秒跑完一整局。
"""
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

TAGS = {
    "【夜间·目标选择】": "kill",
    "【夜间·核查】": "check",
    "【夜间·守护】": "guard",
    "【夜间·医疗】": "witch",
    "【日间·表决】": "vote",
    "【出局·反制】": "hunter",
}


def _seat_of(system_text: str) -> int:
    m = re.search(r"座位 (\d+)", system_text)
    return int(m.group(1)) if m else 1


def _alive(user_text: str) -> list:
    m = re.search(r"在场：(.+)", user_text)
    if not m:
        return [1, 2, 3]
    return [int(x) for x in re.findall(r"(\d+)\(", m.group(1))]


def fake_call(conf, messages, **kw):
    system = messages[0]["content"]
    user = messages[1]["content"]
    seat = _seat_of(system)
    alive = _alive(user) or [seat]
    others = [s for s in alive if s != seat] or [seat]
    target = others[0]

    if "【夜间·私下商议】" in user:
        payload = {"kind": "speak", "text": "{}号：今晚带走 {} 号。".format(seat, target)}
    elif "【夜间·目标选择】" in user:
        payload = {"kind": "kill", "target": target}
    elif "【夜间·核查】" in user:
        payload = {"kind": "check", "target": target}
    elif "【夜间·守护】" in user:
        payload = {"kind": "guard", "target": target}
    elif "【夜间·医疗】" in user:
        payload = {"kind": "pass"}
    elif "【日间·表决】" in user:
        payload = {"kind": "vote", "target": target}
    elif "【出局·反制】" in user:
        payload = {"kind": "pass"}
    elif "【出局·遗言】" in user:
        payload = {"kind": "speak", "text": "我是 {} 号，临走前提醒大家看 {} 号。".format(seat, target)}
    else:
        payload = {"kind": "speak", "text": "我是 {} 号，我的看法是盯紧 {} 号。".format(seat, target)}

    content = json.dumps(payload, ensure_ascii=False)
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": content, "reasoning_content": "想一想"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


class TestWerewolfPlugin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plugin = plugin_mod.get_plugin("werewolf")

    def test_plugin_registered(self):
        self.assertIsNotNone(self.plugin, "werewolf 插件应当被发现")
        self.assertTrue(self.plugin.default_config)

    def test_full_game_runs_on_base(self):
        plugin = self.plugin
        seats = [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                                 "model": "fake", "api_key": "x", "temperature": 0.7,
                                 "max_tokens": 512}, "name": "{}号".format(i)}
                 for i in range(1, 13)]
        session = runner_mod.create_session("t-wolf", plugin, {"seed": 7}, seats, "测试局")
        with mock.patch.object(providers, "call_chat", side_effect=fake_call):
            thread = runner_mod.start(session)
            thread.join(timeout=60)
        self.assertEqual(session.state, "ended", "对局应当正常结束")
        self.assertGreater(len(session.messages), 30, "应当产生足够多的消息")

        # 频道隔离：狼队密聊不能出现在非狼的可见集合里
        wolf_channel = [m for m in session.messages if m.channel == "wolves"]
        self.assertTrue(wolf_channel, "应当有狼队密聊消息")
        wolves = [a.id for a in session.agents.values() if session.meta["game"].role_of(a.id) == "werewolf"]
        for m in wolf_channel:
            for aid in session.agents:
                if aid in wolves:
                    self.assertTrue(session.visible_to(aid, m))
                else:
                    self.assertFalse(session.visible_to(aid, m), "村民不应看见狼队密聊")

        # 上下文指标：每条发言都应带 prompt_chars
        speaks = [m for m in session.messages if m.kind == "speak" and m.meta]
        self.assertTrue(speaks)
        self.assertTrue(all("context" in (m.meta or {}) for m in speaks),
                        "每条消息都应记录上下文装配信息")

    def test_survives_malformed_model_output(self):
        """模型返回 null / 残缺 JSON 时，对局必须继续，不能崩。"""
        plugin = self.plugin
        seats = [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                                 "model": "bad", "api_key": "x"}, "name": "{}号".format(i)}
                 for i in range(1, 13)]
        session = runner_mod.create_session("t-wolf3", plugin, {"seed": 11}, seats, "畸形输出局")

        def broken_call(conf, messages, **kw):
            user = messages[1]["content"]
            if "【夜间·目标选择】" in user:
                payload = {"kind": "kill"}                 # 没有 target
            elif "【日间·表决】" in user:
                payload = {"target": None}                 # 没有 kind
            elif "【夜间·核查】" in user:
                return {"choices": [{"finish_reason": "stop",
                                     "message": {"content": "我不知道该查谁"}}]}   # 非 JSON
            else:
                payload = {"kind": "speak", "text": "随便说一句"}
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"content": json.dumps(payload, ensure_ascii=False)}}]}

        with mock.patch.object(providers, "call_chat", side_effect=broken_call):
            thread = runner_mod.start(session)
            thread.join(timeout=60)

        self.assertEqual(session.state, "ended")
        joined = " ".join((m.text or "") for m in session.messages)
        self.assertNotIn("int() argument", joined, "不应把类型错误暴露成对局中断")
        self.assertNotIn("Traceback", joined)

    def test_no_role_leak_in_public_channel(self):
        """身份表只能出现在观察者频道，绝不能进公共频道（否则模型直接读到）。"""
        plugin = self.plugin
        seats = [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                                 "model": "fake", "api_key": "x"}, "name": "{}号".format(i)}
                 for i in range(1, 13)]
        session = runner_mod.create_session("t-leak", plugin, {"seed": 5}, seats, "泄漏检查")
        plugin.setup(session)

        public_text = " ".join(m.text or "" for m in session.messages if m.channel == "public")
        for role in ("预言家", "女巫", "狼人", "白痴", "猎人"):
            self.assertNotIn("=" + role, public_text, "公共频道不应出现完整身份表")
        observer_text = " ".join(m.text or "" for m in session.messages if m.channel == "meta")
        self.assertIn("身份表", observer_text)

        # 观察者频道的消息对所有 agent 都不可见
        meta_msgs = [m for m in session.messages if m.channel == "meta"]
        self.assertTrue(meta_msgs)
        for msg in meta_msgs:
            for aid in session.agents:
                self.assertFalse(session.visible_to(aid, msg), "模型不应看到观察者旁白")

    def test_validation_rejects_illegal_action(self):
        """自刀（kill 自己）应被规则挡下，触发重说。"""
        plugin = self.plugin
        seats = [{"model_conf": {"protocol": "chat_completions", "api_base": "http://127.0.0.1:9/v1",
                                 "model": "fake", "api_key": "x"}, "name": "{}号".format(i)}
                 for i in range(1, 13)]
        session = runner_mod.create_session("t-wolf2", plugin, {"seed": 3}, seats, "校验局")
        plugin.setup(session)
        st = session.meta["game"]
        wolf = st.alive_wolves()[0]
        bad = {"kind": "kill", "target": wolf}
        ok, reason = plugin._validator("night_wolf")(session, session.agents[wolf],
                                                     json.dumps(bad, ensure_ascii=False))
        self.assertFalse(ok)
        self.assertIn("自己", reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
