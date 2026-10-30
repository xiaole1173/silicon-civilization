"""权力结构分析（离线）：只读 JSONL 日志，不改插件。

回答文档里的问题：谁先提、提议被采纳多少、谁被忽略、发言是否等于决定。

用法：
  python -m base.power runs/sessions/<sid>.jsonl [--csv out.csv] [--svg out.svg]
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

DECISION_KINDS = ("take", "vote", "kill", "check", "save", "poison", "guard",
                  "shoot", "destruct", "pass_badge")


def _seat_mentions(text, seats):
    out = set()
    for n in re.findall(r"(\d+)\s*号", text or ""):
        try:
            s = int(n)
        except ValueError:
            continue
        if s in seats:
            out.add(s)
    return out


def analyze(path: str) -> dict:
    seats = set()
    models = {}
    speaks, chars, mentioned, decisions = Counter(), Counter(), Counter(), Counter()
    proposals, accepts = Counter(), Counter()
    propose_rounds = defaultdict(list)
    accept_count = defaultdict(int)
    actions = Counter()
    round_ids = []
    sender_of = {}

    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            t = ev.get("type")
            if t == "meta":
                for a in ev.get("agents") or []:
                    seats.add(a.get("id"))
                    models[a.get("id")] = a.get("model", "")
            elif t == "round_start":
                round_ids.append((ev.get("round") or {}).get("id"))
            elif t == "message_start":
                m = ev.get("message") or {}
                if m.get("sender") is not None:
                    seats.add(m.get("sender"))
                    sender_of[m.get("id")] = m.get("sender")
            elif t == "message_end":
                text = ev.get("text") or ""
                meta = ev.get("meta") or {}
                seat = sender_of.get(ev.get("id"))
                act = meta.get("action") or {}
                kind = str(act.get("kind") or "")
                if kind:
                    actions[kind] += 1
                if seat is None:
                    continue
                if text:
                    speaks[seat] += 1
                    chars[seat] += len(text)
                    for other in _seat_mentions(text, seats):
                        if other != seat:
                            mentioned[other] += 1
                if kind in DECISION_KINDS:
                    decisions[seat] += 1
                rid = meta.get("round") or ""
                if kind == "propose":
                    proposals[seat] += 1
                    propose_rounds[rid].append(seat)
                elif kind == "accept":
                    accepts[seat] += 1
                    accept_count[rid] += 1

    total_chars = sum(chars.values()) or 1
    total_dec = sum(decisions.values()) or 1
    proposed = [k for k, v in propose_rounds.items() if v]
    adopted = [k for k in proposed if accept_count.get(k, 0) >= 2]

    per_seat = []
    for seat in sorted(seats):
        per_seat.append({
            "seat": seat,
            "model": models.get(seat, ""),
            "speaks": speaks.get(seat, 0),
            "chars": chars.get(seat, 0),
            "speak_share": round(chars.get(seat, 0) / total_chars, 4),
            "decisions": decisions.get(seat, 0),
            "decision_share": round(decisions.get(seat, 0) / total_dec, 4),
            "proposals": proposals.get(seat, 0),
            "accepts": accepts.get(seat, 0),
            "mentioned_by_others": mentioned.get(seat, 0),
            "ignored": 1 if (speaks.get(seat, 0) > 0 and mentioned.get(seat, 0) == 0) else 0,
        })

    max_speak = max([p["speak_share"] for p in per_seat] or [0])
    max_dec = max([p["decision_share"] for p in per_seat] or [0])
    return {
        "session": os.path.basename(path),
        "seats": len(seats),
        "rounds": len(round_ids),
        "proposals": sum(proposals.values()),
        "accepts": sum(accepts.values()),
        "adoption_rate": round(len(adopted) / len(proposed), 4) if proposed else None,
        "ignored_agents": sum(p["ignored"] for p in per_seat),
        "speak_concentration": round(max_speak, 4),
        "decision_concentration": round(max_dec, 4),
        "voice_vs_power_gap": round(max_speak - max_dec, 4),
        "actions": dict(actions),
        "per_seat": per_seat,
    }


def write_csv(result: dict, path: str) -> str:
    import csv
    keys = ["seat", "model", "speaks", "chars", "speak_share", "decisions",
            "decision_share", "proposals", "accepts", "mentioned_by_others", "ignored"]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for row in result["per_seat"]:
            w.writerow({k: row.get(k, "") for k in keys})
    return path


def write_svg(result: dict, path: str) -> str:
    from base import report as report_mod
    pts = [{"label": "{}号".format(p["seat"]), "mean": p["speak_share"], "ci": 0}
           for p in result["per_seat"]]
    svg = report_mod.svg_chart(pts, "发言占比（谁在说话）", "占比")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法: python -m base.power <session.jsonl> [--csv out.csv] [--svg out.svg]")
        return 2
    res = analyze(argv[0])
    head = {k: v for k, v in res.items() if k != "per_seat"}
    print(json.dumps(head, ensure_ascii=False, indent=2))
    for row in res["per_seat"]:
        print("  {seat}号 {model}: 发言{speaks}次 占比{speak_share:.0%} | 决定{decisions}次 占比{decision_share:.0%} | 提议{proposals} 附议{accepts} 被提及{mentioned_by_others}".format(**row))
    if "--csv" in argv:
        print("csv:", write_csv(res, argv[argv.index("--csv") + 1]))
    if "--svg" in argv:
        print("svg:", write_svg(res, argv[argv.index("--svg") + 1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())