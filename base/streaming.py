"""极简发布订阅：给 SSE 用。

一个会话一个 Broker，订阅者拿到队列；发布即入队，不阻塞写入方。
"""
from __future__ import annotations

import queue
import threading


class Broker:
    def __init__(self) -> None:
        self._subs: list = []
        self._lock = threading.Lock()
        self.closed = False

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=10000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass

    def close(self) -> None:
        self.closed = True
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait({"type": "session", "state": "closed"})
            except queue.Full:
                pass
