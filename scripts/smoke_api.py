"""模型管理接口冒烟测试：不需要任何真实 API Key。"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"
FAILS = []


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  " + str(extra)) if not cond else ""))
    if not cond:
        FAILS.append(name)


# 1 健康
st, d = call("GET", "/api/health")
check("health 200", st == 200 and d.get("ok"))

# 2 预设
st, d = call("GET", "/api/providers")
check("providers >= 8", st == 200 and len(d.get("providers", [])) >= 8, len(d.get("providers", [])))

# 3 非法创建（缺字段）
st, d = call("POST", "/api/models", {"name": ""})
check("reject empty name", st == 400 and d.get("errors"), d)

# 4 创建
st, d = call("POST", "/api/models", {
    "name": "冒烟测试模型",
    "provider": "custom",
    "api_base": "http://127.0.0.1:9/v1",
    "model": "smoke-model",
    "api_key": "sk-placeholder-not-a-key",
    "temperature": 0.5,
    "max_tokens": 128,
    "notes": "smoke",
})
check("create 201", st == 201 and d.get("ok"), d)
mid = (d.get("model") or {}).get("id")

# 5 列表不含明文 key
st, d = call("GET", "/api/models")
raw = json.dumps(d, ensure_ascii=False)
check("list hides plaintext key", "sk-placeholder-not-a-key" not in raw)
check("masked key present", "****" in raw or "abcdef" in raw)

# 6 更新时 key 留空 -> 保留
st, d = call("PUT", "/api/models/" + mid, {"name": "冒烟测试模型-改", "notes": "updated"})
check("update 200", st == 200 and d.get("ok"), d)
check("key kept after blank update", (d.get("model") or {}).get("api_key_set") is True)

# 7 测试连通：不可达地址应返回 ok=false 且有中文错误
st, d = call("POST", "/api/models/" + mid + "/test", {})
res = d.get("result") or {}
check("test unreachable handled", st == 200 and res.get("ok") is False and bool(res.get("error")), res)
print("      错误文案:", (res.get("error") or "")[:80])

# 8 删除
st, d = call("DELETE", "/api/models/" + mid)
check("delete 200", st == 200 and d.get("ok"))
st, d = call("GET", "/api/models/" + mid)
check("deleted really gone", st == 404)

# 9 静态页
for path in ["/web/models.html", "/viz/index.html", "/"]:
    req = urllib.request.Request(BASE + path)
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", "replace")
    check("static " + path, resp.status == 200 and "html" in body.lower())

print()
print("FAILED:", len(FAILS))
sys.exit(1 if FAILS else 0)
