"""批量权力结构分析：把一批对局的 JSONL 汇总成 CSV。

用法：
  python scripts/power_batch.py --glob "runs/sessions/b9d0f89bb15-*.jsonl" --out runs/power.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from base import power as power_mod  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", default="runs/sessions/*.jsonl")
    ap.add_argument("--out", default="runs/power/index.csv")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    paths = sorted(glob.glob(args.glob))
    if args.limit:
        paths = paths[:args.limit]
    if not paths:
        raise SystemExit("没有匹配到日志：" + args.glob)

    rows = []
    for p in paths:
        try:
            r = power_mod.analyze(p)
        except Exception:
            continue
        rows.append({
            "session": r["session"],
            "seats": r["seats"],
            "rounds": r["rounds"],
            "proposals": r["proposals"],
            "accepts": r["accepts"],
            "adoption_rate": r["adoption_rate"],
            "ignored_agents": r["ignored_agents"],
            "speak_concentration": r["speak_concentration"],
            "decision_concentration": r["decision_concentration"],
            "voice_vs_power_gap": r["voice_vs_power_gap"],
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    def avg(key):
        vals = [r[key] for r in rows if isinstance(r[key], (int, float))]
        return round(sum(vals) / len(vals), 4) if vals else None

    print("局数:", len(rows))
    for key in ("proposals", "accepts", "adoption_rate", "ignored_agents",
                "speak_concentration", "decision_concentration", "voice_vs_power_gap"):
        print("  {:<22} {}".format(key, avg(key)))
    print("csv:", out)


if __name__ == "__main__":
    main()