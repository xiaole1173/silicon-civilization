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


def _numeric_keys(rows) -> list:
    """只保留能当数字用的 m_* 列（资源名之类是字符串，不能聚合）。"""
    out = []
    for k in (rows[0].keys() if rows else []):
        if not k.startswith("m_"):
            continue
        v = rows[0].get(k)
        if v in (None, ""):
            continue
        try:
            float(v)
        except (TypeError, ValueError):
            continue
        out.append(k)
    return out


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


def build(rows, manifest=None, *, metric_key="m_utterances", metric_label="发言量",
          chart_dir=None) -> str:
    rows = list(rows)
    keys_all = _numeric_keys(rows)
    # 指标键不存在时自动挑一个有意义的主指标（合作率 > 基尼 > 发言量 > 提取量）
    if metric_key not in keys_all:
        for cand in ("m_cooperation_rate", "m_gini", "m_utterances",
                     "m_total_extracted", "m_deaths"):
            if cand in keys_all:
                metric_key = cand
                metric_label = cand.replace("m_", "")
                break
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
    if chart_dir and len(comps) >= 2:
        try:
            pts = chart_points(rows, metric_key)
            svg = svg_chart(pts, "{}（均值 ±95%CI）".format(metric_label), metric_label)
            if svg:
                path = os.path.join(chart_dir, "chart.svg")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(svg)
                out.append("![{}](chart.svg)".format(metric_label))
                out.append("")
        except Exception as exc:
            out.append("（图表生成失败：{}）".format(exc))
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
        cost = sum(_num(r, "cost_usd") for r in rows)
        if cost:
            out.append("- 估算成本合计：{:.4f} USD".format(cost))
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

def svg_chart(points, title: str, ylabel: str = "", width: int = 520, height: int = 220) -> str:
    """极简柱状图（带误差棒），返回 SVG 文本。points: [{label, mean, ci}]"""
    pts = [p for p in points if p.get("mean") is not None]
    if not pts:
        return ""
    top = max(p["mean"] + (p.get("ci") or 0) for p in pts) or 1.0
    pad_l, pad_r, pad_t, pad_b = 44, 12, 18, 34
    inner_w = width - pad_l - pad_r
    inner_h = height - pad_t - pad_b
    slot = inner_w / max(1, len(pts))
    bars = []
    for i, p in enumerate(pts):
        h = inner_h * (p["mean"] / top)
        x = pad_l + slot * i + slot * 0.2
        w = slot * 0.6
        y = pad_t + inner_h - h
        bars.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="3" '
                    'fill="var(--brand, #2b2f36)" opacity="0.85"/>' % (x, y, w, max(1.0, h)))
        ci = p.get("ci") or 0
        if ci:
            ch = inner_h * (ci / top)
            cy = y - ch
            bars.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#8b929d"/>'
                        % (x + w / 2, cy, x + w / 2, y + ch))
            bars.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#8b929d"/>'
                        % (x + w / 2 - 4, cy, x + w / 2 + 4, cy))
        bars.append('<text x="%.1f" y="%.1f" font-size="10" fill="#5b636f" '
                    'text-anchor="middle">%s</text>' % (x + w / 2, height - 12, p["label"]))
        bars.append('<text x="%.1f" y="%.1f" font-size="10" fill="#2b2f36" '
                    'text-anchor="middle">%.3f</text>' % (x + w / 2, y - 5, p["mean"]))
    axis = ('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="#d4d8e0"/>'
            % (pad_l, pad_t + inner_h, width - pad_r, pad_t + inner_h))
    title_tag = ('<text x="%d" y="13" font-size="11" fill="#5b636f">%s</text>'
                 % (pad_l, title))
    ylabel_tag = ('<text x="6" y="%d" font-size="9" fill="#8b929d">%s</text>'
                  % (pad_t + 10, ylabel)) if ylabel else ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">'
            % (width, height, width, height)) + title_tag + ylabel_tag + axis + "".join(bars) + "</svg>"


def chart_points(rows, metric_key: str) -> list:
    """按条件聚合出柱状图数据。"""
    out = []
    comps = compare(rows, [metric_key])
    for c in comps:
        v = (c["agg"].get(metric_key) or {})
        out.append({"label": c["condition"].replace("regen_rate-", "ρ=").replace("p", "."),
                    "mean": v.get("mean"), "ci": v.get("ci95")})
    return out
