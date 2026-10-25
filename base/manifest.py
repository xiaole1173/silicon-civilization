"""实验清单（manifest / 预注册）：开跑前把条件冻结，防止事后调参。"""
from __future__ import annotations

import hashlib
import json
import os
import time


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def freeze(*, plugin: str, scenario: str, config: dict, seats,
           seeds, metrics, notes: str = "", created: str | None = None) -> dict:
    """生成冻结清单：内容哈希一旦变化即为"改过条件"。"""
    body = {
        "plugin": plugin,
        "scenario": scenario,
        "config": config,
        "seats": [s if isinstance(s, str) else s.get("model_id") or s.get("model")
                  for s in seats],
        "seeds": list(seeds),
        "metrics": list(metrics),
        "notes": notes,
        "created": created or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    body["digest"] = digest({k: v for k, v in body.items() if k != "created"})
    return body


def verify(manifest: dict) -> bool:
    """校验清单是否被改动过。"""
    body = {k: v for k, v in manifest.items() if k not in ("digest", "created")}
    return digest(body) == manifest.get("digest")


def save(manifest: dict, directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    name = "manifest-{}-{}.json".format(
        manifest.get("digest", "x")[:8],
        manifest.get("created", "").replace(":", "").replace("-", "")[:15])
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return path


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
