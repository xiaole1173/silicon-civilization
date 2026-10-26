"""公地困境插件：共享资源 + 公开声明 + 取用 + 结算。

基座提供 world（资源/存量/恢复）、metrics（基尼/合作率）、批次与清单；
本插件只负责"每轮问谁、把结果交给 world 结算、由裁判播报"。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from base.message import OBSERVER, PUBLIC          # noqa: E402
from base.plugin import BaseScenario                # noqa: E402
from base.world import Resource, World              # noqa: E402
from engine import prompts as ep                     # noqa: E402

BUDGET = {"declare": 768, "take": 768, "speak": 1024}


class CommonsPlugin(BaseScenario):
    id = "commons"
    name = "公地困境"
    description = "共享草场：公开声明 → 取用 → 结算，测合作与信任"
    default_config = {
        "scenario": "scenarios/commons.yaml",
        "seed": 1,
        "rounds": 8,
        "regen_rate": 0.05,
        "per_round_max": 25,
        "declare": True,
    }

    # ---------- 基础 ----------
    def _cfg(self, session):
        return self.merged_config(session.config)

    def _world(self, session) -> World:
        return session.meta["world"]

    def _fair_share(self, session) -> float:
        w = self._world(session)
        res = next(iter(w.resources.values()))
        n = max(1, len(w.agents))
        mode = str(self._cfg(session).get("fair_share_mode", "sustainable"))
        if mode == "equal":
            return res.cap / n
        return res.cap * res.regen_rate / n

    # ---------- 稳定块 ----------
    def system_text(self, session) -> str:
        cfg = self._cfg(session)
        w = self._world(session)
        res = next(iter(w.resources.values()))
        return (
            "你们共用一片{name}。当前存量 {amount:g}{unit}，上限 {cap:g}{unit}，"
            "每轮自然恢复 {regen:.0%}（约 {gain:g}{unit}）。\n"
            "每轮流程：先当众说明这轮打算取用多少，再实际取用；取用上限 {mx:g}{unit}/轮。\n"
            "草场归零，本局结束且所有人都输。没有人强制你守信。"
        ).format(name=res.name, amount=res.amount, unit=res.unit, cap=res.cap,
                 regen=res.regen_rate, gain=res.cap * res.regen_rate, mx=cfg.get("per_round_max", 25))

    # ---------- 事实卡 ----------
    def facts(self, session, agent) -> dict:
        w = self._world(session)
        res = next(iter(w.resources.values()))
        mine = w.totals(res.name).get(agent.id, 0.0)
        fair = self._fair_share(session)
        out = {
            "资源": "{}（{}）".format(res.name, res.unit),
            "当前存量": "{:g}{}（稀缺度 {:.0%}）".format(res.amount, res.unit, res.scarcity()),
            "每轮恢复": "{:g}{}".format(res.cap * res.regen_rate, res.unit),
            "可持续份额/人": "{:.1f}{}".format(fair, res.unit),
            "你已取用": "{:g}{}".format(mine, res.unit),
            "在场": ["{}（{}）".format(i, session.agents[i].name) for i in sorted(session.agents)],
        }
        if str(session.config.get("info_visibility", "full")) != "self":
            others = {k: v for k, v in w.totals(res.name).items() if k != agent.id}
            if others:
                out["他人累计"] = ["{}号 {:g}".format(k, v) for k, v in sorted(others.items())]
        return out

    # ---------- 校验 ----------
    def _validator(self, context: str):
        def check(session, agent, text: str):
            action = ep.parse_action(text or "")
            if not action:
                return False, "没有解析出 JSON 动作"
            kind = action.get("kind")
            want = {"declare": "declare", "take": "take"}.get(context, context)
            if context == "declare":
                if kind not in ("declare", "pass"):
                    return False, "声明阶段只能 declare 或 pass"
                if kind == "pass":
                    return True, ""
            elif context == "take":
                if kind != "take":
                    return False, "取用阶段只能 take"
            mx = float(self._cfg(session).get("per_round_max", 25))
            try:
                amount = float(action.get("amount"))
            except (TypeError, ValueError):
                return False, "必须给出 amount（数字）"
            if amount < 0 or amount > mx:
                return False, "amount 必须在 0 到 {:g} 之间".format(mx)
            return True, ""

        return check

    # ---------- 开局 ----------
    def setup(self, session) -> None:
        cfg = self._cfg(session)
        res = Resource(name=str(cfg.get("resource", "草料")),
                       amount=float(cfg.get("initial", 100)),
                       cap=float(cfg.get("cap", 100)),
                       regen_rate=float(cfg.get("regen_rate", 0.05)),
                       unit=str(cfg.get("unit", "捆")))
        world = World(resources={res.name: res}, agents=sorted(session.agents))
        session.meta["world"] = world
        session.meta["agent_roles"] = {s: "牧户" for s in sorted(session.agents)}
        session.meta["turn"] = 0
        self._sync(session)
        session.referee("{}：{} 户人家共用一片{}，每轮恢复 {:.0%}。".format(
            session.title, len(world.agents), res.name, res.regen_rate))
        session.referee("初始存量 {:g}{}，可持续份额约 {:.1f}{}/人/轮。".format(
            res.amount, res.unit, self._fair_share(session), res.unit))

    def _sync(self, session) -> None:
        w = self._world(session)
        res = next(iter(w.resources.values()))
        session.meta["alive"] = sorted(w.agents)
        session.publish_world({"round": session.meta.get("turn", 0),
                               "stock": round(res.amount, 2),
                               "cap": res.cap,
                               "scarcity": round(res.scarcity(), 3),
                               "totals": {str(k): v for k, v in w.totals(res.name).items()}})

    # ---------- 主循环 ----------
    def run(self, session) -> None:
        cfg = self._cfg(session)
        world = self._world(session)
        res = next(iter(world.resources.values()))
        rounds = max(1, int(cfg.get("rounds") or 8))
        mx = float(cfg.get("per_round_max", 25))
        collapsed = False
        last_round = 0

        for rnd_no in range(1, rounds + 1):
            if session.stopped:
                break
            last_round = rnd_no
            session.meta["turn"] = rnd_no
            session.referee("第 {} 轮。当前存量 {:g}{}（稀缺度 {:.0%}）。".format(
                rnd_no, res.amount, res.unit, res.scarcity()))

            declared = {}
            if cfg.get("declare", True):
                card = session.open_round("公开声明", "第 {} 轮".format(rnd_no))
                for seat in sorted(session.agents):
                    action = self._act(session, seat, "declare", "先当众说明这轮打算取用多少。",
                                      card["id"])
                    if action.get("kind") == "declare":
                        try:
                            declared[seat] = float(action.get("amount"))
                        except (TypeError, ValueError):
                            declared[seat] = None
                session.close_round(card, "，".join(
                    "{}号 {:g}".format(k, v) for k, v in sorted(declared.items()) if v is not None) or "—")

            card = session.open_round("取用", "第 {} 轮".format(rnd_no))
            taken = {}
            for seat in sorted(session.agents):
                action = self._act(session, seat, "take", "实际取用多少（0–{:g}）。".format(mx),
                                  card["id"])
                amount = action.get("amount")
                try:
                    amount = max(0.0, min(mx, float(amount)))
                except (TypeError, ValueError):
                    amount = 0.0
                event = world.extract(seat, res.name, amount, round_no=rnd_no)
                taken[seat] = event["got"]
            session.close_round(card, "本轮共取 {:.0f}{}".format(sum(taken.values()), res.unit))

            gained = world.settle(round_no=rnd_no)
            session.referee("结算：本轮取走 {:.0f}{}，草场恢复 {:.0f}{}，剩余 {:g}{}（{:.0%}）。".format(
                sum(taken.values()), res.unit, gained.get(res.name, 0), res.unit,
                res.amount, res.unit, res.scarcity()))
            self._sync(session)

            if res.amount <= res.cap * 0.1:
                collapsed = True
                session.referee("草场见底了。这一轮之后再没有草可以割。")
                break

        survived = 0 if collapsed else last_round
        session.referee("对局结束：{}（撑过 {} 轮，期末存量 {:g}{}）。".format(
            "草场崩溃" if collapsed else "草场保住", survived, res.amount, res.unit))
        session.meta["collapse"] = {"collapsed": collapsed, "survived_rounds": survived,
                                    "final_stock": round(res.amount, 2)}
        session.end("collapsed" if collapsed else "sustained")

    # ---------- 指标与结论 ----------
    def metrics(self, session) -> dict:
        from base import metrics as M
        world = self._world(session)
        res = next(iter(world.resources.values()))
        summary = M.summarize(world, resource=res.name,
                              fair_share=self._fair_share(session), threshold=0.1)
        summary["collapse"] = 1 if (session.meta.get("collapse") or {}).get("collapsed") else 0
        summary["survived_rounds"] = (session.meta.get("collapse") or {}).get("survived_rounds", 0)
        # 声明与实际的偏差（信任指标）
        return summary

    def outcome(self, session) -> dict:
        return dict(session.meta.get("collapse") or {})

    # ---------- 工具 ----------
    def _act(self, session, seat: int, context: str, instruction: str, round_id: str = "") -> dict:
        if session.stopped:
            return {"kind": "pass"}
        agent = session.agents.get(seat)
        if agent is None:
            return {"kind": "pass"}
        tag = ep.CONTEXT_TAG.get("commons_" + context, "")
        schema = ep.SCHEMA_TEXT.get("commons_" + context, "")
        prompt = "你是 {} 号。{}{}\n只输出一个 JSON 对象，不要解释。\n输出格式：{}".format(
            seat, tag, instruction, schema)
        msg = session.ask(agent, prompt, channel=PUBLIC, kind="speak",
                          budget=BUDGET.get(context, 768),
                          validator=self._validator(context), retries=1,
                          label="commons_" + context, round_id=round_id)
        raw = (msg.text if msg else "") or ""
        action = ep.parse_action(raw)
        if not action:
            action = {"kind": "pass"}
        if msg is not None:
            if context == "declare" and action.get("kind") == "declare":
                msg.text = "（打算取用 {:g}）".format(float(action.get("amount") or 0))
                msg.kind = "action"
            elif context == "take":
                msg.text = "（取用 {:g}）".format(float(action.get("amount") or 0))
                msg.kind = "action"
            msg.meta = dict(msg.meta or {})
            msg.meta["action"] = action
            msg.meta["role"] = "牧户"
            msg.meta["seat"] = seat
            session.patch_message(msg)
        return action