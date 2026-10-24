"""用模型注册表里的真实模型跑狼人杀。

用法：
    python server/app.py                                  # 先在别的窗口起服务（可选）
    python scripts/run_werewolf_llm.py --list             # 看有哪些模型
    python scripts/run_werewolf_llm.py --model deepseek   # 全部座位用同一模型
    python scripts/run_werewolf_llm.py --model deepseek --games 3

注意：每个动作都是一次真实 API 调用，9 人局打完通常上百次调用。
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import store  # noqa: E402
from engine import game  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "scenarios", "werewolf.yaml")
ROLE_SHORT = {"werewolf": "狼", "seer": "预", "witch": "女", "hunter": "猎", "villager": "民"}


def pick_model(name: str) -> dict:
    models = store.list_models()
    if not models:
        raise SystemExit("模型注册表是空的：先运行 python server/app.py，在 /web/models.html 里添加模型")
    for m in models:
        if name in (m["id"], m["name"]):
            conf = store.get_model(m["id"], with_secret=True)
            if not conf:
                raise SystemExit("读取模型配置失败：" + m["id"])
            return conf
    raise SystemExit("找不到模型：{}。可用：{}".format(
        name, "、".join("{}（{}）".format(m["id"], m["name"]) for m in models)))


def summarize(events: list) -> None:
    actions = [e for e in events if e["event"] == "action"]
    degraded = [e for e in events if e["event"] == "action_degraded"]
    rejected = [e for e in events if e["event"] == "action_rejected"]
    latencies = [a["latency_ms"] for a in actions if a.get("latency_ms")]
    parse_fail = sum(a.get("parse_fail", 0) for a in actions)
    print("调用统计：动作 {} 次｜非法重试 {} 次｜降级 {} 次｜JSON 解析失败 {} 次".format(
        len(actions), len(rejected), len(degraded), parse_fail))
    if latencies:
        print("延迟：中位 {}ms｜最大 {}ms".format(
            int(statistics.median(latencies)), max(latencies)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="模型 id 或名称（所有座位同一个模型）")
    ap.add_argument("--seats", help="座位分配表 YAML（每个座位不同模型）")
    ap.add_argument("--scenario", help="规则预设（默认 9 人局）")
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--list", action="store_true", help="列出可用模型")
    args = ap.parse_args()

    if args.list:
        models = store.list_models()
        if not models:
            print("（空）先用 /web/models.html 添加模型")
        for m in models:
            print("{}  {}  {}  {}".format(m["id"], m["name"], m["model"], m["api_base"]))
        return

    if not args.model and not args.seats:
        raise SystemExit("需要 --model 或 --seats（--list 可查看已入库模型）")

    scenario_path = args.scenario or SCENARIO
    scenario = Scenario.load(scenario_path)

    # 座位分配：--seats 优先，否则全部座位用 --model
    seat_models: dict = {}
    if args.seats:
        import yaml
        with open(args.seats, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        mapping = data.get("seats") or {}
        for seat, model_id in mapping.items():
            key = str(model_id).strip()
            conf_seat = store.get_model(key, with_secret=True)
            if not conf_seat:
                # 允许写显示名称
                by_name = [m for m in store.list_models() if m["name"] == key]
                if by_name:
                    conf_seat = store.get_model(by_name[0]["id"], with_secret=True)
            if not conf_seat:
                raise SystemExit("座位 {} 指定的模型不存在：{}".format(seat, model_id))
            seat_models[int(seat)] = conf_seat
        missing = [s for s in range(1, scenario.players + 1) if s not in seat_models]
        if missing:
            raise SystemExit("座位表缺少这些座位：" + "、".join(map(str, missing)))
        log_tag = "mixed"
    else:
        if not args.model:
            raise SystemExit("需要 --model 或 --seats")
        conf = pick_model(args.model)
        log_tag = str(conf["id"])

    for i in range(args.games):
        seed = args.seed + i
        state = GameState.new(scenario, seed)
        models = seat_models if args.seats else {seat: dict(conf) for seat in state.seat_roles}
        players = game.build_players(state, mode="llm", seed=seed, models=models)
        result = game.run_game(scenario, players=players, seed=seed,
                               log_path=os.path.join(ROOT, "runs",
                                                     "werewolf_llm_{}_seed{}.jsonl".format(log_tag, seed)))
        summary = result["summary"]
        print("seed {}: 结局 {}（{} 天），存活 {}".format(
            seed, summary["winner"], summary["days"],
            "、".join("{}号{}".format(s, ROLE_SHORT.get(r, r)) for s, r in summary["alive_roles"].items())))
        summarize(result["log"].events)
        from engine.monitor import render
        print(render(summary["health"]))


if __name__ == "__main__":
    main()
