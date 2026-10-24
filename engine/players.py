"""玩家：MockPlayer（规则型基线，零成本、可复现）与 LLMPlayer（真实模型）。"""
from __future__ import annotations

import os
import random
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# providers 放在 server/ 下（HTTP 服务与引擎共用同一个调用适配层）
sys.path.insert(0, os.path.join(_ROOT, "server"))

import providers  # noqa: E402
from engine import prompts  # noqa: E402

SPEECH_TEMPLATES = [
    "我这边信息不多，先听别人说。座位 {} 的发言有点急，我先记一下。",
    "我建议大家盯紧座位 {}，他昨天一直在带节奏。",
    "我是好人。昨天票型里座位 {} 很可疑，我倾向于投他。",
    "昨天死人的位置很关键，我怀疑是座位 {} 干的。",
    "先别急着冲，我认为座位 {} 需要解释一下自己的行为。",
]


class Player:
    """玩家接口：act(view, error) -> (action: dict, meta: dict)。"""

    def __init__(self, seat: int, role: str):
        self.seat = seat
        self.role = role

    def act(self, view: dict, error: str | None = None, on_delta=None) -> tuple[dict, dict]:
        raise NotImplementedError


class MockPlayer(Player):
    """规则型基线：行为完全由 (seed, 座位) 决定，用于无 Key 跑通与做对照。"""

    def __init__(self, seat: int, role: str, seed: int = 0, name: str = ""):
        super().__init__(seat, role)
        self.rng = random.Random(seed * 1000 + seat)
        self.name = name or "mock"
        self._checked: set[int] = set()

    def _others(self, view: dict) -> list[int]:
        return [s for s in view.get("alive", []) if s != self.seat]

    def act(self, view: dict, error: str | None = None, on_delta=None) -> tuple[dict, dict]:
        ctx = view.get("context")
        others = self._others(view)

        if ctx == "wolf_speak":
            mates = [s for s in (view.get("teammates") or [])]
            target = self.rng.choice(others) if others else None
            if target is None:
                return {"kind": "pass"}, {"policy": "mock"}
            text = "我打算刀 {} 号。{}".format(
                target, "他发言最跳，先解决。" if self.rng.random() < 0.5 else "把他票出去更省事。")
            return {"kind": "speak", "text": text[: int(view.get("wolf_chat_max_chars", 120))]}, {"policy": "mock"}

        if ctx == "night_wolf":
            mates = set(view.get("teammates") or [])
            prey = [s for s in others if s not in mates]
            if not prey:
                return {"kind": "pass"}, {"policy": "mock"}
            target = self.rng.choice(prey)
            return {"kind": "kill", "target": target, "reason": "随机刀"}, {"policy": "mock"}

        if ctx == "night_guard":
            pool = [s for s in view.get("alive", []) if s != view.get("guard_last")]
            if not pool:
                return {"kind": "pass"}, {"policy": "mock"}
            # 自守与守人都允许，随机
            return {"kind": "guard", "target": self.rng.choice(sorted(pool))}, {"policy": "mock"}

        if ctx == "night_seer":
            pool = [s for s in others if s not in self._checked] or others
            if not pool:
                return {"kind": "check", "target": 1}, {"policy": "mock"}
            target = self.rng.choice(sorted(pool))
            self._checked.add(target)
            return {"kind": "check", "target": target}, {"policy": "mock"}

        if ctx == "night_witch":
            stock = view.get("witch_stock") or {}
            victim = view.get("wolf_victim")
            if victim and int(stock.get("antidote", 0)) > 0 and self.rng.random() < 0.7:
                return {"kind": "save", "target": victim, "reason": "救人"}, {"policy": "mock"}
            if int(stock.get("poison", 0)) > 0 and others and self.rng.random() < 0.3:
                return {"kind": "poison", "target": self.rng.choice(others)}, {"policy": "mock"}
            return {"kind": "pass"}, {"policy": "mock"}

        if ctx == "last_words":
            suspect = self.rng.choice(others) if others else self.seat
            return ({"kind": "speak",
                     "text": "我是{}号，临死前提醒大家：{}号不对劲，别放过他。".format(self.seat, suspect)},
                    {"policy": "mock"})

        if ctx == "day_speak":
            if not others:
                return {"kind": "pass"}, {"policy": "mock"}
            suspect = self.rng.choice(others)
            text = self.rng.choice(SPEECH_TEMPLATES).format(suspect)
            return {"kind": "speak", "text": text[: int(view.get("max_chars", 220))]}, {"policy": "mock"}

        if ctx == "day_vote":
            mates = set(view.get("teammates") or [])
            pool = [s for s in others if s not in mates] or others
            if not pool:
                return {"kind": "abstain"}, {"policy": "mock"}
            return {"kind": "vote", "target": self.rng.choice(pool)}, {"policy": "mock"}

        if ctx == "hunter":
            if not others:
                return {"kind": "pass"}, {"policy": "mock"}
            return {"kind": "shoot", "target": self.rng.choice(others)}, {"policy": "mock"}

        return {"kind": "pass"}, {"policy": "mock"}


