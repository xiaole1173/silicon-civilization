"""从批次索引生成报告（Markdown）：条件对比 + 一句话结论 + 清单校验。"""
from __future__ import annotations

import csv
import os
import time
from collections import Counter, defaultdict

import base.metrics as metrics_mod


def load_rows(index_path: str) -> list[dict]:
    with open(index_path, encoding="utf-8-sig") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _num(row, key, default=0.0) -> float:
    try:
        return float(row.get(key) or default)
    except (TypeError, ValueError):
        return default


def by_condition(rows) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[r.get("condition") or "base"].append(r)
    return dict(groups)


def compare(rows, metric_keys) -> list[dict]:
    out = []
    for cond, items in by_condition(rows).items():
        agg = metrics_mod.aggregate(items, metric_keys)
        out.append({"condition": cond, "n": len(items), "agg": agg,
                    "winners": Counter((i.get("winner") or "无") for i in items)})
    return out


def one_liner(comparisons, metric_key: str, label: str = "") -> str:
    usable = [c for c in comparisons
              if (c["agg"].get(metric_key) or {}).get("mean") is not None]
    if len(usable) < 2:
        return "（条件不足，尚不能下结论：需要至少两种条件各跑若干局）"
    usable.sort(key=lambda c: c["agg"][metric_key]["mean"])
    lo, hi = usable[0], usable[-1]
    lo_m = lo["agg"][metric_key]
    hi_m = hi["agg"][metric_key]
    name = label or metric_key
    return ("在{}上，{} 为 {:.3f}（n={}，95%CI ±{:.3f}），"
            "{} 为 {:.3f}（n={}，95%CI ±{:.3f}），相差 {:.3f}。").format(
        name, lo["condition"], lo_m["mean"], lo["n"], lo_m["ci95"],
        hi["condition"], hi_m["mean"], hi["n"], hi_m["ci95"],
        abs(hi_m["mean"] - lo_m["mean"]))


def build(rows, manifest=None, *, metric_key="m_utterances", metric_label="发言量") -> str:
    rows = list(rows)
    keys_all = [k for k in (rows[0].keys() if rows else []) if k.startswith("m_")]
    comps = compare(rows, keys_all + ["duration_s"])
    states = Counter((r.get("state") or "?") for r in rows)
    out = []
    out.append("# 实验报告")
    out.append("")
    out.append("- 生成时间：{}".format(time.strftime("%Y-%m-%d %H:%M")))
    out.append("- 局数：{}（{}）".format(len(rows), "，".join(
        "{}={}".format(k, v) for k, v in states.items())))
    if manifest:
        out.append("- 条件清单：{}（digest {}）".format(
            os.path.basename(manifest.get("path", "") or "manifest"),
            str(manifest.get("digest", ""))[:12]))
    out.append("")
    out.append("## 结论")
    out.append("")
    out.append(one_liner(comps, metric_key, metric_label))
    out.append("")
    out.append("## 条件对比")
    out.append("")
    head = ["条件", "n", "胜方分布"] + ["{} (mean±ci95)".format(k) for k in keys_all]
    out.append("| " + " | ".join(head) + " |")
    out.append("|" + "---|" * len(head))
    for c in comps:
        win = "，".join("{}×{}".format(k, v) for k, v in c["winners"].most_common(3))
        cells = [c["condition"], str(c["n"]), win or "-"]
        for k in keys_all:
            v = c["agg"].get(k) or {}
            cells.append("-" if v.get("mean") is None
                         else "{:.3f} ±{:.3f}".format(v["mean"], v["ci95"]))
        out.append("| " + " | ".join(cells) + " |")
    out.append("")
    if any(k.startswith("tokens_") for k in (rows[0].keys() if rows else [])):
        tin = sum(_num(r, "tokens_in") for r in rows)
        tout = sum(_num(r, "tokens_out") for r in rows)
        est = sum(1 for r in rows if str(r.get("usage_estimated")).lower() == "true")
        out.append("## 成本")
        out.append("")
        out.append("- 输入 tokens 合计：{}".format(int(tin)))
        out.append("- 输出 tokens 合计：{}".format(int(tout)))
        out.append("- 估算口径的局数：{}".format(est))
        out.append("")
    out.append("## 复现")
    out.append("")
    out.append("见同目录 manifest 与 index.csv；重跑同一条件会自动续跑。")
    out.append("")
    return "\n".join(out)


def write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path
