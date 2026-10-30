"""角色卡：把"人"的画像变成可注入、可版本化的 Agent 设定。

一张卡只描述实验设定，不是对真人的事实判断；卡上有版本号，日志会记录它。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CARDS_DIR = ROOT / "cards"

FIELDS = ("name", "role", "goal", "public_identity", "private_info",
          "risk_appetite", "style", "trust_initial", "forbidden", "win_condition")


def _version(raw: bytes) -> str:
    return "card-" + hashlib.sha1(raw).hexdigest()[:8]


def load(path: str) -> dict:
    """读一张卡（yaml 或 json），补上版本号。"""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    raw = p.read_bytes()
    if p.suffix.lower() in (".json",):
        import json as _json
        data = _json.loads(raw.decode("utf-8"))
    else:
        import yaml
        data = yaml.safe_load(raw.decode("utf-8")) or {}
    data.setdefault("id", p.stem)
    data["version"] = _version(raw)
    return data


def render(card: dict) -> str:
    """把卡渲染成一段可注入 system 的文本（稳定块）。"""
    lines = ["【角色卡 {}】".format(card.get("version", ""))]
    mapping = [("role", "身份"), ("goal", "目标"), ("public_identity", "公开身份"),
               ("private_info", "私有信息"), ("risk_appetite", "风险偏好"),
               ("style", "沟通风格"), ("trust_initial", "信任初值"),
               ("win_condition", "胜利条件")]
    for key, label in mapping:
        val = card.get(key)
        if val:
            lines.append("- {}：{}".format(label, val))
    forb = card.get("forbidden") or []
    if forb:
        lines.append("- 不可违反：" + "；".join(str(x) for x in forb))
    return "\n".join(lines)


def load_dir(path: str = "") -> dict:
    """读一目录下所有卡，返回 {id: card}。"""
    d = Path(path) if path else CARDS_DIR
    if not d.is_absolute():
        d = ROOT / d
    out = {}
    if not d.is_dir():
        return out
    for p in sorted(list(d.glob("*.yaml")) + list(d.glob("*.yml")) + list(d.glob("*.json"))):
        try:
            card = load(str(p))
            out[card["id"]] = card
        except Exception:
            continue
    return out