class LLMPlayer(Player):
    """真实模型玩家：一次动作 = 一次 chat 调用 + 结构化解析。"""

    def __init__(self, seat: int, role: str, model_conf: dict,
                 temperature: float | None = None, max_tokens: int | None = None,
                 timeout: float = 90.0):
        super().__init__(seat, role)
        self.conf = dict(model_conf or {})
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = float(timeout)
        self.calls = 0

    @staticmethod
    def _finish_reason(resp: dict, protocol: str) -> str:
        """识别"输出被预算截断"，避免把它当成模型的错。"""
        if protocol == "chat_completions":
            choices = resp.get("choices") or []
            if choices:
                return str(choices[0].get("finish_reason") or "")
        if protocol == "responses":
            details = resp.get("incomplete_details") or {}
            if details.get("reason") == "max_output_tokens":
                return "length"
            if resp.get("status") == "incomplete":
                return "length"
        return ""

    def act(self, view: dict, error: str | None = None, on_delta=None) -> tuple[dict, dict]:
        payload = dict(view)
        if error:
            payload["error"] = error
        messages = prompts.build_messages(payload)
        started = time.time()
        protocol = providers.resolve_protocol(self.conf)
        raw_budget = view.get("budget")
        if isinstance(raw_budget, dict):        # 兼容旧格式（thinking/answer 拆分）
            budget = int(raw_budget.get("thinking", 0) or 0) + int(raw_budget.get("answer", 0) or 0)
        else:
            budget = int(raw_budget or self.max_tokens or 2048)
        # 思考闸门已撤：不再传 thinking_cap，模型爱想多久想多久，由 4 分钟回合上限兜底
        timeout = self.timeout
        force_direct = False
        meta = {"policy": "llm", "model": self.conf.get("model", ""),
                "protocol": protocol, "parse_ok": False, "latency_ms": 0,
                "raw": "", "error": "", "finish_reason": "", "retried": 0}

        for attempt in range(3):
            # 只有重试才需要清空（首次调用是新的回合，页面按 key 自然切换）
            if on_delta is not None and attempt > 0:
                try:
                    on_delta("reset", str(attempt))
                except Exception:
                    pass
            if force_direct:
                payload = dict(view)
                payload["force_direct"] = True
                if error:
                    payload["error"] = error
                messages = prompts.build_messages(payload)
            try:
                resp = providers.call_chat(
                    self.conf, messages,
                    temperature=0.0 if self.temperature is None else self.temperature,
                    max_tokens=budget,
                    timeout=timeout,
                    on_delta=on_delta,
                )
            except providers.ProviderError as exc:
                text = str(exc)
                # 超时不算模型的错：放大时间预算重试一次
                if attempt == 0 and ("超时" in text or "timed out" in text.lower()):
                    timeout = timeout * 2
                    self.timeout = timeout      # 记住这个模型慢，后续轮次不再吃亏
                    meta["retried"] += 1
                    meta["error"] = text
                    continue
                meta["latency_ms"] = int((time.time() - started) * 1000)
                meta["error"] = text
                return {}, meta
            except Exception as exc:  # pragma: no cover
                meta["latency_ms"] = int((time.time() - started) * 1000)
                meta["error"] = repr(exc)
                return {}, meta

            text = providers.extract_text(resp, protocol)
            reasoning = providers.extract_reasoning(resp, protocol)
            finish = self._finish_reason(resp, protocol)
            action = prompts.parse_action(text)
            self.calls += 1
            meta.update({"parse_ok": bool(action), "raw": text[:4000],
                         "reasoning": reasoning[:20000], "finish_reason": finish,
                         "latency_ms": int((time.time() - started) * 1000)})
            if action:
                return action, meta

            # 情况一：正文为空（不管有没有思考内容，都要重试）
            if not text.strip() and attempt < 2:
                meta["retried"] += 1
                meta["empty_text"] = True
                if reasoning.strip():
                    # 想了但没说：保持额度，要求直接回答
                    force_direct = True
                    meta["error"] = "只输出了思考（{} 字），正文为空；要求直接回答后重试".format(
                        len(reasoning))
                else:
                    # 整段空：放大输出预算 + 退回非流式
                    budget = min(budget * 2, 16384)
                    on_delta = None
                    meta["error"] = "模型返回空响应；放大输出预算并用非流式重试"
                continue

            # 情况二：输出被预算截断导致 JSON 不完整
            if finish == "length" and attempt < 2:
                budget = min(budget * 2, 16384)
                meta["retried"] += 1
                continue

            if not text.strip():
                meta["empty_text"] = True
                meta["error"] = "模型返回了空正文"
            return {}, meta
        return {}, meta
