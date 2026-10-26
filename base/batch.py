"""批量实验运行器（与场景无关）。

一次批次 = 条件矩阵 × 随机种子 × 重复；支持并发与断点续跑。
"""
from __future__ import annotations

import itertools
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import base.metrics as metrics_mod          # noqa: E402
import base.manifest as manifest_mod         # noqa: E402
from base import plugin as plugin_mod        # noqa: E402
from base import runner as runner_mod        # noqa: E402


@dataclass
class RunSpec:
    run_id: str
    condition: dict = field(default_factory=dict)
    seed: int = 0

    @property
    def config(self) -> dict:
        return dict(self.condition)


def build_conditions(sweep: dict) -> list:
    if not sweep:
        return [{}]
    keys = list(sweep.keys())
    values = [[v] if not isinstance(v, (list, tuple)) else list(v) for v in
              (sweep[k] for k in keys)]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def condition_name(cond: dict) -> str:
    if not cond:
        return "base"
    parts = []
    for k, v in cond.items():
        s = str(v).replace(".", "p").replace("-", "n")
        parts.append("{}-{}".format(k, s))
    return "_".join(parts)


def plan_runs(batch_id: str, sweep: dict, seeds) -> list:
    out = []
    for cond in build_conditions(sweep):
        cname = condition_name(cond)
        for seed in seeds:
            out.append(RunSpec(run_id="{}-{}-s{}".format(batch_id, cname, seed),
                               condition=cond, seed=int(seed)))
    return out


def _flatten(row: dict, prefix: str, data: dict) -> None:
    for k, v in (data or {}).items():
        if isinstance(v, (dict, list)):
            continue
        row["{}{}".format(prefix, k)] = v


def _execute(plugin, spec, base_config: dict, seats, title: str,
             per_run_timeout: float) -> dict:
    """跑一局，返回一行结果；不碰共享状态，可并发调用。"""
    cfg = dict(base_config or {})
    cfg.update(spec.condition)
    started = time.time()
    row = {"run_id": spec.run_id, "condition": condition_name(spec.condition),
           "seed": spec.seed, "communication": cfg.get("communication", "on")}
    try:
        session = runner_mod.create_session(spec.run_id, plugin, cfg, seats,
                                            title or plugin.name)
        thread = runner_mod.start(session)
        thread.join(timeout=per_run_timeout)
        row["state"] = session.state
        row["winner"] = session.winner or ""
        _flatten(row, "o_", (session.meta or {}).get("outcome") or {})
        _flatten(row, "m_", (session.meta or {}).get("metrics") or {})
        row["messages"] = len(session.messages)
        row["rounds"] = len(session.rounds)
        row["info_visibility"] = cfg.get("info_visibility", "full")
        row["show_reputation"] = cfg.get("show_reputation", "on")
        usages = [((m.meta or {}).get("usage") or {}) for m in session.messages]
        t_in = sum(int(u.get("prompt_tokens") or 0) for u in usages)
        t_out = sum(int(u.get("completion_tokens") or 0) for u in usages)
        row["tokens_in"] = t_in
        row["tokens_out"] = t_out
        row["tokens_total"] = t_in + t_out
        row["usage_estimated"] = any(bool(u.get("estimated")) for u in usages)
        price_in = float(cfg.get("price_in_per_m") or 0.0)
        price_out = float(cfg.get("price_out_per_m") or 0.0)
        if price_in or price_out:
            row["cost_usd"] = round(t_in / 1e6 * price_in + t_out / 1e6 * price_out, 6)
    except Exception as exc:
        row["state"] = "error"
        row["error"] = repr(exc)[:200]
    row["duration_s"] = round(time.time() - started, 1)
    return row


def run_batch(plugin_id: str, *, seats, base_config: dict | None = None,
              sweep: dict | None = None, seeds=(1,), title: str = "",
              out_root=None, resume: bool = True, per_run_timeout: float = 7200.0,
              concurrency: int = 1, on_progress=None) -> dict:
    """执行一个批次；concurrency>1 时多局并行。"""
    plugin = plugin_mod.get_plugin(plugin_id)
    if plugin is None:
        raise ValueError("插件不存在：" + plugin_id)

    manifest = manifest_mod.freeze(
        plugin=plugin_id, scenario=str((base_config or {}).get("scenario", "")),
        config=base_config or {}, seats=[s.get("model_conf", {}).get("model") or s.get("name")
                                        for s in seats],
        seeds=list(seeds), metrics=["metrics", "outcome"],
        notes="sweep=" + str(sweep or {}))
    batch_id = "b" + manifest["digest"][:10]
    out_root = Path(out_root) if out_root else (ROOT / "runs" / "batches")
    out_dir = out_root / batch_id
    out_dir.mkdir(parents=True, exist_ok=True)

    specs = plan_runs(batch_id, sweep or {}, seeds)
    manifest_path = manifest_mod.save(manifest, str(out_dir))
    manifest["path"] = manifest_path

    index_path = out_dir / "index.csv"
    rows: list = []
    done: set = set()
    if resume and index_path.exists():
        try:
            import csv
            with open(index_path, encoding="utf-8-sig") as fh:
                for r in csv.DictReader(fh):
                    rows.append(dict(r))
                    if r.get("run_id"):
                        done.add(r["run_id"])
        except Exception:
            rows = []

    pending = [s for s in specs if s.run_id not in done]
    errors = []
    executed = 0
    lock = threading.Lock()

    def record(row):
        nonlocal executed
        with lock:
            rows.append(row)
            executed += 1
            if row.get("state") == "error":
                errors.append((row["run_id"], row.get("error", "")))
            metrics_mod.write_csv(str(index_path), rows)
        if on_progress:
            on_progress(row, executed, len(pending))

    if concurrency and int(concurrency) > 1 and len(pending) > 1:
        with ThreadPoolExecutor(max_workers=int(concurrency)) as pool:
            futures = [pool.submit(_execute, plugin, spec, base_config or {}, seats,
                                   title, per_run_timeout) for spec in pending]
            for fut in as_completed(futures):
                record(fut.result())
    else:
        for spec in pending:
            record(_execute(plugin, spec, base_config or {}, seats, title, per_run_timeout))

    if rows:
        metrics_mod.write_csv(str(index_path), rows)

    summary = {"batch_id": batch_id, "index": str(index_path),
               "manifest": manifest_path, "runs": len(specs),
               "executed": executed, "skipped": len(done),
               "concurrency": int(concurrency or 1),
               "errors": errors, "dir": str(out_dir)}
    try:
        import base.report as report_mod
        md = report_mod.build(rows, manifest, chart_dir=str(out_dir))
        summary["report"] = report_mod.write(str(out_dir / "REPORT.md"), md)
    except Exception as exc:
        summary["report_error"] = repr(exc)

    with open(out_dir / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary