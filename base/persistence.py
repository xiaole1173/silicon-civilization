"""对局持久化：把会话快照落盘，重启后可恢复列表与回放（可选续跑）。

设计：
  - 每回合结束、对局结束各存一次快照（runs/state/<sid>.json）；
  - 快照只存"重建所需"的内容：参与者、消息、回合、世界状态、指标；
  - 服务启动时懒加载快照，让历史对局重新出现在列表里（只读）；
  - 场景插件可选实现 resume(session) 支持真正续跑。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "runs" / "state"


def path_for(sid: str) -> Path:
    return STATE_DIR / (sid + ".json")


_META_KEYS = ("turn", "metrics", "outcome", "collapse", "contracts",
              "agent_roles", "alive", "sheriff", "revealed", "world")


def _meta_payload(session) -> dict:
    """meta 里可能挂着 World 对象：转成快照再序列化。"""
    out = {}
    for k, v in (session.meta or {}).items():
        if k not in _META_KEYS:
            continue
        if hasattr(v, "snapshot"):
            try:
                out[k] = v.snapshot()
                continue
            except Exception:
                continue
        out[k] = v
    return out


def save(session) -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": session.id,
        "title": session.title,
        "scenario": getattr(session.scenario, "id", ""),
        "config": session.config,
        "state": session.state,
        "winner": session.winner,
        "agents": [{"id": a.id, "name": a.name,
                    "model": a.model_conf.get("model", ""),
                    "protocol": a.model_conf.get("protocol", ""),
                    "api_base": a.model_conf.get("api_base", ""),
                    "persona": a.persona}
                   for a in session.agents.values()],
        "messages": [dict(m.to_dict()) for m in session.messages],
        "rounds": session.rounds,
        "meta": _meta_payload(session),
        "reputation": dict(session.reputation or {}),
    }
    p = path_for(session.id)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, p)
    return str(p)


def load_all() -> list:
    if not STATE_DIR.is_dir():
        return []
    out = []
    for p in sorted(STATE_DIR.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                out.append(json.load(fh))
        except Exception:
            continue
    return out


def load(sid: str):
    p = path_for(sid)
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None

def restore(data: dict, plugin) -> object:
    """把快照重建为 Session（不启动线程，只用于查看/续跑）。"""
    from base.message import Message
    from base.session import Agent, Session
    from base.world import World

    sess = Session(data.get("id"), data.get("title", ""), plugin,
                   data.get("config") or {}, truncate_log=False)
    for a in data.get("agents") or []:
        sess.agents[a["id"]] = Agent(id=a["id"], name=a.get("name", ""),
                                     model_conf={"model": a.get("model", ""),
                                                 "protocol": a.get("protocol", ""),
                                                 "api_base": a.get("api_base", "")},
                                     persona=a.get("persona", ""))
    for m in data.get("messages") or []:
        msg = Message(id=m.get("id", ""), seq=m.get("seq", 0),
                      channel=m.get("channel", "public"), sender=m.get("sender"),
                      sender_name=m.get("sender_name", ""), kind=m.get("kind", "speak"),
                      text=m.get("text", ""), thinking=m.get("thinking", ""),
                      meta=m.get("meta") or {}, ts=m.get("ts", 0.0))
        sess.messages.append(msg)
        sess._seq = max(sess._seq, msg.seq)
    sess.rounds = data.get("rounds") or []
    meta = dict(data.get("meta") or {})
    if isinstance(meta.get("world"), dict):
        meta["world"] = World.from_snapshot(meta["world"])
    sess.meta = meta
    sess.reputation = {int(k): v for k, v in (data.get("reputation") or {}).items()}
    sess.state = data.get("state", "ended")
    if sess.state == "running":
        sess.state = "paused"
    sess.winner = data.get("winner")
    return sess
