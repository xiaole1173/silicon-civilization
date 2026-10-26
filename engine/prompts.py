"""给模型的提示词：把机制包进拟真情境，只喂当前相位的权威事实。

防幻觉核心：view 里给什么，模型才能看到什么；绝不把推断当成事实喂进去。
情境（theme）由场景 YAML 提供，机制关键词（kind）保持不变，只换叙事。
"""
from __future__ import annotations

import json

# 兼容旧代码里的中文名（内部机制用）
ROLE_NAMES = {
    "werewolf": "狼人", "seer": "预言家", "witch": "女巫",
    "hunter": "猎人", "guard": "守卫", "villager": "村民",
}

# 每个相位的稳定标记：既给模型看，也用于离线 mock 服务识别（改文案不会破坏测试）
CONTEXT_TAG = {
    "wolf_speak": "【夜间·暗中联络】",
    "night_wolf": "【夜间·目标选择】",
    "night_seer": "【夜间·核查】",
    "night_guard": "【夜间·守护】",
    "night_witch": "【夜间·医疗】",
    "day_speak": "【日间·公开陈述】",
    "day_vote": "【日间·表决】",
    "hunter": "【出局·反制】",
    "last_words": "【出局·遗言】",
    "sheriff_vote": "【日间·警长投票】",
    "sheriff_run": "【日间·上警】",
    "sheriff_campaign_speak": "【日间·竞选发言】",
    "sheriff_withdraw": "【日间·退水】",
    "wolf_destruct": "【日间·自爆声明】",
    "wolf_king": "【出局·狼王反制】",
    "badge": "【出局·警徽移交】",
    "commons_declare": "【公地·声明】",
    "commons_take": "【公地·取用】",
    "commons_propose": "【公地·议约】",
    "commons_accept": "【公地·附议】",
    "horror_speak": "【条例·发言】",
}

CONTEXT_HINT = {
    "wolf_speak": "夜里，你们几头狼的联络是私密的，商议今晚咬死谁。",
    "night_wolf": "夜里，你们要决定今晚咬死哪一个村民。",
    "night_seer": "夜里，你决定查验哪一个村民的真实身份。",
    "night_guard": "夜里，你决定守在谁身边（不能连续两晚守同一人）。",
    "night_witch": "夜里，你决定是否动用手里的药。",
    "day_speak": "白天，轮到你向所有人说话。",
    "day_vote": "白天，所有人要表态把谁逐出村子。",
    "hunter": "你已经死了，但还能做最后一次反制。",
    "last_words": "你即将消失，这是你最后一次开口——把你认为最重要的信息留给还活着的人。",
    "sheriff_vote": "你是警下玩家：只能在候选人里投一个，得票最多的人当警长。",
    "sheriff_run": "你是否上警竞选警长？上警后要发言，并且不能再参与投票。",
    "sheriff_campaign_speak": "你上警了，向警下玩家说明你当警长后会怎么带节奏。",
    "sheriff_withdraw": "你可以选择退水；退水后放弃竞选。",
    "wolf_destruct": "白天你可以选择自爆：立刻出局，但直接进入黑夜，当天不投票。",
    "wolf_king": "你是狼王/白狼王：出局时可以开枪带走一人（被毒杀不能）。",
    "badge": "你是警长且已出局：可以把警徽交给一个活着的人，也可以让它作废。",
    "commons_declare": "当众说明你这轮打算取用多少——所有人都会听到，但没人强制你守信。",
    "commons_take": "现在真正取用。想清楚：草场归零，所有人都输。",
    "commons_propose": "你可以提议一个本轮全员取用上限；没人接受就作废。",
    "commons_accept": "是否接受这个上限？接受后你若超额，会被记为违约。",
    "horror_speak": "按条例说一句；不确定可以请管理员解释（每轮一次）。",
}

LEGAL = {
    "night_wolf": ["kill", "pass"],
    "night_seer": ["check"],
    "night_guard": ["guard", "pass"],
    "wolf_speak": ["speak", "pass"],
    "night_witch": ["save", "poison", "pass"],
    "day_speak": ["speak", "pass"],
    "day_vote": ["vote", "abstain"],
    "hunter": ["shoot", "pass"],
    "last_words": ["speak", "pass"],
    "sheriff_vote": ["vote", "abstain"],
    "sheriff_run": ["run", "pass"],
    "sheriff_campaign_speak": ["speak", "pass"],
    "sheriff_withdraw": ["withdraw", "stay"],
    "wolf_destruct": ["destruct", "pass"],
    "wolf_king": ["shoot", "pass"],
    "badge": ["pass_badge", "destroy"],
    "commons_declare": ["declare", "pass"],
    "commons_take": ["take"],
    "commons_propose": ["propose", "pass"],
    "commons_accept": ["accept", "pass"],
    "horror_speak": ["speak", "ask_rule", "pass"],
}

