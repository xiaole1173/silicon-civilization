"""对已入库的每个模型做一次连通性检查（走已保存的协议）。

用法：python scripts/check_models.py
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    models = json.loads(urllib.request.urlopen(BASE + "/api/models", timeout=15).read().decode())["models"]
    print("已入库：{} 个".format(len(models)))
    fails = 0
    for m in models:
        req = urllib.request.Request(BASE + "/api/models/" + m["id"] + "/test",
                                     data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
            r = res.get("result", {})
        except Exception as exc:
            print("ERR  {:<32} {}".format(m["name"], type(exc).__name__))
            fails += 1
            continue
        if r.get("ok"):
            print("OK   {:<32} {:<17} {:>6}ms  {}".format(
                m["name"], m["protocol"], r.get("latency_ms", 0),
                (r.get("reply") or "")[:12]))
        else:
            fails += 1
            print("FAIL {:<32} {:<17} {}".format(m["name"], m["protocol"],
                                                 (r.get("error") or "")[:70]))
    print("失败：{}".format(fails))


if __name__ == "__main__":
    main()
