"""消息与频道：基座的最小数据单元。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

PUBLIC = "public"
OBSERVER = "meta"      # 只有观察者能看到，模型看不到（防信息泄漏）


@dataclass
class Channel:
    """频道：public 所有人可见；其余按订阅者白名单可见。"""
    name: str
    title: str = ""
    subscribers: list = field(default_factory=list)   # 空列表 + public 语义由 session 决定

    def visible_to(self, agent_id: int) -> bool:
        if self.name == PUBLIC:
            return True
        return agent_id in self.subscribers


@dataclass
class Message:
    """一条消息。渲染结果缓存，保证"历史只追加、绝不重写"（前缀可缓存）。"""
    id: str
    seq: int
    channel: str
    sender: int | None
    sender_name: str
    kind: str                  # speak / action / system / narration
    text: str = ""
    thinking: str = ""
    meta: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    _render_cache: str | None = None

    def render(self) -> str:
        """渲染成喂给模型的一行（结果缓存，避免重复拼接导致前缀漂移）。"""
        if self._render_cache is None:
            who = self.sender_name or "系统"
            body = (self.text or "").strip()
            if self.kind == "system":
                self._render_cache = "【旁白】" + body
            else:
                self._render_cache = "{}：{}".format(who, body)
        return self._render_cache

    def to_dict(self) -> dict:
        return {
            "id": self.id, "seq": self.seq, "channel": self.channel,
            "sender": self.sender, "sender_name": self.sender_name,
            "kind": self.kind, "text": self.text, "thinking": self.thinking,
            "meta": self.meta, "ts": self.ts,
        }
