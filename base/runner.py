"""会话运行器：把插件跑在后台线程里，出错不炸服务。"""
from __future__ import annotations

import threading
import traceback

from base.session import Agent, Session

_SESSIONS: dict[str, Session] = {}
_LOCK = threading.Lock()


def create_session(session_id: str, plugin, config: dict, seats: list, title: str = "") -> Session:
    """seats: [{"name": "...", "model_conf": {...}, "persona": "..."}]"""
    session = Session(session_id, title or plugin.name, plugin, config)
    for idx, seat in enumerate(seats, start=1):
        agent = Agent(
            id=idx,
            name=seat.get("name") or "{}号".format(idx),
            model_conf=dict(seat.get("model_conf") or {}),
            persona=seat.get("persona") or "",
        )
        session.agents[idx] = agent
    with _LOCK:
        _SESSIONS[session_id] = session
    try:
        session.publish_meta()
    except Exception:
        pass
    return session


def get_session(session_id: str) -> Session | None:
    with _LOCK:
        return _SESSIONS.get(session_id)


def stop_session(session_id: str, reason: str = "") -> bool:
    session = get_session(session_id)
    if not session:
        return False
    session.stop(reason)
    return True


def list_sessions() -> list:
    with _LOCK:
        items = list(_SESSIONS.values())
    return [{"id": s.id, "title": s.title, "state": s.state,
             "messages": len(s.messages),
             "scenario": getattr(s.scenario, "id", "")} for s in items]


def start(session: Session, on_error=None) -> threading.Thread:
    def _run():
        session.state = "running"
        session._publish({"type": "session", "state": "running", "id": session.id})
        try:
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
