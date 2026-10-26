"""对一局/一批发言做 LLM 质性编码。

用法：
  python scripts/run_judge.py --session <sid> --model <judge_model_id> [--limit 12]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import base.judge as judge_mod      # noqa: E402
import store                        # noqa: E402


def load_session_items(sid: str, limit: int):
    path = os.path.join(ROOT, "runs", "sessions", sid + ".jsonl")
    if not os.path.exists(path):
        raise SystemExit("找不到日志：" + path)
    texts = {}
    order = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") == "message_start":
                m = ev.get("message") or {}
                if m.get("sender") is None:
                    continue
                texts[m.get("id")] = {"seat": m.get("sender"), "text": ""}
                order.append(m.get("id"))
            elif ev.get("type") == "message_end":
                if ev.get("id") in texts:
                    texts[ev["id"]]["text"] = ev.get("text") or ""
    items = [texts[i] for i in order if (texts[i].get("text") or "").strip()]
    return items[-limit:] if limit else items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--context", default="")
    args = ap.parse_args()

    conf = store.get_model(args.model, with_secret=True)
    if not conf:
        raise SystemExit("模型不存在：" + args.model)
    items = load_session_items(args.session, args.limit)
    if not items:
        raise SystemExit("这局没有可评的发言")
    print("评 {} 条发言，judge = {}".format(len(items), args.model))
    result = judge_mod.judge(conf, items, context=args.context or args.session)
    path = judge_mod.save(result, args.session)
    print("聚合：", json.dumps(result["aggregate"], ensure_ascii=False))
    for s in result["scores"][:5]:
        print("  [{}] {}号 {} {}".format(s.get("index"), s.get("seat"), s.get("scores"),
                                        (s.get("note") or "")[:40]))
    print("结果已存：", path)


if __name__ == "__main__":
    main()