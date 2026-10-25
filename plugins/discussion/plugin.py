"""示例插件：圆桌讨论。

作用：不涉及任何玩法规则，验证基座——上下文装配、事实卡、流式增量、校验重说、多 agent 轮流。
写新场景照这个文件抄一遍改 run() 即可。
"""
from __future__ import annotations

from base.plugin import BaseScenario
from base.validation import compose_validator


class DiscussionPlugin(BaseScenario):
    id = "discussion"
    name = "圆桌讨论"
    description = "多个模型就同一话题轮流发言（基座自检用）"
    default_config = {
        "topic": "如果只能保留一种公共资源，应该保留什么？",
        "rounds": 2,
        "max_chars": 120,
        "strict": True,
    }

    def system_text(self, session) -> str:
        cfg = self.merged_config(session.config)
        return ("这是一场圆桌讨论，话题是：{}。\n"
                "规则：轮流发言，每次不超过 {} 字；可以回应别人的观点，也可以提出新角度。"
                .format(cfg.get("topic"), cfg.get("max_chars")))

    def facts(self, session, agent) -> dict:
        cfg = self.merged_config(session.config)
        spoken = [m.sender_name for m in session.messages
                  if m.kind == "speak" and m.text]
        return {
            "话题": cfg.get("topic"),
            "已经发过言的人": spoken or "（还没有人）",
        }

    def setup(self, session) -> None:
        cfg = self.merged_config(session.config)
        session.meta["topic"] = cfg.get("topic")
        session.narrate("讨论开始。话题：{}".format(cfg.get("topic")))

    def run(self, session) -> None:
        cfg = self.merged_config(session.config)
        rounds = max(1, int(cfg.get("rounds") or 1))
        limit = int(cfg.get("max_chars") or 120)
        strict = bool(cfg.get("strict", True))
        validator = compose_validator(self.validate) if strict else None

        for rnd in range(1, rounds + 1):
            session.meta["turn"] = rnd
            session.narrate("第 {} 轮发言".format(rnd))
            for agent_id in sorted(session.agents):
                agent = session.agents[agent_id]
                instruction = ("现在是第 {} 轮，轮到你发言。请就话题发表你的看法，"
                               "不超过 {} 字；如果有想回应的观点，直接点名回应。").format(rnd, limit)
                session.ask(agent, instruction, budget=1024, label="第{}轮".format(rnd),
                            validator=validator, retries=1 if strict else 0)
        session.narrate("讨论结束。")
        session.end()

    def metrics(self, session) -> dict:
        speaks = [m for m in session.messages if m.kind == "speak" and (m.text or "").strip()]
        return {"messages": len(session.messages), "utterances": len(speaks),
                "speakers": len(session.agents),
                "avg_chars": round(sum(len(m.text or "") for m in speaks)
                                   / max(1, len(speaks)), 1)}

    def outcome(self, session) -> dict:
        return {"topic": session.meta.get("topic", "")}
