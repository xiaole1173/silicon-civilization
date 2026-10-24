"""按队列探测连通性，然后只把通的模型入库。

用法：python scripts/probe_and_add.py            # 只探测
      python scripts/probe_and_add.py --add      # 探测 + 入库
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import providers  # noqa: E402
import store  # noqa: E402

QUEUE = os.path.join(ROOT, "data", "_add_queue.json")
RESULT = os.path.join(ROOT, "data", "_probe_results.json")

PROBE_MESSAGES = [{"role": "user", "content": "回复两个字：连通"}]


def probe(conf: dict, protocol: str, timeout: float = 25.0) -> dict:
    trial = dict(conf)
    trial["protocol"] = protocol
    trial["max_tokens"] = 512
    trial["temperature"] = 0
    try:
        resp = providers.call_chat(trial, PROBE_MESSAGES, max_tokens=512,
                                   temperature=0, timeout=timeout)
        text = providers.extract_text(resp, protocol).strip()
        return {"ok": True, "text": text[:60], "raw_keys": sorted(resp.keys())[:8]}
    except providers.ProviderError as exc:
        return {"ok": False, "error": str(exc)[:240]}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": repr(exc)[:240]}


def main() -> None:
    do_add = "--add" in sys.argv
    with open(QUEUE, encoding="utf-8") as fh:
        queue = json.load(fh)

    results = []
    for entry in queue["entries"]:
        for model in entry["models"]:
            conf = {"api_base": entry["base"], "api_key": entry["key"], "model": model}
            r_resp = probe(conf, "responses")
            r_chat = None if r_resp["ok"] else probe(conf, "chat_completions")
            chosen = "responses" if r_resp["ok"] else ("chat_completions" if r_chat and r_chat["ok"] else "")
            row = {"base": entry["base"], "model": model, "responses": r_resp,
                   "chat": r_chat, "chosen": chosen}
            results.append(row)
            mark = "OK " if chosen else "FAIL"
            print("[{}] {:<32} responses={:<46} chat={}".format(
                mark, model,
                ("通 " + (r_resp.get("text") or "")[:20]).strip() if r_resp["ok"] else "失败",
                ("通" if (r_chat or {}).get("ok") else ("失败" if r_chat else "未测"))))

    with open(RESULT, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)

    good = [r for r in results if r["chosen"]]
    print()
    print("汇总：{} 个模型，{} 个至少一种协议可用".format(len(results), len(good)))
    if not do_add:
        print("（未入库，加 --add 才会写入）")
        return

    added = 0
    for r in good:
        name = r["model"].split("/")[-1] if "/" in r["model"] else r["model"]
        payload = {"name": name, "protocol": r["chosen"], "provider": "custom",
                   "api_base": r["base"],
                   "model": r["model"],
                   "api_key": next(e["key"] for e in queue["entries"]
                                   if e["base"] == r["base"]),
                   "temperature": 0.7, "max_tokens": 1024,
                   "notes": "协议：" + r["chosen"] + "；探测通过"}
        model, errors = store.create_model(payload)
        if errors:
            print("入库失败 {}：{}".format(r["model"], errors))
        else:
            added += 1
    print("已入库：{} 个".format(added))


if __name__ == "__main__":
    main()
