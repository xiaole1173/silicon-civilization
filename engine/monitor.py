"""对局体检：读事件流，自动检查规则一致性与异常。

设计目标：把"人工看日志"变成"每次跑完自动出一份体检报告"。
检查分三级：
- error   规则被破坏（数据不可用，必须修）
- warning 行为可疑（可能是模型问题，需要人看）
- info    统计信息（正常但值得知道）

可对"正在写入的日志"做增量体检：缺 game_end 只记为 info。
"""
from __future__ import annotations

import re
from collections import Counter

GOD_ROLES = ("seer", "witch", "hunter", "guard")
WOLF = "werewolf"


def audit(events: list) -> dict:
    errors: list = []
    warnings: list = []
    infos: list = []
    stats: dict = {}

    if not events:
        return {"ok": False, "errors": ["事件流为空"], "warnings": [], "infos": [],
                "stats": {}}

    # ---------- 1 结构 ----------
    for idx, event in enumerate(events, start=1):
        if event.get("seq") != idx:
            errors.append("事件序号断裂：第 {} 条 seq={}".format(idx, event.get("seq")))
            break
    if events[0].get("event") != "run_meta":
        errors.append("首个事件不是 run_meta")
    ended = events[-1].get("event") == "game_end"
    if not ended:
        infos.append("对局尚未结束（没有 game_end，可能仍在运行）")

    kinds = Counter(e.get("event") for e in events)
    stats["events"] = len(events)
    stats["counts"] = {k: v for k, v in kinds.items()}

    # ---------- 2 角色与存活追踪 ----------
    layout: dict = {}
    alive: set = set()
    players = 0
    for e in events:
        if e.get("event") == "role_layout":
            layout = {int(k): v for k, v in (e.get("seats") or {}).items()}
            alive = set(layout)
            players = len(layout)
            break
    if not layout:
        warnings.append("缺少 role_layout，无法核对身份与存活")
    stats["players"] = players

    dead: dict = {}
    witch_stock = None
    stock_history: list = []
    day = 0
    votes_today: dict = {}
    speaks_today: dict = {}
    guard_last = None
    speak_texts: list = []
    wolf_chats: list = []

    def kill(seat: int, cause: str, where: str) -> None:
        nonlocal alive
        seat = int(seat)
        if seat in dead:
            errors.append("座位 {} 重复死亡（{} 与之前 {}）".format(seat, where, dead[seat]["cause"]))
            return
        if seat not in alive:
            errors.append("座位 {} 在 {} 死亡，但当时已不在存活名单".format(seat, where))
            return
        alive.discard(seat)
        dead[seat] = {"cause": cause, "where": where}

    for e in events:
        kind = e.get("event")
        if kind == "phase":
            day = int(e.get("day") or day)
            if e.get("phase") == "day":
                votes_today = {}
                speaks_today = {}
        elif kind == "night_resolve":
            stock = e.get("witch_stock") or {}
            if witch_stock is not None:
                if stock.get("antidote", 0) > witch_stock.get("antidote", 0):
                    errors.append("解药数量增加了（第 {} 天）".format(e.get("day")))
                if stock.get("poison", 0) > witch_stock.get("poison", 0):
                    errors.append("毒药数量增加了（第 {} 天）".format(e.get("day")))
            witch_stock = dict(stock)
            stock_history.append(dict(stock))
            for d in e.get("deaths") or []:
                kill(d["seat"], d.get("cause", ""), "night_resolve 第 {} 天".format(e.get("day")))
            if e.get("guarded") and e.get("saved") and not e.get("same_night_rescue"):
                errors.append("第 {} 天守卫与解药同时生效却未判定同守同救".format(e.get("day")))
        elif kind == "guard_action":
            target = e.get("target")
            last = e.get("last_night")
            if target is not None and last is not None and int(target) == int(last):
                errors.append("第 {} 天守卫连续守了同一人 {} 号".format(e.get("day"), target))
            guard_last = target
        elif kind == "elimination":
            kill(e["seat"], "vote", "elimination 第 {} 天".format(e.get("day")))
        elif kind == "hunter_shot":
            if e.get("target") is not None:
                kill(e["target"], "hunter", "hunter_shot 第 {} 天".format(e.get("day")))
        elif kind == "vote":
            votes = e.get("votes") or {}
            if len(votes) > len(votes_today) + 0:
                pass
            for voter, target in votes.items():
                voter = int(voter)
                if voter in votes_today:
                    errors.append("座位 {} 在同一轮投票了两次".format(voter))
                votes_today[voter] = target
                if target is not None and int(target) not in alive and int(target) not in dead:
                    errors.append("座位 {} 投给了不存在的座位 {}".format(voter, target))
        elif kind == "action" and e.get("context") == "wolf_speak":
            seat = int(e.get("seat") or 0)
            if layout and layout.get(seat) != WOLF:
                errors.append("座位 {} 不是狼人却出现在狼队密聊中".format(seat))
            wolf_chats.append({"day": e.get("day"), "seat": seat,
                               "text": str(e.get("text") or "")})
        elif kind == "action" and e.get("context") == "day_speak":
            seat = int(e.get("seat") or 0)
            key = (day, e.get("round") or 1, seat)
            if key in speaks_today:
                errors.append("座位 {} 在第 {} 天第 {} 轮发言了两次".format(
                    seat, day, e.get("round") or 1))
            speaks_today[key] = True
            text = str(e.get("text") or "")
            if text:
                speak_texts.append((seat, text))

    stats["days"] = day
    stats["wolf_chat_messages"] = len(wolf_chats)
    stats["deaths"] = len(dead)
    stats["alive"] = sorted(alive)
    stats["witch_stock"] = witch_stock or {}

    # ---------- 3 模型侧异常 ----------
    rejected = sum(1 for e in events if e.get("event") == "action_rejected")
    degraded = sum(1 for e in events if e.get("event") == "action_degraded")
    actions = [e for e in events if e.get("event") == "action"]
    parse_fail = sum(int(a.get("parse_fail") or 0) for a in actions)
    latencies = [int(a["latency_ms"]) for a in actions if a.get("latency_ms")]
    stats["actions"] = len(actions)
    stats["rejected"] = rejected
    stats["degraded"] = degraded
    stats["parse_fail"] = parse_fail
    stats["avg_latency_ms"] = int(sum(latencies) / len(latencies)) if latencies else 0

    if degraded:
        warnings.append("有 {} 次动作因反复不合法被降级（模型没按格式/规则行动）".format(degraded))
    if rejected:
        infos.append("非法动作重试 {} 次（每次重试都带错误原因，属正常兜底）".format(rejected))
    if parse_fail:
        warnings.append("JSON 解析失败 {} 次（模型输出不是合法 JSON）".format(parse_fail))

    # ---------- 4 复读与可疑陈述 ----------
    if speak_texts:
        counts = Counter(text for _, text in speak_texts)
        top_text, top_n = counts.most_common(1)[0]
        if top_n >= 4:
            warnings.append("复读：同一句话出现 {} 次（{!r}）".format(top_n, top_text[:30]))
        bad_seats = set()
        for seat, text in speak_texts:
            for num in re.findall(r"(\d+)\s*号", text):
                n = int(num)
                if players and (n < 1 or n > players):
                    bad_seats.add(n)
        if bad_seats:
            warnings.append("发言提到不存在的座位号：{}（可能是幻觉）".format(sorted(bad_seats)))

    # ---------- 5 结局自洽 ----------
    end = events[-1] if ended else None
    if end:
        winner = end.get("winner")
        end_alive = set(int(s) for s in (end.get("alive") or []))
        if end_alive != alive:
            errors.append("最终存活名单与逐条死亡记录不一致")
        if layout:
            wolves = sum(1 for s in end_alive if layout.get(s) == WOLF)
            villagers = sum(1 for s in end_alive if layout.get(s) == "villager")
            gods = sum(1 for s in end_alive if layout.get(s) in GOD_ROLES)
            expect = None
            if wolves == 0:
                expect = "good"
            elif villagers == 0 or gods == 0:
                expect = "werewolves"
            if expect and winner != expect:
                errors.append("胜负判定不自洽：记录为 {}，按存活重算应为 {}".format(winner, expect))
            stats["end"] = {"winner": winner, "wolves": wolves,
                            "villagers": villagers, "gods": gods}

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "stats": stats,
    }


def render(report: dict) -> str:
    lines = []
    verdict = "通过" if report["ok"] else "发现 {} 处规则问题".format(len(report["errors"]))
    lines.append("体检结论：" + verdict)
    stats = report.get("stats") or {}
    if stats:
        lines.append("规模：{} 人 / {} 天 / {} 次动作 / {} 人出局".format(
            stats.get("players", "?"), stats.get("days", "?"),
            stats.get("actions", "?"), stats.get("deaths", "?")))
        lines.append("模型侧：非法重试 {} / 降级 {} / 解析失败 {} / 平均延迟 {}ms".format(
            stats.get("rejected", 0), stats.get("degraded", 0),
            stats.get("parse_fail", 0), stats.get("avg_latency_ms", 0)))
        if stats.get("end"):
            e = stats["end"]
            lines.append("结局：{}（狼 {} / 民 {} / 神 {}）".format(
                e["winner"], e["wolves"], e["villagers"], e["gods"]))
    for tag, items in (("错误", report["errors"]),
                       ("警告", report["warnings"]),
                       ("提示", report["infos"])):
        for item in items:
            lines.append("[{}] {}".format(tag, item))
    return "\n".join(lines)
