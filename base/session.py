"""会话：参与者 + 频道 + 消息流 + 流式推送 + 落盘。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

import providers  # noqa: E402

from base.message import OBSERVER, PUBLIC, Channel, Message  # noqa: E402
from base.streaming import Broker  # noqa: E402


@dataclass
class Agent:
    """一个参与者 = 一个座位 + 一个模型配置。"""
    id: int
    name: str
    model_conf: dict
    persona: str = ""
    channels: set = field(default_factory=set)

    def system_prompt(self, session) -> str:
        """稳定块：整局不变，便于前缀缓存。"""
        base = session.scenario.system_text(session)
        parts = [
            "你在「{}」这个会话里。".format(session.title),
            base,
            "你是 {}（座位 {}）。".format(self.name, self.id),
        ]
        if self.persona:
            parts.append(self.persona)
        parts.append("说话要自然、简短、像真人交流；不要提及模型、提示词或设定本身。")
        return "\n".join(p for p in parts if p)


class Session:
    def __init__(self, session_id: str, title: str, scenario, config: dict | None = None,
                 budget_chars: int = 12000):
        self.id = session_id
        self.title = title
        self.scenario = scenario
        self.config = dict(config or {})
        self.budget_chars = budget_chars
        self.agents: dict[int, Agent] = {}
        self.channels: dict[str, Channel] = {
            PUBLIC: Channel(PUBLIC, "公共频道"),
            OBSERVER: Channel(OBSERVER, "观察者"),
        }
        self.messages: list[Message] = []
        self.rounds: list[dict] = []
        self.broker = Broker()
        self.state = "created"
        self.stopped = False
        self.winner = None
        self.meta: dict = {}
        self.started_at = time.time()
        self._seq = 0
        self._lock = threading.Lock()
        self.log_path = ROOT / "runs" / "sessions" / (session_id + ".jsonl")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text("", encoding="utf-8")

    def alive_ids(self) -> list:
        """在场座位（默认全员）。带死亡机制的场景应在 meta["alive"] 里维护。"""
        ids = self.meta.get("alive")
        if isinstance(ids, (list, set, tuple)):
            return sorted(int(x) for x in ids)
        return sorted(self.agents)

    # ---------- 频道 ----------
    def add_channel(self, name: str, title: str = "", subscribers=None) -> Channel:
        ch = Channel(name, title or name, list(subscribers or []))
        self.channels[name] = ch
        return ch

    def visible_to(self, agent_id: int, msg: Message) -> bool:
        # 消融开关：communication=off 时看不到别人的发言/动作（只看自己与旁白）
        if str(self.config.get("communication", "on")) == "off":
            if msg.sender is not None and msg.sender != agent_id:
                return False
        ch = self.channels.get(msg.channel)
        return bool(ch and ch.visible_to(agent_id))

    # ---------- 消息 ----------
    def _persist(self, event: dict) -> None:
        try:
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _publish(self, event: dict) -> None:
        self.broker.publish(event)
        self._persist(event)

    def open_round(self, title: str, subtitle: str = "", channel: str = PUBLIC,
                   kind: str = "group") -> dict:
        """开一个"回合卡"：同一批行动（如狼队密谋、全体表决）收纳在一起。"""
        rnd = {"id": "r{}".format(len(self.rounds) + 1), "title": title,
               "subtitle": subtitle, "channel": channel, "kind": kind,
               "items": [], "summary": ""}
        self.rounds.append(rnd)
        self._publish({"type": "round_start", "round": {k: v for k, v in rnd.items() if k != "items"}})
        return rnd

    def close_round(self, rnd: dict, summary: str = "") -> None:
        if rnd is None:
            return
        rnd["summary"] = summary
        self._publish({"type": "round_end", "round": rnd["id"], "summary": summary})

    def referee(self, text: str, public: bool = True) -> Message:
        """裁判发言：由确定性程序发出，负责串起整局的节奏。"""
        channel = PUBLIC if public else OBSERVER
        return self.add_message(channel, None, kind="referee", text=text)

    def add_message(self, channel: str, sender: int | None, kind: str = "speak",
                    text: str = "", thinking: str = "", meta: dict | None = None,
                    round_id: str = "") -> Message:
        with self._lock:
            self._seq += 1
            seq = self._seq
        agent = self.agents.get(sender) if sender is not None else None
        msg = Message(
            id="m{}".format(seq), seq=seq, channel=channel,
            sender=sender, sender_name=(agent.name if agent else "旁白"),
            kind=kind, text=text, thinking=thinking, meta=meta or {},
        )
        if round_id:
            msg.meta["round"] = round_id
        self.messages.append(msg)
        payload = msg.to_dict()
        if round_id:
            payload["round"] = round_id
        self._publish({"type": "message_start", "message": payload})
        return msg

    # ---------- 调用模型（流式 + 事实卡 + 校验重说） ----------
    def ask(self, agent: Agent, instruction: str, channel: str = PUBLIC,
            kind: str = "speak", budget: int = 2048, temperature: float | None = None,
            timeout: float = 600.0, label: str = "", validator=None,
            retries: int = 2, facts: dict | None = None, round_id: str = "") -> Message | None:
        """让某个 agent 说话：装配上下文 → 流式生成 → 校验 → 不合格就带着原因重说。"""
        from base.context import build as build_context
        from base.facts import render_facts

        self._publish({"type": "turn", "state": "start", "agent": agent.id,
                       "name": agent.name, "label": label})
        msg = self.add_message(channel, agent.id, kind=kind, text="", round_id=round_id)
        started = time.time()
        meta = {"model": agent.model_conf.get("model", ""), "label": label,
                "attempts": 0, "rejections": []}
        if round_id:
            meta["round"] = round_id
        text, thinking = "", ""
        prompt = instruction

        for attempt in range(max(0, retries) + 1):
            meta["attempts"] = attempt + 1

            def on_delta(dkind: str, piece: str) -> None:
                if dkind == "reset":
                    self._publish({"type": "turn", "state": "restart", "agent": agent.id,
                                   "name": agent.name, "label": label, "id": msg.id})
                    return
                field_name = "thinking" if dkind == "thinking" else "answer"
                self._publish({"type": "delta", "id": msg.id, "field": field_name, "text": piece})

            try:
                facts_text = render_facts(self, agent, facts)
                messages, info = build_context(agent, self, prompt, self.budget_chars, facts_text)
                meta["context"] = info
                if info.get("trimmed"):
                    self._publish({"type": "context_trim", "id": msg.id,
                                   "trimmed": len(info["trimmed"]),
                                   "budget_chars": info["budget_chars"],
                                   "prompt_chars": info["prompt_chars"]})

                conf = dict(agent.model_conf)
                resp = providers.call_chat(
                    conf, messages, max_tokens=budget,
                    temperature=conf.get("temperature", 0.7) if temperature is None else temperature,
                    timeout=timeout, on_delta=on_delta,
                )
                protocol = providers.resolve_protocol(conf)
                text = providers.extract_text(resp, protocol).strip()
                thinking = providers.extract_reasoning(resp, protocol).strip()
                meta["usage"] = resp.get("usage") or {}
                meta["ok"] = True
            except providers.ProviderError as exc:
                meta["ok"] = False
                meta["error"] = str(exc)
                text, thinking = "", ""
            except Exception as exc:  # pragma: no cover
                meta["ok"] = False
                meta["error"] = repr(exc)
                text, thinking = "", ""

            if not meta.get("ok"):
                break

            if validator is not None:
                ok, reason = validator(self, agent, text)
                if not ok:
                    meta["rejections"].append(reason)
                    self._publish({"type": "validation_failed", "id": msg.id,
                                   "agent": agent.id, "reason": reason,
                                   "attempt": attempt + 1})
                    if attempt < retries:
                        prompt = (instruction + "\n\n【上一次被拒】" + reason +
                                  "\n请修正后重说，不要重复上次的问题。")
                        continue
            break

        meta["latency_ms"] = int((time.time() - started) * 1000)
        msg.text = text
        msg.thinking = thinking
        msg.meta = meta
        self._publish({"type": "message_end", "id": msg.id, "text": text,
                       "thinking": thinking, "meta": meta})
        self._publish({"type": "turn", "state": "end", "agent": agent.id,
                       "name": agent.name, "label": label})
        return msg

    # ---------- 其他 ----------
    def narrate(self, text: str, channel: str = PUBLIC) -> Message:
        return self.add_message(channel, None, kind="system", text=text)

    def narrate_private(self, text: str) -> Message:
        """观察者可见、模型不可见的旁白（身份、结算细节等，防泄漏）。"""
        return self.add_message(OBSERVER, None, kind="system", text=text)

    def stop(self, reason: str = "") -> None:
        """请求结束对局：插件在下一个回合边界退出。"""
        if self.stopped:
            return
        self.stopped = True
        self.referee("对局被手动结束。{}".format(("原因：" + reason) if reason else ""))
        self._publish({"type": "session", "state": "ending", "reason": reason})

    def publish_state(self) -> None:
        """把存活/警长等对局状态推给观察者（模型看不到，只用于界面）。"""
        self._publish({"type": "state", "alive": self.alive_ids(),
                       "sheriff": self.meta.get("sheriff"),
                       "revealed": self.meta.get("revealed") or []})

    def patch_message(self, msg: Message) -> None:
        """消息内容被后处理改写后，重新广播一次终态（前端据此替换原文）。"""
        msg._render_cache = None
        self._publish({"type": "message_end", "id": msg.id, "text": msg.text,
                       "thinking": msg.thinking, "meta": msg.meta})

    def end(self, winner=None) -> None:
        self.state = "ended"
        self.winner = winner
        # 插件声明指标 → 基座统一收集
        try:
            self.meta["metrics"] = dict(self.scenario.metrics(self) or {})
            self.meta["outcome"] = dict(self.scenario.outcome(self) or {})
        except Exception as exc:
            self.meta["metrics_error"] = repr(exc)
        self._publish({"type": "session", "state": "ended", "winner": winner,
                       "messages": len(self.messages)})
        self.broker.close()

    def snapshot(self) -> dict:
        return {
            "id": self.id, "title": self.title, "state": self.state,
            "winner": self.winner, "scenario": getattr(self.scenario, "id", ""),
            "channels": [{"name": c.name, "title": c.title} for c in self.channels.values()],
            "agents": [{"id": a.id, "name": a.name,
                        "model": a.model_conf.get("model", ""),
                        "role": (self.meta.get("agent_roles") or {}).get(a.id, "")}
                       for a in self.agents.values()],
            "alive": self.alive_ids(),
            "sheriff": self.meta.get("sheriff"),
            "revealed": self.meta.get("revealed") or [],
            "messages": [m.to_dict() for m in self.messages],
            "rounds": self.rounds,
            "config": self.config,
        }