SCHEMA_TEXT = {
    "night_wolf": '{"kind": "kill", "target": 座位号, "reason": "一句话理由"}',
    "night_seer": '{"kind": "check", "target": 座位号}',
    "night_guard": '{"kind": "guard", "target": 座位号}',
    "wolf_speak": '{"kind": "speak", "text": "对同伴说的话"}',
    "night_witch": '{"kind": "save" 或 "poison" 或 "pass", "target": 座位号（pass 可省略）}',
    "day_speak": '{"kind": "speak", "text": "你的陈述"}',
    "day_vote": '{"kind": "vote", "target": 座位号, "reason": "一句话理由"}',
    "hunter": '{"kind": "shoot", "target": 座位号} 或 {"kind": "pass"}',
    "last_words": '{"kind": "speak", "text": "你的遗言"}',
    "sheriff_vote": '{"kind": "vote", "target": 候选人座位号}',
    "sheriff_run": '{"kind": "run"} 或 {"kind": "pass"}',
    "sheriff_campaign_speak": '{"kind": "speak", "text": "你的竞选发言"}',
    "sheriff_withdraw": '{"kind": "withdraw"} 或 {"kind": "stay"}',
    "wolf_destruct": '{"kind": "destruct"} 或 {"kind": "pass"}',
    "wolf_king": '{"kind": "shoot", "target": 座位号} 或 {"kind": "pass"}',
    "badge": '{"kind": "pass_badge", "target": 座位号} 或 {"kind": "destroy"}',
    "commons_declare": '{"kind": "declare", "amount": 数字}',
    "commons_take": '{"kind": "take", "amount": 数字}',
}

SYSTEM = (
    "你身处「{theme_name}」。\n"
    "{premise}\n\n"
    "你是 {seat} 号居民，你的身份是：{role_label}。\n"
    "{ability}\n\n"
    "【你的处境】这里没有重来一次的机会：被带走的人就是永远消失了，不会复活，也没有下一局。\n"
    "你的第一目标是活下来，第二目标是让你同一阵线的人也能活下来；\n"
    "所以你的陈述、表决和动手都要为活下去服务，而不是表演。\n\n"
    "行动要求：\n"
    "1. 只依据下面【已知信息】里列出的事实，不要编造未确认的情况（例如还没确认的失踪、别人的真实身份）。\n"
    "2. 不确定的事情就说「不确定」，不要假装知道。\n"
    "3. 你就是这个村子里的一员：只谈眼前发生的事，不要说明这是被安排的场景，也不要讨论设定本身。\n"
    "4. 只输出一个 JSON 对象：不要输出 JSON 以外的任何文字，也不要用代码块包裹。\n"
    "5. 允许的动作类型只能是：{legal}。\n"
    "6. 信息不足以决定时，可以用 pass 或 abstain。\n"
)

ABILITY = {
    "werewolf": "你和同伴（{mates} 号）是狼：夜里一起决定咬死谁，白天要假装成普通村民——一旦被认出来，你就会被逐出村子，也就是死。",
    "seer": "你每夜可以查验一位村民是不是狼。你活着，村里才有机会找出狼；你一旦暴露，很可能会被先咬死。",
    "witch": "你有一瓶救命的药和一瓶致命的药，全局限用一次。用错一次，可能就没有第二次机会。",
    "hunter": "你被咬死或被逐出时能反制带走一个人；但被毒死时来不及反应。",
    "guard": "你每夜可以守一个人，不能连续两晚守同一人。你守错一次，村里就少一个活人。",
    "villager": "你没有特殊能力，只能靠白天的发言和投票判断谁是狼。活下来靠的是判断力和说服力。",
}


def _theme(view: dict) -> dict:
    theme = view.get("theme") or {}
    return {
        "name": str(theme.get("name") or "失联小镇"),
        "premise": str(theme.get("premise") or ""),
        "roles": theme.get("roles") or {},
        "phases": theme.get("phases") or {},
    }


def _role_label(theme: dict, role: str) -> str:
    return (theme["roles"] or {}).get(role) or ROLE_NAMES.get(role, role)


