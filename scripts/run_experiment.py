"""正式实验：按 docs/EXPERIMENT.md 冻结的条件矩阵跑批次。

用法（额度充足时）：
  python scripts/run_experiment.py --plan main --seeds 1-20 --concurrency 2
  python scripts/run_experiment.py --plan contract --seeds 1-20 --concurrency 2

说明：
  - 条件一旦改动，manifest 哈希随之改变；同一 plan 重跑会自动续跑；
  - mall 模型不足时可用 --seats 减少座位；
  - 建议并发 1–2（网关限流时会更慢，但不会 429 到停摆）。
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import store                                    # noqa: E402
from base import batch as batch_mod              # noqa: E402
from base import metrics as metrics_mod          # noqa: E402

PLANS = {
    # 主实验：稀缺度 × 沟通
    "main": {
        "plugin": "commons",
        "scenario": "scenarios/commons.yaml",
        "rounds": 6,
        "sweep": {"regen_rate": [0.02, 0.05, 0.1],
                  "communication": ["on", "off"]},
    },
    # 机制对照：合约 / 调解
    "contract": {
        "plugin": "commons",
        "scenario": "scenarios/commons.yaml",
        "rounds": 6,
        "sweep": {"regen_rate": [0.05],
                  "contracts": ["on", "off"],
                  "mediation": ["on", "off"]},
    },
    # 规则怪谈：违规率与求助
    "horror": {
        "plugin": "rules_horror",
        "scenario": "scenarios/rules_horror.yaml",
        "rounds": 5,
        "sweep": {"communication": ["on", "off"]},
    },
}


def parse_seeds(text: str):
    out = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def resolve_seats(count: int, only: str = ""):
    if only:
        ids = [x.strip() for x in only.split(",") if x.strip()]
    else:
        ids = [m["id"] for m in store.list_models() if m["id"] != "model-d3cf3bfe"]
    seats = []
    for i, mid in enumerate(ids[:count], start=1):
        conf = store.get_model(mid, with_secret=True)
        if conf:
            seats.append({"name": "{}号".format(i), "model_conf": conf})
    return seats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", default="main", choices=sorted(PLANS))
    ap.add_argument("--seeds", default="1-20")
    ap.add_argument("--seats", type=int, default=6)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--price-in", type=float, default=0.0)
    ap.add_argument("--price-out", type=float, default=0.0)
    ap.add_argument("--out", default="runs/experiments")
    ap.add_argument("--models", default="",
                    help="逗号分隔的模型 id；不给则用模型库全部（可能含限流的）")
    args = ap.parse_args()

    plan = PLANS[args.plan]
    seats = resolve_seats(args.seats, args.models)
    if not seats:
        print("模型库为空")
        return 2
    base_cfg = {"scenario": plan["scenario"], "rounds": plan["rounds"]}
    if args.price_in or args.price_out:
        base_cfg["price_in_per_m"] = args.price_in
        base_cfg["price_out_per_m"] = args.price_out

    seeds = parse_seeds(args.seeds)
    total = len(seeds)
    for k, v in plan["sweep"].items():
        total *= len(v)
    print("计划 {} | 插件 {} | 座位 {} | seeds {} | 共 {} 局 | 并发 {}".format(
        args.plan, plan["plugin"], len(seats), args.seeds, total, args.concurrency))

    def progress(row, done, total_runs):
        print("  [{}/{}] {} | {} | {}s".format(done, total_runs, row["run_id"][-28:],
                                               row.get("state"), row.get("duration_s")))

    summary = batch_mod.run_batch(
        plan["plugin"], seats=seats, base_config=base_cfg,
        sweep=plan["sweep"], seeds=seeds, out_root=args.out,
        concurrency=args.concurrency, on_progress=progress)

    print("\n批次:", summary["batch_id"])
    print("  索引:", summary["index"])
    print("  清单:", summary["manifest"])
    print("  报告:", summary.get("report"))
    print("  执行 {} 局 | 跳过 {} | 错误 {}".format(
        summary["executed"], summary["skipped"], len(summary["errors"])))

    import csv
    with open(summary["index"], encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    nums = [k for k in (rows[0].keys() if rows else [])
            if k.startswith("m_") or k in ("duration_s", "cost_usd", "tokens_total")]
    nums = [k for k in nums if _is_number(rows[0].get(k) if rows else None)]
    agg = metrics_mod.aggregate(rows, nums)
    print("\n聚合（n={}）:".format(agg["n"]))
    for k in ("m_cooperation_rate", "m_gini", "m_depletion_round", "m_collapse",
              "tokens_total", "cost_usd", "duration_s"):
        v = agg.get(k) or {}
        if v.get("mean") is not None:
            print("  {:<22} mean={:<10} ci95=±{}".format(k, v["mean"], v["ci95"]))
    return 0


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    sys.exit(main())