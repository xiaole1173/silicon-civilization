"""会话运行器：把插件跑在后台线程里，出错不炸服务。"""
from __future__ import annotations

import threading
import traceback

from base.session import Agent, Session

_SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()


def create_session(session_id: str, plugin, config: dict, seats: list, title: str = "") -> Session:
    """seats: [{"name": "...", "model_conf": {...}, "persona": "..."}]"""
    from base import cards as cards_mod

    session = Session(session_id, title or plugin.name, plugin, config)
    use_persona = str((config or {}).get("persona", "on")) != "off"
    for idx, seat in enumerate(seats, start=1):
        persona = seat.get("persona") or ""
        card_version = ""
        try:
            loaded = None
            card = seat.get("card")
            card_path = seat.get("role_card") or ""
            if isinstance(card, dict) and card:
                loaded = dict(card)
                loaded.setdefault("version", "card-inline")
            elif card_path:
                loaded = cards_mod.load(card_path)
            if loaded and use_persona:
                persona = cards_mod.render(loaded)
                card_version = loaded.get("version", "")
        except Exception:
            loaded = None
        if not use_persona:
            persona = ""
            card_version = ""
        agent = Agent(
            id=idx,
            name=seat.get("name") or "{}号".format(idx),
            model_conf=dict(seat.get("model_conf") or {}),
            persona=persona,
            role_card_version=card_version,
        )
        session.agents[idx] = agent
    with _LOCK:
        _SESSIONS[session_id] = session
    try:
        session.publish_meta()
    except Exception:
        pass
    return session


_LOADED = False


def _ensure_loaded() -> None:
    """服务启动后首次访问时，从快照恢复历史对局（只读/可续跑）。"""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        import base.persistence as persistence
        import base.plugin as plugin_mod
        for data in persistence.load_all():
            sid = data.get("id")
            if not sid or sid in _SESSIONS:
                continue
            plugin = plugin_mod.get_plugin(data.get("scenario") or "")
            if plugin is None:
                continue
            try:
                _SESSIONS[sid] = persistence.restore(data, plugin)
            except Exception:
                continue
    except Exception:
        pass


def get_session(session_id: str) -> Session | None:
    _ensure_loaded()
    with _LOCK:
        return _SESSIONS.get(session_id)


def stop_session(session_id: str, reason: str = "") -> bool:
    session = get_session(session_id)
    if not session:
        return False
    session.stop(reason)
    return True


def resume_session(session_id: str) -> bool:
    """从快照继续跑（仅支持插件实现了 resume 语义的场景，如公地）。"""
    sess = get_session(session_id)
    if sess is None or sess.state != "paused":
        return False
    sess.meta["resumed"] = True
    sess.state = "running"
    start(sess, skip_setup=True)
    return True


def list_sessions() -> list:
    _ensure_loaded()
    with _LOCK:
        items = list(_SESSIONS.values())
    return [{"id": s.id, "title": s.title, "state": s.state,
             "messages": len(s.messages),
             "scenario": getattr(s.scenario, "id", "")} for s in items]


def start(session: Session, on_error=None, skip_setup: bool = False) -> threading.Thread:
    def _run():
        session.state = "running"
        session._publish({"type": "session", "state": "running", "id": session.id})
        try:
            if not skip_setup:
                session.scenario.setup(session)
            session.scenario.run(session)
        except Exception as exc:  # pragma: no cover
            traceback.print_exc()
            session.narrate("运行出错：{}".format(exc))
            if on_error:
                on_error(exc)
        finally:
            if session.state != "ended":
                session.end(session.winner)

    thread = threading.Thread(target=_run, name="session-" + session.id, daemon=True)
    thread.start()
    return thread
