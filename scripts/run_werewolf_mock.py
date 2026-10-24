"""跑一局（或 N 局）纯规则型狼人杀，不需要任何 API Key。

用法：
    python scripts/run_werewolf_mock.py            # 1 局，seed=1，打印时间线
    python scripts/run_werewolf_mock.py 12         # 跑 12 局，只打印汇总
    python scripts/run_werewolf_mock.py 1 --quiet  # 1 局，不打印时间线
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import game, rules  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "scenarios", "werewolf.yaml")


def pick_scenario() -> str:
    """--scenario path 可指定别的规则预设（例如 12 人局）。"""
    for i, arg in enumerate(sys.argv):
        if arg == "--scenario" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("--scenario="):
            return arg.split("=", 1)[1]
    return SCENARIO

# Windows 控制台默认 GBK，中文会乱码；强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

ROLE_SHORT = {"werewolf": "狼", "seer": "预", "witch": "女", "hunter": "猎",
              "guard": "守", "villager": "民"}


def show_timeline(events: list) -> None:
    for e in events:
        kind = e.get("event")
        day = e.get("day", "")
        if kind == "role_layout":
            seats = "  ".join("{}号={}".format(s, ROLE_SHORT.get(r, r)) for s, r in e["seats"].items())
            print("[开局] " + seats)
        elif kind == "guard_action":
            print("  夜{} 守卫守 -> {}".format(day, e.get("target") or "空守"))
        elif kind == "wolf_kill":
            print("  夜{} 狼刀 -> {}".format(day, e.get("target") or "空刀"))
        elif kind == "seer_check":
            print("  夜{} 查验 {} -> {}".format(day, e.get("target"), "狼人" if e.get("is_wolf") else "好人"))
        elif kind == "night_resolve":
            tag = []
            if e.get("guarded"):
                tag.append("守卫生效")
            if e.get("saved"):
                tag.append("女巫救人")
            if e.get("poisoned"):
                tag.append("女巫用毒")
            if e.get("same_night_rescue"):
                tag.append("同守同救（该死）")
            deaths = e.get("deaths") or []
            dtext = "、".join("{}号({})".format(d["seat"], ROLE_SHORT.get(d.get("role", ""), "?")) for d in deaths) or "平安夜"
            print("夜{} 结算：{}".format(day, dtext) + ("｜" + "，".join(tag) if tag else ""))
        elif kind == "action" and e.get("context") == "day_speak" and e.get("kind") == "speak":
            print("  天{} {}号说：{}".format(day, e.get("seat"), e.get("text")))
        elif kind == "phase" and e.get("phase") == "day":
            print("")
            print("--- 天{} 开始，存活：{}".format(day, "、".join(str(s) for s in e.get("alive", []))))
        elif kind == "vote":
            votes = e.get("votes") or {}
            print("天{} 投票：{}".format(day, "  ".join("{}->{}".format(k, v or "弃") for k, v in votes.items())))
        elif kind == "vote_tie":
            print("天{} 平票：{} 号同票（策略：{}）".format(day, "、".join(str(s) for s in e.get("top", [])), e.get("policy")))
        elif kind == "vote_revote":
            votes = e.get("votes") or {}
            print("天{} 重投：{}".format(day, "  ".join("{}->{}".format(k, v or "弃") for k, v in votes.items())))
        elif kind == "vote_tie_final":
            print("天{} 再次平票，本轮无人出局".format(day))
        elif kind == "action_rejected":
            print("  [拒绝] {}号 {}：{}".format(e.get("seat"), e.get("context"), e.get("error")))
        elif kind == "elimination":
            print("天{} 出局：{}号（{}）".format(day, e.get("seat"), ROLE_SHORT.get(e.get("role", ""), "?")))
        elif kind == "hunter_shot":
            print("  猎人 {}号 开枪 -> {}".format(e.get("seat"), e.get("target") or "放弃"))
        elif kind == "action_degraded":
            print("  [降级] {}号 {} 非法动作 -> {}".format(e.get("seat"), e.get("context"), e.get("fallback")))
        elif kind == "game_end":
            print("结局：{}  共 {} 天".format(e.get("winner"), e.get("days")))


def main() -> None:
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    games = int(positional[0]) if positional else 1
    quiet = "--quiet" in sys.argv
    scenario = Scenario.load(pick_scenario())
    print("场景：{}  {} 人  角色：{}".format(scenario.name, scenario.players, scenario.roles))
    print()
    wins: dict[str, int] = {}
    for i in range(games):
        seed = 1 + i
        result = game.run_game(scenario, players={}, seed=seed,
                               log_path=os.path.join(ROOT, "runs", "werewolf_seed{}.jsonl".format(seed)))
        summary = result["summary"]
        wins[summary["winner"]] = wins.get(summary["winner"], 0) + 1
        if not quiet:
            show_timeline(result["log"].events)
            print()
            from engine.monitor import render
            print(render(summary["health"]))
            print()
    if games > 1:
        print("{} 局汇总：{}".format(games, "  ".join("{} {}".format(k, v) for k, v in wins.items())))


if __name__ == "__main__":
    main()
