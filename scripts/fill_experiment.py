"""把最新实验批次的结果写进 docs/EXPERIMENT.md 的结果区。

用法：
  python scripts/fill_experiment.py [--batch <id>] [--doc docs/EXPERIMENT.md]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import base.report as report_mod     # noqa: E402

BEGIN = "<!-- RESULTS:BEGIN -->"
END = "<!-- RESULTS:END -->"

MAIN_METRICS = [
    ("m_cooperation_rate", "合作率"),
    ("m_gini", "基尼系数"),
    ("m_depletion_round", "枯竭轮次"),
    ("m_collapse", "崩溃比例"),
    ("m_total_extracted", "总取用"),
]


def latest_batch(root: str) -> str:
    base = os.path.join(root, "runs", "experiments")
    if not os.path.isdir(base):
        raise SystemExit("没有 runs/experiments 目录")
    dirs = [d for d in os.listdir(base)
            if os.path.isdir(os.path.join(base, d))
            and os.path.exists(os.path.join(base, d, "index.csv"))]
    if not dirs:
        raise SystemExit("实验目录里还没有任何 index.csv")
    dirs.sort(key=lambda d: os.path.getmtime(os.path.join(base, d)), reverse=True)
    return dirs[0]


def load_rows(batch_dir: str):
    idx = os.path.join(batch_dir, "index.csv")
    if not os.path.exists(idx):
        raise SystemExit("还没有 index.csv")
    with open(idx, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def fmt(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    return "{:.3f}".format(f)


def build_section(rows, batch_id: str, has_chart: bool) -> str:
    lines = [BEGIN, "", "### 结果（自动生成，批次 `{}`）".format(batch_id), ""]
    n_runs = len(rows)
    n_ok = sum(1 for r in rows if r.get("state") in ("ended", "running"))
    tokens = sum(int(float(r.get("tokens_total") or 0)) for r in rows)
    cost = sum(float(r.get("cost_usd") or 0) for r in rows)
    lines.append("共 {} 局（有效 {}），tokens {}，估算成本 {:.4f} USD。".format(
                 n_runs, n_ok, tokens, cost))
    lines.append("")

    # 按条件聚合
    conds = {}
    for r in rows:
        conds.setdefault(r.get("condition") or "base", []).append(r)
    header = "| 条件 | n | " + " | ".join(label for _, label in MAIN_METRICS) + " |"
    sep = "|---" * (len(MAIN_METRICS) + 2) + "|"
    lines.append(header)
    lines.append(sep)
    for cond in sorted(conds):
        sub = conds[cond]
        cells = []
        for key, _ in MAIN_METRICS:
            vals = []
            for r in sub:
                try:
                    vals.append(float(r.get(key)))
                except (TypeError, ValueError):
                    continue
            cells.append("{:.3f}".format(sum(vals) / len(vals)) if vals else "—")
        lines.append("| {} | {} | {} |".format(cond, len(sub), " | ".join(cells)))
    lines.append("")

    if has_chart:
        lines.append("![合作率](chart.svg)")
        lines.append("")

    # 一句话结论
    comps = []
    for key, label in MAIN_METRICS[:1]:
        comps = report_mod.compare(rows, [key])
    if len(comps) >= 2:
        best = max(comps, key=lambda c: (c["agg"].get("m_cooperation_rate") or {}).get("mean") or -1)
        worst = min(comps, key=lambda c: (c["agg"].get("m_cooperation_rate") or {}).get("mean") or 9)
        bv = (best["agg"].get("m_cooperation_rate") or {}).get("mean")
        wv = (worst["agg"].get("m_cooperation_rate") or {}).get("mean")
        lines.append("**结论**：合作率最高的是 `{}`（{:.3f}），最低的是 `{}`（{:.3f}）。".format(
                     best["condition"], bv or 0, worst["condition"], wv or 0))
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="")
    ap.add_argument("--doc", default=os.path.join(ROOT, "docs", "EXPERIMENT.md"))
    args = ap.parse_args()

    batch_id = args.batch or latest_batch(ROOT)
    batch_dir = os.path.join(ROOT, "runs", "experiments", batch_id)
    rows = load_rows(batch_dir)
    if not rows:
        raise SystemExit("批次没有数据")
    has_chart = os.path.exists(os.path.join(batch_dir, "chart.svg"))
    section = build_section(rows, batch_id, has_chart)

    with open(args.doc, encoding="utf-8") as fh:
        doc = fh.read()
    if BEGIN in doc and END in doc:
        doc = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), section, doc, flags=re.S)
    else:
        doc = doc.rstrip() + "\n\n## 11. 结果\n\n" + section + "\n"
    with open(args.doc, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print("已写入", args.doc, "（批次", batch_id, "，", len(rows), "局）")


if __name__ == "__main__":
    main()