"""上下文装配：稳定前缀 + 只追加历史 + 事实卡 + 易变尾部。

顺序是刻意的：
    system（整局不变，利于前缀缓存）
    历史（只追加，倒序挑选、正序输出）
    事实卡（每轮重喂，防记错）
    本轮指令（最容易变，放最后，注意力最强）

裁剪策略：预算不够时从"最旧的普通消息"开始丢，旁白（system）永远保留；
丢弃的 id 会上报，供审计。
"""
from __future__ import annotations

DEFAULT_BUDGET_CHARS = 12000


def build(agent, session, instruction: str, budget_chars: int | None = None,
          facts_text: str = "") -> tuple[list, dict]:
    system = agent.system_prompt(session)
    budget = int(budget_chars or getattr(session, "budget_chars", DEFAULT_BUDGET_CHARS))
    tail = "【现在】" + instruction
    facts_block = ("\n" + facts_text) if facts_text else ""

    fixed = len(system) + len(tail) + len(facts_block) + 40
    remain = max(0, budget - fixed)

    visible = [m for m in session.messages if session.visible_to(agent.id, m)]
    chosen: list = []
    trimmed: list = []
    used = 0

    # 从新到旧挑：新消息优先保留，旁白必留
    for msg in reversed(visible):
        rendered = msg.render()
        if msg.kind == "system":
            chosen.append(msg)
            used += len(rendered)
            continue
        if used + len(rendered) > remain:
            trimmed.append(msg.id)
            continue
        chosen.append(msg)
        used += len(rendered)

    chosen.reverse()

    lines: list = []
    if trimmed:
        lines.append("（更早的 {} 条消息已省略）".format(len(trimmed)))
    for msg in chosen:
        lines.append(msg.render())
    body = "\n".join(lines)

    content = "{}\n{}\n{}".format(body, facts_block, tail).strip()
    info = {
        "trimmed": trimmed,
        "kept": len(chosen),
        "budget_chars": budget,
        "prompt_chars": len(system) + len(content),
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ], info
