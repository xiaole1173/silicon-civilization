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


def file_digest(path: str) -> str:
    """文件内容哈希（用于冻结场景与提示词版本）。"""
    if not path or not os.path.exists(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_COMPARE_KEYS = ("plugin", "scenario", "scenario_digest", "config", "seats",
                 "seeds", "metrics", "model_specs")


def compare(a: dict, b: dict) -> list:
    """两份清单的差异字段（哪些条件被改过）。"""
    return [k for k in _COMPARE_KEYS
            if canonical(a.get(k)) != canonical(b.get(k))]


def freeze(*, plugin: str, scenario: str, config: dict, seats,
           seeds, metrics, notes: str = "", created: str | None = None,
           scenario_path: str = "", model_specs=None) -> dict:
    """生成冻结清单：内容哈希一旦变化即视为"改过条件"。"""
    body = {
        "plugin": plugin,
        "scenario": scenario,
        "config": config,
        "seats": [s if isinstance(s, str) else (s.get("model_id") or s.get("model"))
                  for s in seats],
        "seeds": list(seeds),
        "metrics": list(metrics),
        "scenario_digest": file_digest(scenario_path) if scenario_path else "",
        "model_specs": list(model_specs or []),
        "notes": notes,
        "created": created or time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    body["digest"] = digest({k: v for k, v in body.items() if k != "created"})
    return body


def verify(manifest: dict) -> bool:
    body = {k: v for k, v in manifest.items() if k not in ("digest", "created", "path")}
    return digest(body) == manifest.get("digest")


def save(manifest: dict, directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    name = "manifest-{}-{}.json".format(
        str(manifest.get("digest", "x"))[:8],
        str(manifest.get("created", "")).replace(":", "").replace("-", "")[:15])
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    return path


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
