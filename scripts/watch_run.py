"""实时看一局正在跑的对局（终端）。

用法：
    python scripts/watch_run.py runs/xxx.jsonl           # 从头播完并继续跟随
    python scripts/watch_run.py runs/xxx.jsonl --tail 20 # 只看最近 20 条，再跟随
    python scripts/watch_run.py runs/xxx.jsonl --no-follow  # 只打印已有的，不跟随

原理：events.py 每写一个事件就落盘一行，所以这里只需 tail 增量解析。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROLE_SHORT = {"werewolf": "狼", "seer": "预", "witch": "女", "hunter": "猎",
              "guard": "守", "villager": "民"}


def short(role: str) -> str:
    return ROLE_SHORT.get(role or "", "?")


def fmt(event: dict) -> str:
    kind = event.get("event")
    day = event.get("day", "")
    if kind == "run_meta":
        return "[开局] seed={} 人数={} 模式={}".format(
            event.get("seed"), event.get("players"), event.get("mode"))
    if kind == "role_layout":
        return "[身份] " + "  ".join("{}号={}".format(k, short(v))
                                    for k, v in (event.get("seats") or {}).items())
    if kind == "phase":
        if event.get("phase") == "night":
            return "\n--- 第 {} 夜 ----".format(day)
        return "\n--- 第 {} 天 ---- 存活：{}".format(
            day, "、".join(str(s) for s in (event.get("alive") or [])))
    if kind == "guard_action":
        return "  守卫 -> {}".format(event.get("target") or "空守")
    if kind == "wolf_kill":
        return "  狼刀 -> {}".format(event.get("target") or "空刀")
    if kind == "seer_check":
        return "  查验 {} -> {}".format(event.get("target"),
                                       "狼人" if event.get("is_wolf") else "好人")
    if kind == "night_resolve":
        tags = []
        if event.get("same_night_rescue"):
            tags.append("同守同救→死亡")
        else:
            if event.get("guarded"):
                tags.append("守卫挡住")
            if event.get("saved"):
                tags.append("女巫救回")
        if event.get("poisoned"):
            tags.append("女巫用毒")
        deaths = event.get("deaths") or []
        body = "、".join("{}号({})".format(d["seat"], short(d.get("role"))) for d in deaths) or "平安夜"
        return "  结算：{}".format(body) + ("｜" + "，".join(tags) if tags else "")
    if kind == "action" and event.get("context") == "day_speak":
        if event.get("kind") == "speak":
            return "  {}号说：{}".format(event.get("seat"), event.get("text"))
        return None
    if kind == "vote":
        votes = event.get("votes") or {}
        return "  投票：" + "  ".join("{}->{}".format(k, v if v else "弃")
                                     for k, v in votes.items())
    if kind == "vote_tie":
        return "  平票：{} 号".format("、".join(str(s) for s in event.get("top") or []))
    if kind == "vote_revote":
        votes = event.get("votes") or {}
        return "  重投：" + "  ".join("{}->{}".format(k, v if v else "弃")
                                     for k, v in votes.items())
    if kind == "vote_tie_final":
        return "  再次平票，无人出局"
    if kind == "elimination":
        return "  出局：{}号（{}）".format(event.get("seat"), short(event.get("role")))
    if kind == "hunter_trigger":
        return "  猎人 {}号 触发技能".format(event.get("seat"))
    if kind == "hunter_shot":
        return "  猎人开枪 -> {}".format(event.get("target") or "放弃")
    if kind == "action_rejected":
        return "  [拒绝] {}号 {}：{}".format(event.get("seat"), event.get("context"),
                                            event.get("error"))
    if kind == "action_degraded":
        return "  [降级] {}号 {} -> {}".format(event.get("seat"), event.get("context"),
                                              event.get("fallback"))
    if kind == "game_end":
        return "\n结局：{}（共 {} 天）".format(event.get("winner"), event.get("days"))
    return None


def wait_for_file(path: str, timeout: float = 600.0) -> bool:
    started = time.time()
    while not os.path.exists(path):
        if time.time() - started > timeout:
            return False
        time.sleep(0.5)
    return True


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) < 2:
        raise SystemExit("用法：python scripts/watch_run.py <jsonl> [--tail N] [--no-follow]")
    path = sys.argv[1]
    follow = "--no-follow" not in sys.argv
    tail_n = None
    if "--tail" in sys.argv:
        idx = sys.argv.index("--tail")
        try:
            tail_n = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            tail_n = 20

    if not follow and not os.path.exists(path):
        raise SystemExit("文件不存在：" + path)
    if follow:
        print("等待日志出现：" + path)
        if not wait_for_file(path):
            raise SystemExit("超时，未等到日志文件")

    offset = 0
    printed = 0
    if tail_n:
        # 只看最后 N 条：把前面的跳掉
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        skip = max(0, len(lines) - tail_n)
        offset = sum(len(l.encode("utf-8")) for l in lines[:skip])
        for l in lines[skip:]:
            try:
                out = fmt(json.loads(l))
            except json.JSONDecodeError:
                continue
            if out:
                print(out)
                printed += 1

    while True:
        try:
            with open(path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
                offset = fh.tell()
        except FileNotFoundError:
            chunk = b""
        for raw in chunk.splitlines():
            if not raw.strip():
                continue
            try:
                event = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            out = fmt(event)
            if out:
                print(out)
                printed += 1
            if event.get("event") == "game_end" and not follow:
                return
        if not follow:
            return
        if printed and chunk:
            pass
        time.sleep(0.8)


if __name__ == "__main__":
    main()
