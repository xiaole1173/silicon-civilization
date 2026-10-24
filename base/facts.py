"""事实卡：每轮把"当前确定的事实"重新喂一遍。

为什么要有它：长对话里模型最容易记错的就是这几样——谁还活着、谁死了、自己查过谁。
不要指望它记得准，每轮重新给。
"""
from __future__ import annotations


def render_facts(session, agent, extra: dict | None = None) -> str:
    """把事实渲染成结构化文本块（放历史之后、本轮指令之前）。"""
    lines = ["【确定的事实】"]

    round_no = session.meta.get("turn", 0)
    if round_no:
        lines.append("· 现在是第 {} 轮".format(round_no))

    alive = sorted(session.agents.keys())
    lines.append("· 在场：{}".format("、".join("{}（{}）".format(i, session.agents[i].name)
                                             for i in alive)))

    facts = dict(getattr(session.scenario, "facts", lambda s, a: {})(session, agent) or {})
    if extra:
        facts.update(extra)

    for key, value in facts.items():
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, tuple)):
            value = "、".join(str(v) for v in value)
        lines.append("· {}：{}".format(key, value))

    lines.append("· 以上是事实；不在其中的事情不要编造。")
    return "\n".join(lines)