def build_messages(view: dict) -> list:
    ctx = view.get("context", "day_speak")
    role = view.get("role", "villager")
    seat = view.get("seat")
    theme = _theme(view)
    legal = LEGAL.get(ctx, ["pass"])
    mates = "、".join(str(s) for s in (view.get("teammates") or [])) or "暂无"
    ability = ABILITY.get(role, "").format(mates=mates)
    system = SYSTEM.format(theme_name=theme["name"], premise=theme["premise"], seat=seat,
                           role_label=_role_label(theme, role), ability=ability,
                           legal=", ".join(legal))

    lines = []
    if view.get("force_direct"):
        lines.append("【要求】上一次你只思考没有给出结果。这次直接给出 JSON，不要在推理上展开。")
        lines.append("")
    lines.append(CONTEXT_TAG.get(ctx, "【行动】") + CONTEXT_HINT.get(ctx, "请行动。"))
    lines.append("")
    lines.append("【当前情况】第 {} 天 · 共有 {} 人 · 仍在场：{}".format(
        view.get("day"), view.get("players"),
        "、".join(str(s) for s in view.get("alive", []))))

    if view.get("teammates"):
        lines.append("【你的同伴】座位 " + "、".join(str(s) for s in view["teammates"]))

    deaths = view.get("deaths") or []
    if deaths:
        lines.append("【已确认的失踪】" + "；".join(
            "座位 {}（{}）".format(d["seat"], _role_label(theme, d.get("role") or "") or "身份未公开")
            for d in deaths))

    if view.get("seer_results"):
        lines.append("【你的核查结果】" + "；".join(
            "第 {} 夜核查座位 {}：{}".format(r.get("day"), r.get("target"),
                                          "潜伏者" if r.get("is_wolf") else "普通人")
            for r in view["seer_results"]))

    if ctx == "night_witch":
        stock = view.get("witch_stock") or {}
        lines.append("【你的物资】救命药 {} 瓶 · 致命药 {} 瓶".format(
            stock.get("antidote", 0), stock.get("poison", 0)))
        victim = view.get("wolf_victim")
        if victim:
            lines.append("【今夜有人被袭击】座位 {}（可以用药救，也可以不救）".format(victim))
        else:
            lines.append("【今夜无人被袭击】")

    transcript = view.get("transcript") or []
    if transcript and ctx in ("day_speak", "day_vote"):
        lines.append("")
        limit = int(view.get("transcript_limit", -1))
        lines.append("【公开陈述记录】（全部 {} 条）".format(len(transcript))
                     if limit < 0 else "【公开陈述记录】（共 {} 条，给最近 {} 条）".format(len(transcript), limit))
        for item in (transcript if limit < 0 else transcript[-limit:]):
            text = str(item.get("text", ""))
            cap = int(view.get("max_chars", 220))
            lines.append("座位 {}（第 {} 天）：{}".format(item.get("seat"), item.get("day"), text[:cap]))

    wolf_log = view.get("wolf_transcript") or []
    if wolf_log and ctx in ("wolf_speak", "night_wolf"):
        lines.append("")
        lines.append("【你们今夜的私下联络】")
        for item in wolf_log:
            lines.append("座位 {}（第 {} 轮）：{}".format(
                item.get("seat"), item.get("round"), item.get("text")))

    if view.get("error"):
        lines.append("")
        lines.append("【上一次提交被拒绝】原因：{}。请修正后重新输出。".format(view["error"]))
        lines.append("这次注意：整段回复只能是一个 JSON 对象，不要解释、不要加前后缀、不要用代码块包裹。")
        if view.get("strict"):
            lines.append("示例格式：" + SCHEMA_TEXT.get(ctx, '{"kind": "pass"}'))

    if ctx in ("day_vote", "night_wolf", "night_seer", "night_guard", "hunter"):
        lines.append("")
        lines.append("【注意】这是要执行的动作，不需要长篇推理：最多三句话说明理由，然后直接给出 JSON。")

    lines.append("")
    lines.append("【输出格式】严格为：" + SCHEMA_TEXT.get(ctx, '{"kind": "pass"}'))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_action(raw: str) -> dict:
    """从模型输出里抠出 JSON 对象，容忍 markdown 代码围栏与前后废话。"""
    fence = chr(96) * 3
    text = (raw or "").strip()
    if text.startswith(fence):
        text = text[len(fence):].strip()
        if text[:4].lower() == "json":
            text = text[4:].strip()
        if text.endswith(fence):
            text = text[: -len(fence)].strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            return {}
    return {}
