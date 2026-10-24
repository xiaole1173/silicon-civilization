"""对一局（或一批）JSONL 事件流做体检。

用法：
    python scripts/audit_run.py runs/werewolf_seed1.jsonl
    python scripts/audit_run.py runs/*.jsonl
    python scripts/audit_run.py runs/xxx.jsonl --json
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from engine.monitor import audit, render  # noqa: E402


def load(path: str) -> list:
    events = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    paths = []
    for pattern in args:
        paths.extend(sorted(glob.glob(pattern)))
    if not paths:
        raise SystemExit("用法：python scripts/audit_run.py <jsonl 或通配符>")

    bad = 0
    reports = []
    for path in paths:
        events = load(path)
        report = audit(events)
        report["file"] = os.path.basename(path)
        reports.append(report)
        if not report["ok"]:
            bad += 1
        if not as_json:
            print("=" * 70)
            print(os.path.basename(path))
            print(render(report))
    if as_json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))
    else:
        print("=" * 70)
        print("共 {} 局，{} 局有问题".format(len(paths), bad))


if __name__ == "__main__":
    main()
