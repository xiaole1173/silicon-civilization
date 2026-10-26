"""网关体检：逐个模型试一次，给出可用/限流/登录页/超时的结论。

用法：
  python scripts/probe_gateway.py            # 全部模型
  python scripts/probe_gateway.py --models deepseek-v4-1-flash,kimi-k3
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402
import store      # noqa: E402


def classify(err: str) -> str:
    e = (err or "")
    if "429" in e or "限流" in e:
        return "限流/余额"
    if "网页" in e or "登录" in e:
        return "需要登录/VPN"
    if "超时" in e or "timeout" in e.lower():
        return "超时"
    if "认证" in e or "401" in e:
        return "密钥无效"
    return "其他"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    ids = [x.strip() for x in args.models.split(",") if x.strip()]
    if not ids:
        ids = [m["id"] for m in store.list_models()]

    ok = 0
    for mid in ids:
        conf = store.get_model(mid, with_secret=True)
        if not conf:
            print("{:<28} 跳过（不存在）".format(mid))
            continue
        started = time.time()
        try:
            resp = providers.call_chat(
                dict(conf, retry_attempts=1),
                [{"role": "user", "content": "只回复 ok"}],
                max_tokens=32, temperature=0, timeout=args.timeout)
            text = providers.extract_text(resp, providers.resolve_protocol(conf))
            dt = time.time() - started
            ok += 1
            print("{:<28} 可用 {:.1f}s  {}".format(mid, dt, (text or "").strip()[:12]))
        except Exception as exc:
            dt = time.time() - started
            print("{:<28} {} {:.1f}s  {}".format(mid, classify(str(exc)), dt,
                                                   str(exc)[:60]))
    print("")
    print("可用 {}/{}".format(ok, len(ids)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())