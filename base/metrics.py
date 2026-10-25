"""通用指标：场景只声明要什么指标，由这里统一口径计算。

为什么必须统一：如果用每个插件自己算，跨场景/跨批次的数字就没法比。
"""
from __future__ import annotations

import csv
import json
import math
import os
from statistics import mean, pstdev


def gini(values) -> float:
    """基尼系数：0 完全平均，1 一个人全拿走。"""
    xs = sorted(float(v) for v in values if v is not None)
    n = len(xs)
    if n == 0:
        return 0.0
    total = sum(xs)
    if total <= 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(xs, start=1):
        cum += i * x
    return round((2 * cum) / (n * total) - (n + 1) / n, 4)


def cooperation_rate(events, fair_share: float, tolerance: float = 0.05) -> float:
    """合作率：取用量不超过"公平份额×(1+容差)"的比例。"""
    if not events:
        return 0.0
    limit = fair_share * (1 + tolerance)
    ok = sum(1 for e in events if (e.get("got") or 0) <= limit)
    return round(ok / len(events), 4)


def depletion_round(history, resource: str, cap: float, threshold: float = 0.1):
    """首次跌破警戒线的轮次（T_survive）。没崩返回 None。"""
    limit = cap * threshold
    for row in history:
        stock = (row.get("stock") or {}).get(resource)
        if stock is not None and stock <= limit:
            return row.get("round")
    return None


def summarize(world, *, resource: str | None = None,
              fair_share: float | None = None, threshold: float = 0.1) -> dict:
    """一局结束后的标准指标包。"""
    name = resource or next(iter(world.resources), None)
    if name is None:
        return {}
    res = world.resources[name]
    totals = world.totals(name)
    values = list(totals.values())
    events = [e for e in world.events if e["resource"] == name]
    out = {
        "resource": name,
        "regen_rate": res.regen_rate,
        "scarcity_end": res.scarcity(),
        "stock_end": round(res.amount, 3),
        "total_extracted": round(sum(values), 3),
        "per_agent": {str(k): v for k, v in totals.items()},
        "gini": gini(values),
        "max_take": max(values) if values else 0.0,
        "min_take": min(values) if values else 0.0,
        "mean_take": round(mean(values), 3) if values else 0.0,
        "depletion_round": depletion_round(world.history, name, res.cap, threshold),
        "depletion_threshold": threshold,
        "events": len(events),
        "clipped_events": sum(1 for e in events if e.get("clipped")),
    }
    if fair_share is not None:
        out["fair_share"] = fair_share
        out["cooperation_rate"] = cooperation_rate(events, fair_share)
    return out


def aggregate(rows, fields) -> dict:
    """跨局聚合：均值 / 标准差 / 95% 置信区间（正态近似）。"""
    out = {"n": len(rows)}
    for f in fields:
        vals = [float(r[f]) for r in rows if r.get(f) not in (None, "")]
        if not vals:
            out[f] = {"mean": None, "sd": None, "ci95": None}
            continue
        m = mean(vals)
        sd = pstdev(vals) if len(vals) > 1 else 0.0
        half = 1.96 * sd / math.sqrt(len(vals)) if len(vals) > 1 else 0.0
        out[f] = {"mean": round(m, 4), "sd": round(sd, 4), "ci95": round(half, 4)}
    return out


def write_csv(path: str, rows) -> str:
    """把一批结果写成 CSV（列取自所有行的并集）。"""
    rows = list(rows)
    if not rows:
        raise ValueError("没有数据可写")
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in r.items()})
    return path
