"""批量实验 CLI。

用法：
  python scripts/run_batch.py --plugin werewolf --scenario scenarios/werewolf12_standard.yaml \
      --seats 12 --seeds 1-3 --sweep "communication=on,off" --resume
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import store                                   # noqa: E402
from base import batch as batch_mod            # noqa: E402
from base import metrics as metrics_mod         # noqa: E402


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


def parse_sweep(text: str):
    sweep = {}
    for chunk in (text or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, vals = chunk.partition("=")
        items = []
        for v in vals.split(","):
            v = v.strip()
            if not v:
                continue
            if v in ("on", "off"):
                items.append(v)
            elif v.lower() in ("true", "false"):
                items.append(v.lower() == "true")
            else:
                try:
                    items.append(int(v))
                except ValueError:
                    try:
                        items.append(float(v))
                    except ValueError:
                        items.append(v)
        sweep[key.strip()] = items
    return sweep


def resolve_seats(count: int):
    models = [m for m in store.list_models() if m["id"] != "model-d3cf3bfe"]
    picked = models[:count]
    seats = []
    for i, m in enumerate(picked, start=1):
        conf = store.get_model(m["id"], with_secret=True)
        seats.append({"name": "{}号".format(i), "model_conf": conf})
    return seats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugin", default="werewolf")
    ap.add_argument("--scenario", default="scenarios/werewolf12_standard.yaml")
    ap.add_argument("--seats", type=int, default=12)
    ap.add_argument("--seeds", default="1-3")
    ap.add_argument("--sweep", default="")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--out", default="")
    ap.add_argument("--no-resume", action="store_true")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="同时跑几局（受模型端限流影响，建议 1-3）")
    args = ap.parse_args()

    seats = resolve_seats(args.seats)
    if not seats:
        print("模型库为空，先在模型管理页添加模型")
        return 2
    # 不同插件用不同键：狼人杀看 rounds_per_day，公地/规则怪谈看 rounds
    base_config = {"scenario": args.scenario, "rounds_per_day": args.rounds,
                   "rounds": args.rounds}
    sweep = parse_sweep(args.sweep)
    seeds = parse_seeds(args.seeds)

    print("插件 {} | 座位 {} | seeds {} | 条件 {} | 并发 {}".format(
        args.plugin, len(seats), seeds, sweep or "（单条件）", args.concurrency))

    def progress(row, done, total):
        print("  [{}/{}] {} | {} | winner={} | {}s".format(
            done, total, row["run_id"], row.get("state"), row.get("winner", ""),
            row.get("duration_s")))

    summary = batch_mod.run_batch(
        args.plugin, seats=seats, base_config=base_config, sweep=sweep, seeds=seeds,
        title=args.plugin, out_root=args.out or None,
        resume=not args.no_resume, concurrency=args.concurrency,
        on_progress=progress)
    print("\n批次完成:", summary["batch_id"])
    print("  索引:", summary["index"])
    print("  清单:", summary["manifest"])
    if summary.get("report"):
        print("  报告:", summary["report"])
    print("  执行 {} 局，跳过 {} 局，错误 {} 个".format(
        summary["executed"], summary["skipped"], len(summary["errors"])))

    # 聚合
    import csv
    rows = list(csv.DictReader(open(summary["index"], encoding="utf-8-sig")))
    def _is_num(key):
        if key == "duration_s":
            return True
        if not key.startswith("m_"):
            return False
        try:
            float(rows[0].get(key))
            return True
        except (TypeError, ValueError):
            return False

    numeric = [k for k in (rows[0].keys() if rows else []) if _is_num(k)]
    agg = metrics_mod.aggregate(rows, numeric)
    print("\n聚合（n={}）:".format(agg["n"]))
    for k in numeric:
        v = agg.get(k) or {}
        if v.get("mean") is not None:
            print("  {:<20} mean={:<10} sd={:<10} ci95=±{}".format(
                k, v["mean"], v["sd"], v["ci95"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
