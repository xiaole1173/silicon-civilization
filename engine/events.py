"""事件日志：JSONL，一行一个事件，供回放台与审计使用。

刻意不写入墙上时钟，保证同 seed 重跑得到逐字节相同的事件流，方便做确定性回归测试。
需要真实时间时用 time 字段（只在 run_meta 里出现一次，不参与对比）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path


class LiveLog:
    """逐块增量日志：模型一边生成一边写，页面轮询它就能看到"打字"过程。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def emit(self, **fields) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(fields, ensure_ascii=False) + "\n")
        except Exception:
            pass


class EventLog:
    def __init__(self, path: str | Path | None = None):
        self.events: list = []
        self.path = Path(path) if path else None
        self.live = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")
            self.live = LiveLog(self.path.with_suffix(".live.jsonl"))

    def emit(self, event_type: str, **fields) -> dict:
        # 参数名不叫 kind，避免与事件字段 kind（动作类型）冲突
        event = {"seq": len(self.events) + 1, "event": event_type}
        event.update(fields)
        self.events.append(event)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def write_meta(self, **fields) -> dict:
        return self.emit("run_meta", recorded_at=time.strftime("%Y-%m-%d %H:%M:%S"), **fields)

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(e, ensure_ascii=False) for e in self.events)
