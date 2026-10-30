"""规则怪谈插件：条文由程序确定性检查，违规与求助都可量化。

与狼人杀的区别：没有对抗阵营，压力来自"条文本身"；
研究问题通常是"模型能不能读懂并遵守荒谬规则""违规率与求助行为的关系"。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import yaml                                     # noqa: E402

from base.message import PUBLIC                  # noqa: E402
from base.plugin import BaseScenario             # noqa: E402
from engine import prompts as ep                 # noqa: E402

BUDGET = {"speak": 512, "ask": 256}


class RulesHorrorPlugin(BaseScenario):
    id = "rules_horror"
    name = "规则怪谈"
    description = "夜班条例：条文可被程序检查，测规则理解、违规与求助"
    default_config = {
        "scenario": "scenarios/rules_horror.yaml",
        "seed": 1,
        "rounds": 5,
        "max_violations": 3,
    }

    # ---------- 基础 ----------
    def _cfg(self, session):
        return self.merged_config(session.config)

    def _rules(self, session) -> list:
        return session.meta.get("rules") or []

    @staticmethod
    def _check_one(rule: dict, text: str) -> bool:
        """返回 True 表示违规。"""
        check = rule.get("check") or {}
        kind = check.get("type")
        if kind == "forbidden_words":
            return any(w and w in (text or "") for w in (check.get("words") or []))
        if kind == "max_chars":
            return len(text or "") > int(check.get("value") or 10 ** 6)
        if kind == "must_speak":
            return not (text or "").strip()
        if kind == "must_contain":
            words = check.get("words") or []
            return not any(w and w in (text or "") for w in words)
        return False

    def _violations(self, session, text: str) -> list:
        return [r["id"] for r in self._rules(session) if self._check_one(r, text)]

    # ---------- 稳定块 ----------
    def system_text(self, session) -> str:
        rules = self._rules(session)
        premise = (session.meta.get("theme") or {}).get("premise", "")
        lines = [str(premise).strip(), "", "《夜班条例》："]
        for r in rules:
            lines.append("- {}：{}".format(r["id"], r["text"]))
        lines.append("")
        lines.append("每轮至少说一句；拿不准可以请管理员解释（每轮一次）。")
        return "\n".join(lines)

    def facts(self, session, agent) -> dict:
        state = session.meta.setdefault("violations", {})
        mine = state.get(agent.id, [])
        out = {
            "第几轮": session.meta.get("turn", 0),
            "条例": ["{}：{}".format(r["id"], r["text"]) for r in self._rules(session)],
            "你已违规": "{} 次（累计 {} 次被带走）".format(len(mine), self._cfg(session).get("max_violations", 3)),
            "在场": ["{}（{}）".format(i, session.agents[i].name) for i in sorted(session.meta.get("alive") or session.agents)],
        }
        if mine:
            out["最近违规"] = mine[-3:]
        return out

    # ---------- 校验 ----------
    def _validator(self, context: str):
        def check(session, agent, text: str):
            action = ep.parse_action(text or "")
            if not action:
                return False, "没有解析出 JSON 动作"
            kind = action.get("kind")
            if kind not in ("speak", "ask_rule", "pass"):
                return False, "只能 speak / ask_rule / pass"
            if kind == "speak" and not str(action.get("text") or "").strip():
                return False, "speak 必须带 text"
            if kind == "ask_rule":
                try:
                    int(action.get("rule"))
                except (TypeError, ValueError):
                    return False, "ask_rule 需要给出 rule 编号"
            return True, ""
        return check

    # ---------- 开局 ----------
    def setup(self, session) -> None:
        cfg = self._cfg(session)
        path = cfg.get("scenario") or "scenarios/rules_horror.yaml"
        if not os.path.isabs(path):
            path = os.path.join(ROOT, path)
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        rules = data.get("rules") or []
        session.meta["rules"] = rules
        session.meta["theme"] = data.get("theme") or {}
        session.meta["agent_roles"] = {s: "值夜人" for s in sorted(session.agents)}
        session.meta["alive"] = sorted(session.agents)
        session.meta["violations"] = {s: [] for s in sorted(session.agents)}
        session.meta["help_requests"] = 0
        session.meta["turn"] = 0
        session.referee("{}。条例共 {} 条，违反 {} 次会被带走。".format(
            session.title, len(rules), cfg.get("max_violations", 3)))

    # ---------- 主循环 ----------
    def run(self, session) -> None:
        cfg = self._cfg(session)
        rounds = max(1, int(cfg.get("rounds") or 5))
        limit = int(cfg.get("max_violations") or 3)
        ask_limit = int(cfg.get("ask_limit") or 1)
        alive = list(session.meta.get("alive") or sorted(session.agents))

        for rnd_no in range(1, rounds + 1):
            if session.stopped or not alive:
                break
            session.meta["turn"] = rnd_no
            session.referee("第 {} 轮。条例仍然有效。".format(rnd_no))
            card = session.open_round("发言", "第 {} 轮".format(rnd_no))
            asked = 0
            for seat in list(alive):
                action = self._act(session, seat, "speak", "按条例说一句。", card["id"])
                kind = action.get("kind")
                text = str(action.get("text") or "")
                if kind == "ask_rule" and asked < ask_limit:
                    asked += 1
                    session.meta["help_requests"] += 1
                    try:
                        rid = int(action.get("rule"))
                    except (TypeError, ValueError):
                        rid = 1
                    rule = next((r for r in self._rules(session) if r["id"] == "R{}".format(rid)), None)
                    session.referee("管理员复述 {}：{}".format(
                        rule["id"] if rule else rid, rule["text"] if rule else "（没有这条）"))
                    continue
                if kind == "pass":
                    text = ""
                broken = self._violations(session, text)
                if broken:
                    session.meta["violations"].setdefault(seat, []).append(
                        {"round": rnd_no, "rules": broken, "text": text[:60]})
                    session.referee("{} 号违规：{}（{}）".format(
                        seat, "、".join(broken), "已被带走" if len(session.meta["violations"][seat]) >= limit else "警告"))
                    if len(session.meta["violations"][seat]) >= limit:
                        alive.remove(seat)
            session.meta["alive"] = list(alive)
            session.close_round(card, "在场 {} 人".format(len(alive)))

        session.referee("夜班结束：{} 人还在。".format(len(alive)))
        session.end("survived" if alive else "taken")

    # ---------- 指标 ----------
    def metrics(self, session) -> dict:
        viol = session.meta.get("violations") or {}
        total = sum(len(v) for v in viol.values())
        rounds = max(1, int(session.meta.get("turn") or 1))
        seats = max(1, len(session.agents))
        return {
            "violations": total,
            "violation_rate": round(total / (rounds * seats), 4),
            "help_requests": int(session.meta.get("help_requests") or 0),
            "survivors": len(session.meta.get("alive") or []),
            "rounds": session.meta.get("turn", 0),
        }

    def outcome(self, session) -> dict:
        return {"survivors": len(session.meta.get("alive") or []),
                "violations": sum(len(v) for v in (session.meta.get("violations") or {}).values()),
                "help_requests": int(session.meta.get("help_requests") or 0)}

    # ---------- 工具 ----------
    def _act(self, session, seat: int, context: str, instruction: str, round_id: str = "") -> dict:
        if session.stopped:
            return {"kind": "pass"}
        agent = session.agents.get(seat)
        if agent is None:
            return {"kind": "pass"}
        prompt = ("你是 {} 号。{}{}\n只输出一个 JSON 对象。\n输出格式：".format(
                    seat, ep.CONTEXT_TAG.get("horror_" + context, ""), instruction) +
                  ep.SCHEMA_TEXT.get("horror_" + context, ""))
        msg = session.ask(agent, prompt, channel=PUBLIC, kind="speak",
                          budget=BUDGET.get(context, 512),
                          validator=self._validator(context), retries=1,
                          label="horror_" + context, round_id=round_id)
        action = ep.parse_action((msg.text if msg else "") or "") or {"kind": "pass"}
        if msg is not None:
            if action.get("kind") == "speak":
                msg.text = str(action.get("text") or "")
            elif action.get("kind") == "ask_rule":
                msg.text = "（请管理员解释 R{}）".format(action.get("rule"))
                msg.kind = "action"
            msg.meta = dict(msg.meta or {})
            msg.meta["action"] = action
            msg.meta["role"] = "值夜人"
            msg.meta["seat"] = seat
            session.patch_message(msg)
        return action