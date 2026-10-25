"""狼人杀插件：规则层（engine/）保持纯函数，基座负责上下文与显示。

一次"行动回合"= 一个 round 卡：谁做了什么集中在一起，裁判负责串场。
私密动作走 seat:N 频道，只有本人与观察者能看到（防泄漏）。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from base.message import OBSERVER, PUBLIC                # noqa: E402
from base.plugin import BaseScenario                      # noqa: E402
from engine import prompts as ep                          # noqa: E402
from engine import rules                                  # noqa: E402
from engine.scenario import Scenario                      # noqa: E402
from engine.state import GameState                        # noqa: E402

BUDGET = {
    "wolf_speak": 1024, "night_wolf": 1024, "night_seer": 1024,
    "night_guard": 1024, "night_witch": 1536, "day_speak": 2048,
    "day_vote": 1024, "hunter": 768, "last_words": 1024,
    "sheriff_vote": 1024, "wolf_destruct": 768, "badge": 768, "wolf_king": 768,
}

# 私密动作：只有本人和观察者能看到
SECRET_CONTEXTS = {"night_guard", "night_wolf", "night_seer", "night_witch",
                   "wolf_king", "badge", "hunter"}


class WerewolfPlugin(BaseScenario):
    id = "werewolf"
    name = "狼人杀"
    description = "12/9 人狼人杀：夜晚密商、白天陈述与表决，裁判串场"
    default_config = {
        "scenario": "scenarios/werewolf12_standard.yaml",
        "seed": 1,
        "rounds_per_day": 1,
    }

    ABILITY = {
        "werewolf": "夜里和同伴一起带走一个人，白天要装成村民。",
        "wolf_king": "你是狼王：出局时能开枪带走一人（被毒杀不能）。",
        "white_wolf_king": "你是白狼王：白天可自爆并带走一人；被毒杀不能开枪。",
        "seer": "每夜可以查验一个人是狼还是人。",
        "witch": "一瓶救命药、一瓶致命药，每晚最多用一瓶，不能救自己。",
        "hunter": "被狼杀或被票出时可以开枪带走一人；被毒杀不能开枪。",
        "guard": "每夜可以守一个人，不能连续两晚守同一人。",
        "idiot": "被投票放逐会翻牌免死，但此后失去投票权。",
        "villager": "没有特殊能力，只能靠陈述和表决找狼。",
    }

    # ---------- 基础 ----------
    def _cfg(self, session):
        return self.merged_config(session.config)

    def _state(self, session) -> GameState:
        return session.meta["game"]

    def _scenario(self, session) -> Scenario:
        return self._state(session).scenario

    def _label(self, session, role: str) -> str:
        return self._scenario(session).role_label(role)

    def _sync_alive(self, session) -> None:
        st = self._state(session)
        before = (tuple(session.meta.get("alive") or ()), session.meta.get("sheriff"))
        session.meta["alive"] = sorted(st.alive)
        session.meta["sheriff"] = st.sheriff
        session.meta["revealed"] = sorted(st.revealed)
        after = (tuple(session.meta["alive"]), st.sheriff)
        if before != after:
            session.publish_state()

    # ---------- 稳定块 ----------
    def system_text(self, session) -> str:
        sc = self._scenario(session)
        theme = sc.theme
        roles = "、".join("{}×{}".format(self._label(session, r), n) for r, n in sc.roles.items())
        return (
            "{}\n\n本局 {} 人，角色构成：{}。\n"
            "夜里被咬死或被逐出就是真的死了，不会复活。白天所有人公开陈述，然后表决逐出一人。\n"
            "每次只输出一个 JSON 对象，不要输出其它文字。".format(
                theme.get("premise", "").strip(), sc.players, roles))

    # ---------- 事实卡 ----------
    def facts(self, session, agent) -> dict:
        st = self._state(session)
        seat = agent.id
        role = st.role_of(seat)
        out = {"你的身份": self._label(session, role),
               "你的能力": self.ABILITY.get(role, ""),
               "在场": ["{}（{}）".format(i, session.agents[i].name) for i in sorted(st.alive)]}
        deaths = st.deaths_last_night or []
        if deaths:
            out["昨夜出局"] = ["{}号".format(d["seat"]) for d in deaths]
        if st.is_wolf(seat):
            mates = [s for s in st.alive_wolves() if s != seat]
            if mates:
                out["你的同伴"] = ["{}号".format(s) for s in mates]
        seer = (st.private.get(seat) or {}).get("seer") or []
        if seer:
            out["你的查验"] = ["第{}夜查{}号：{}".format(
                r.get("day"), r.get("target"), "被策反者" if r.get("is_wolf") else "普通人")
                for r in seer[-6:]]
        if role == "witch":
            out["你的药"] = "救命 {} / 致命 {}".format(
                st.witch_stock.get("antidote", 0), st.witch_stock.get("poison", 0))
            if st.meta.get("pending_wolf_target"):
                out["今夜被袭击"] = "{}号".format(st.meta["pending_wolf_target"])
        if role == "guard" and st.guard_last:
            out["昨夜你守的"] = "{}号".format(st.guard_last)
        if st.sheriff:
            out["警长"] = "{}号".format(st.sheriff)
        return out

    # ---------- 校验 ----------
    def _validator(self, context: str):
        def check(session, agent, text: str):
            st = self._state(session)
            action = ep.parse_action(text or "")
            if not action:
                return False, "没有解析出 JSON 动作，请只输出一个 JSON 对象"
            return rules.validate_action(st, agent.id, action, context=context)
        return check

    # ---------- 开局 ----------
    def setup(self, session) -> None:
        cfg = self._cfg(session)
        path = cfg.get("scenario") or "scenarios/werewolf12_standard.yaml"
        if not os.path.isabs(path):
            path = os.path.join(ROOT, path)
        scenario = Scenario.load(path)
        state = GameState.new(scenario, int(cfg.get("seed") or 1))
        session.meta["game"] = state
        session.meta["turn"] = 0

        if len(session.agents) != scenario.players:
            raise ValueError("座位数 {} 与场景人数 {} 不一致".format(
                len(session.agents), scenario.players))

        wolves = [s for s in state.seat_roles if state.role_of(s) in ("werewolf", "wolf_king", "white_wolf_king")]
        session.add_channel("wolves", "狼队密聊", subscribers=wolves)
        for seat in state.seat_roles:
            session.add_channel("seat:{}".format(seat), "{}号私密".format(seat), subscribers=[seat])

        session.meta["agent_roles"] = {
            seat: self._label(session, role) for seat, role in state.seat_roles.items()}
        self._sync_alive(session)
        session.referee("{} · {} 人局，天黑请闭眼。".format(
            scenario.theme.get("name", "本局"), scenario.players))
        layout = "、".join("{}号={}".format(s, self._label(session, r))
                          for s, r in sorted(state.seat_roles.items()))
        session.referee("身份表（仅观察者可见）：" + layout, public=False)

    # ---------- 主循环 ----------
    def run(self, session) -> None:
        st = self._state(session)
        sc = self._scenario(session)
        rounds_per_day = max(1, int(self._cfg(session).get("rounds_per_day") or 1))

        while True:
            if session.stopped:
                session.referee("已停止，本局到此结束。")
                session.end("stopped")
                return
            st.day += 1
            st.phase = "night"
            session.meta["turn"] = st.day
            session.referee("第 {} 夜。".format(st.day))

            guard_target = None
            if st.alive_of("guard"):
                rnd = session.open_round("守卫行动", "第 {} 夜".format(st.day), kind="secret")
                for seat in st.alive_of("guard"):
                    action = self._act(session, seat, "night_guard",
                                       "决定今晚守谁（不能连守同一人）。", round_id=rnd["id"])
                    if action.get("kind") == "guard":
                        guard_target = self._pick_target(session, seat, action) or guard_target
                session.close_round(rnd, "守 {} 号".format(guard_target) if guard_target else "没有守护")

            if (sc.wolf_discussion or {}).get("enabled", True):
                rnd = session.open_round("狼队密谋", "第 {} 夜".format(st.day),
                                         channel="wolves", kind="wolves")
                for r2 in range(1, int((sc.wolf_discussion or {}).get("rounds", 1)) + 1):
                    for seat in sorted(st.alive_wolves()):
                        self._act(session, seat, "wolf_speak",
                                  "夜里私下商议今晚带走谁（第 {} 轮）。".format(r2),
                                  channel="wolves", round_id=rnd["id"])
                session.close_round(rnd)

            rnd = session.open_round("狼人猎杀", "第 {} 夜".format(st.day), kind="secret")
            wolf_votes = {}
            for seat in st.alive_wolves():
                action = self._act(session, seat, "night_wolf", "决定今晚带走谁。", round_id=rnd["id"])
                wolf_votes[seat] = (self._pick_target(session, seat, action)
                                    if action.get("kind") == "kill" else None)
            wolf_target, _detail = rules.resolve_wolf_votes(wolf_votes)
            st.meta["pending_wolf_target"] = wolf_target
            session.close_round(rnd, "目标 {} 号".format(wolf_target) if wolf_target else "没有目标")

            if st.alive_of("seer"):
                rnd = session.open_round("预言家查验", "第 {} 夜".format(st.day), kind="secret")
                for seat in st.alive_of("seer"):
                    action = self._act(session, seat, "night_seer",
                                       "选择一人查验身份。", round_id=rnd["id"])
                    target = self._pick_target(session, seat, action)
                    if target is None:
                        continue
                    is_wolf = st.is_wolf(target)
                    st.private.setdefault(seat, {}).setdefault("seer", []).append(
                        {"day": st.day, "target": target, "is_wolf": is_wolf})
                    session.referee("{} 号查验 {} 号：{}".format(
                        seat, target, "狼" if is_wolf else "好人"), public=False)
                session.close_round(rnd)

            witch_action = {"kind": "pass"}
            if st.alive_of("witch"):
                rnd = session.open_round("女巫用药", "第 {} 夜".format(st.day), kind="secret")
                for seat in st.alive_of("witch"):
                    witch_action = self._act(session, seat, "night_witch",
                                             "是否用药（救命/致命各一瓶）。", round_id=rnd["id"])
                    witch_action["_seat"] = seat
                session.close_round(rnd, {
                    "save": "用解药", "poison": "用毒药", "pass": "没有用药"
                }.get(witch_action.get("kind"), "没有用药"))

            night = rules.resolve_night(st, wolf_target, witch_action, guard_target)
            deaths = rules.apply_deaths(st, night["deaths"])
            st.deaths_last_night = [dict(d) for d in deaths]

            for d in list(deaths):
                self._death_trigger(session, d["seat"], d["cause"])

            if deaths:
                session.referee("天亮了。{} 号出局。".format(
                    "、".join(str(d["seat"]) for d in deaths)))
            else:
                session.referee("天亮了。昨夜是平安夜。")
            detail = []
            if night.get("guarded"):
                detail.append("守卫")
            if night.get("saved"):
                detail.append("女巫救人")
            if night.get("poisoned"):
                detail.append("女巫用毒")
            if night.get("same_night_rescue"):
                detail.append("同守同救")
            session.referee("夜间结算：{}｜触发：{}".format(
                "、".join("{}号={}".format(d["seat"], self._label(session, d["role"]))
                         for d in deaths) or "无死亡",
                "、".join(detail) or "无"), public=False)

            winner = rules.check_win(st)
            if winner:
                break

            # ---------- 白天 ----------
            st.phase = "day"
            session.referee("第 {} 天。".format(st.day))
            sc_sheriff = sc.sheriff or {}
            if st.day == 1 and sc_sheriff.get("enabled"):
                self._elect_sheriff(session)
                winner = rules.check_win(st)
                if winner:
                    break

            if (sc.wolf_self_destruct or {}).get("enabled") and st.alive_wolves():
                if self._try_self_destruct(session):
                    winner = rules.check_win(st)
                    if winner:
                        break
                    continue

            order = sorted(st.alive)
            if sc_sheriff.get("speaks_last", True) and st.sheriff in order:
                order.remove(st.sheriff)
                order.append(st.sheriff)

            for rnd_no in range(1, rounds_per_day + 1):
                rnd = session.open_round("白天陈述", "第 {} 天 · 第 {} 轮".format(st.day, rnd_no))
                for seat in order:
                    if seat not in st.alive:
                        continue
                    self._act(session, seat, "day_speak",
                              "轮到你陈述（第 {} 轮）。".format(rnd_no), round_id=rnd["id"])
                session.close_round(rnd)

            eliminated = self._vote(session)
            if eliminated:
                outcome = rules.resolve_vote_death(st, eliminated)
                if outcome.get("revealed"):
                    session.referee("{} 号翻牌——是白痴，免于出局，此后失去投票权。".format(eliminated))
                    eliminated = None
            if eliminated:
                role_text = self._label(session, st.role_of(eliminated))
                rules.apply_deaths(st, [{"seat": eliminated, "cause": "vote"}])
                reveal = bool((sc.vote or {}).get("reveal_role_on_exit", False))
                session.referee("{} 号被逐出{}。".format(
                    eliminated, "（身份：{}）".format(role_text) if reveal else ""))
                session.referee("{} 号身份：{}".format(eliminated, role_text), public=False)
                self._death_trigger(session, eliminated, "vote")
                if (sc.last_words or {}).get("after_vote", True):
                    rnd = session.open_round("遗言", "第 {} 天".format(st.day))
                    self._act(session, eliminated, "last_words",
                              "你被逐出，这是你最后一次开口。", round_id=rnd["id"])
                    session.close_round(rnd)

            winner = rules.check_win(st)
            if winner:
                break
            if st.day >= int((sc.win or {}).get("max_days", 8)):
                winner = "draw"
                break

        st.winner = winner
        label = {"good": "好人阵营胜利", "werewolves": "狼人阵营胜利", "draw": "平局"}.get(winner, winner)
        session.referee("对局结束：{}（共 {} 天）。".format(label, st.day))
        session.end(winner)

    # ---------- 警长 ----------
    def _elect_sheriff(self, session) -> None:
        """官方流程：上警 → 警上发言 → 可退水 → 警下投票 → 平票 PK 再投。"""
        st = self._state(session)
        conf = self._scenario(session).sheriff or {}

        # ① 上警
        rnd = session.open_round("上警", "第 1 天 · 警长竞选", kind="vote")
        candidates = []
        for seat in sorted(st.alive):
            action = self._act(session, seat, "sheriff_run", "你要不要上警竞选警长？",
                               round_id=rnd["id"])
            if action.get("kind") == "run":
                candidates.append(seat)
        session.close_round(rnd, "上警：{}".format(
            "、".join("{} 号".format(c) for c in candidates) or "无人上警"))
        if not candidates:
            session.referee("无人上警，本局没有警长。")
            return
        session.referee("上警的是 {} 号。".format("、".join(str(c) for c in candidates)))
        st.meta["sheriff_candidates"] = list(candidates)

        # ② 竞选发言
        rnd = session.open_round("竞选发言", "第 1 天", channel="public")
        for seat in candidates:
            if seat not in st.alive:
                continue
            self._act(session, seat, "sheriff_campaign_speak",
                      "你是警上玩家，向警下说明你当警长后会怎么做。", round_id=rnd["id"])
        session.close_round(rnd)

        # ③ 退水
        rnd = session.open_round("退水", "第 1 天", kind="vote")
        for seat in list(candidates):
            if seat not in st.alive:
                candidates.remove(seat)
                continue
            action = self._act(session, seat, "sheriff_withdraw", "要不要退水？",
                               round_id=rnd["id"])
            if action.get("kind") == "withdraw":
                candidates.remove(seat)
        session.close_round(rnd, "候选人：{}".format(
            "、".join("{} 号".format(c) for c in candidates) or "全部退水"))
        if not candidates:
            session.referee("全部退水，本局没有警长。")
            return
        if len(candidates) == 1:
            st.sheriff = candidates[0]
            self._sync_alive(session)
            session.referee("只有 {} 号一人上警未退水，自动当选警长（票权 {}）。".format(
                st.sheriff, conf.get("vote_weight", 1.5)))
            return

        # ④ 警下投票（平票则 PK 再投）
        st.meta["sheriff_candidates"] = list(candidates)
        winner = self._sheriff_ballot(session, candidates, "警下投票")
        if winner is None:
            return
        if winner == "tie":
            top = st.meta.pop("sheriff_pk", [])
            session.referee("平票：{} 号，进入 PK 发言。".format("、".join(str(t) for t in top)))
            rnd_pk = session.open_round("PK 发言", "第 1 天")
            for seat in top:
                if seat in st.alive:
                    self._act(session, seat, "sheriff_campaign_speak",
                              "你和他人平票，请做 PK 发言。", round_id=rnd_pk["id"])
            session.close_round(rnd_pk)
            winner = self._sheriff_ballot(session, top, "PK 重投")
            if winner is None:
                return
            if winner == "tie":
                session.referee("再次平票，本局没有警长。")
                return
        st.sheriff = winner
        self._sync_alive(session)
        session.referee("{} 号当选警长（票权 {}）。".format(winner, conf.get("vote_weight", 1.5)))

    def _sheriff_ballot(self, session, candidates, title: str):
        """警下玩家投票。返回座位号 / "tie" / None（票数不足）。"""
        st = self._state(session)
        rnd = session.open_round(title, "第 1 天", kind="vote")
        votes = {}
        names = "、".join("{} 号".format(c) for c in sorted(candidates))
        for seat in sorted(st.alive - set(candidates)):
            action = self._act(
                session, seat, "sheriff_vote",
                "候选人只有 {}。你只能投给他们之一，**不能投给自己**（你也不在候选人里）。".format(names),
                round_id=rnd["id"])
            target = self._as_target(action) if action.get("kind") == "vote" else None
            if target not in candidates:
                target = None
            votes[seat] = target
        result = rules.tally_votes(votes)
        detail = "，".join("{} 号 {} 票".format(s, int(v) if v == int(v) else v)
                          for s, v in sorted(result["tally"].items(), key=lambda kv: (-kv[1], kv[0])))
        session.close_round(rnd, detail or "全员弃权")
        if not result["top"]:
            session.referee("警下没有人投票，本局没有警长。")
            return None
        if result["tie"]:
            st.meta["sheriff_pk"] = list(result["top"])
            return "tie"
        return result["top"][0]

    # ---------- 自爆 ----------
    def _try_self_destruct(self, session) -> bool:
        st = self._state(session)
        rnd = session.open_round("自爆声明", "第 {} 天".format(st.day), kind="secret")
        for seat in sorted(st.alive_wolves()):
            action = self._act(session, seat, "wolf_destruct", "要不要现在自爆？", round_id=rnd["id"])
            if action.get("kind") != "destruct":
                continue
            role = st.role_of(seat)
            rules.apply_deaths(st, [{"seat": seat, "cause": "destruct"}])
            session.referee("{} 号自爆，当天不再陈述与投票。".format(seat))
            session.referee("{} 号身份：{}".format(seat, self._label(session, role)), public=False)
            if role == "white_wolf_king":
                take = self._act(session, seat, "wolf_king", "你自爆了，可以带走一个人。",
                                 round_id=rnd["id"])
                victim = self._pick_target(session, seat, take) if take.get("kind") == "shoot" else None
                if victim is not None:
                    rules.apply_deaths(st, [{"seat": victim, "cause": "destruct"}])
                    session.referee("{} 号随自爆出局。".format(victim))
                    self._death_trigger(session, victim, "destruct")
            session.close_round(rnd, "{} 号自爆".format(seat))
            return True
        session.close_round(rnd, "无人自爆")
        return False

    # ---------- 出局触发 ----------
    def _death_trigger(self, session, seat: int, cause: str) -> None:
        st = self._state(session)
        if seat in st.alive:
            return
        if rules.can_hunter_shoot(st, seat, cause):
            rnd = session.open_round("猎人开枪", "{} 号出局".format(seat), kind="secret")
            action = self._act(session, seat, "hunter", "你已出局，可以开枪带走一人。", round_id=rnd["id"])
            shot = self._pick_target(session, seat, action) if action.get("kind") == "shoot" else None
            session.close_round(rnd, "带走 {} 号".format(shot) if shot else "没有开枪")
            if shot is not None:
                rules.apply_deaths(st, [{"seat": shot, "cause": "hunter"}])
                session.referee("{} 号出局时带走了 {} 号。".format(seat, shot))
                self._death_trigger(session, shot, "hunter")
        elif rules.can_wolf_king_shoot(st, seat, cause):
            label = self._label(session, st.role_of(seat))
            rnd = session.open_round("{}反制".format(label), "{} 号出局".format(seat), kind="secret")
            action = self._act(session, seat, "wolf_king", "你是{}，可以开枪。".format(label),
                               round_id=rnd["id"])
            shot = self._pick_target(session, seat, action) if action.get("kind") == "shoot" else None
            session.close_round(rnd, "带走 {} 号".format(shot) if shot else "没有开枪")
            if shot is not None:
                rules.apply_deaths(st, [{"seat": shot, "cause": "hunter"}])
                session.referee("{} 号出局时带走了 {} 号。".format(seat, shot))
                self._death_trigger(session, shot, "hunter")

        if st.sheriff == seat:
            self._handle_badge(session, seat)

    def _handle_badge(self, session, seat: int) -> None:
        st = self._state(session)
        st.sheriff = None
        rnd = session.open_round("警徽移交", "{} 号出局".format(seat), kind="vote")
        action = self._act(session, seat, "badge", "你是警长，已出局，可以把警徽交给一个活人。",
                           round_id=rnd["id"])
        target = self._as_target(action) if action.get("kind") == "pass_badge" else None
        if target is not None and target in st.alive and target != seat:
            st.sheriff = target
            self._sync_alive(session)
            session.close_round(rnd, "{} 号 → {} 号".format(seat, target))
            session.referee("警徽移交：{} 号 → {} 号。".format(seat, target))
        else:
            self._sync_alive(session)
            session.close_round(rnd, "警徽流失")
            session.referee("警徽流失。")

    # ---------- 表决 ----------
    def _vote(self, session):
        st = self._state(session)
        sc = self._scenario(session)
        quorum = str((sc.vote or {}).get("quorum", "above_abstain"))
        first = self._vote_round(session, None, "全体表决")
        ok, detail = rules.quorum_check(first, quorum, len(st.alive))
        if not ok:
            session.referee("票数不足（{}），本轮无人出局。".format(detail))
            return None
        if not first["tie"]:
            return first["eliminated"]
        session.referee("平票：{} 号，重投一次。".format("、".join(str(s) for s in first["top"])))
        policy = str((sc.vote or {}).get("tie", "revote_once"))
        if policy == "lowest_seat":
            return first["top"][0]
        if policy == "no_elimination":
            return None
        second = self._vote_round(session, first["top"], "平票重投")
        ok2, detail2 = rules.quorum_check(second, quorum, len(st.alive))
        if not ok2:
            session.referee("重投票数不足（{}），无人出局。".format(detail2))
            return None
        if second["tie"]:
            session.referee("再次平票，本轮无人出局。")
            return None
        return second["eliminated"]

    def _vote_round(self, session, candidates, title: str) -> dict:
        st = self._state(session)
        rnd = session.open_round(title, "第 {} 天".format(st.day), kind="vote")
        votes = {}
        for seat in sorted(st.alive - set(st.revealed)):
            hint = "表决把谁逐出。" if candidates is None else \
                "在 {} 号之间重投。".format("、".join(str(s) for s in candidates))
            action = self._act(session, seat, "day_vote", hint, round_id=rnd["id"])
            target = action.get("target")
            try:
                target = int(target) if action.get("kind") == "vote" else None
            except (TypeError, ValueError):
                target = None
            if target is not None and candidates is not None and target not in candidates:
                target = None
            votes[seat] = target
        weights = {}
        if st.sheriff is not None and st.sheriff in st.alive:
            weights[st.sheriff] = float((self._scenario(session).sheriff or {}).get("vote_weight", 1.5))
        result = rules.tally_votes(votes, weights)
        session.close_round(rnd, "，".join("{} 号 {} 票".format(s, int(v) if v == int(v) else v)
                                          for s, v in sorted(result["tally"].items(), key=lambda kv: (-kv[1], kv[0])))
                            or "全员弃权")
        return result

    # ---------- 工具 ----------
    @staticmethod
    def _as_target(action: dict):
        try:
            return int(action.get("target"))
        except (TypeError, ValueError):
            return None

    def _pick_target(self, session, seat: int, action: dict, *, allow_self=False):
        st = self._state(session)
        target = self._as_target(action)
        if target is not None and target in st.alive and (allow_self or target != seat):
            return target
        pool = [s for s in sorted(st.alive) if allow_self or s != seat]
        return pool[0] if pool else None

    def _channel_for(self, context: str, seat: int, channel: str | None) -> str:
        if channel:
            return channel
        if context == "wolf_speak":
            return "wolves"
        if context in SECRET_CONTEXTS:
            return "seat:{}".format(seat)
        return PUBLIC

    def _act(self, session, seat: int, context: str, instruction: str,
             channel: str | None = None, round_id: str = "") -> dict:
        if session.stopped:
            return {"kind": "pass"}
        st = self._state(session)
        self._sync_alive(session)
        agent = session.agents.get(seat)
        death_ok = context in ("hunter", "last_words", "badge", "wolf_king")
        if agent is None or (seat not in st.alive and not death_ok):
            return {"kind": "pass"}

        tag = ep.CONTEXT_TAG.get(context, "")
        schema = ep.SCHEMA_TEXT.get(context, "")
        prompt = "{}{}\n只输出一个 JSON 对象，不要解释、不要代码围栏。\n输出格式：{}".format(
            tag, instruction, schema)
        msg = session.ask(agent, prompt,
                          channel=self._channel_for(context, seat, channel),
                          kind="speak", budget=BUDGET.get(context, 1024),
                          validator=self._validator(context), retries=1,
                          label=context, round_id=round_id)
        raw = (msg.text if msg else "") or ""
        if msg is not None and (msg.meta or {}).get("ok") is False:
            session.referee("{} 号调用失败：{}".format(
                seat, (msg.meta or {}).get("error", "未知错误")), public=False)
        action = ep.parse_action(raw)
        fallback = {"kind": "abstain"} if context == "day_vote" else {"kind": "pass"}
        if not action:
            action = fallback
        else:
            # 二次校验：重试用尽后模型可能仍给出非法动作（如投自己），绝不能放行
            ok, reason = rules.validate_action(st, seat, action, context=context)
            if not ok:
                session.referee("{} 号的动作被判非法（{}），按弃权/跳过处理".format(seat, reason),
                                public=False)
                action = fallback

        if msg is not None:
            if action.get("kind") == "speak" and action.get("text"):
                msg.text = str(action["text"])
            else:
                msg.text = self._display_text(action)
                msg.kind = "action"
            msg.meta = dict(msg.meta or {})
            msg.meta["action"] = action
            msg.meta["role"] = self._label(session, st.role_of(seat))
            msg.meta["seat"] = seat
            session.patch_message(msg)
        return action

    @staticmethod
    def _display_text(action: dict) -> str:
        kind = action.get("kind")
        target = action.get("target")
        words = {
            "kill": "（决定对 {} 号动手）", "check": "（查验 {} 号）",
            "guard": "（守 {} 号）", "save": "（用解药救 {} 号）",
            "poison": "（用毒药毒 {} 号）", "vote": "（投票给 {} 号）",
            "shoot": "（开枪带走 {} 号）", "pass_badge": "（把警徽交给 {} 号）",
        }
        if kind in words and target not in (None, ""):
            return words[kind].format(target)
        return {"abstain": "（弃权）", "pass": "（没有动作）", "destroy": "（警徽作废）",
                "destruct": "（自爆）"}.get(kind, "（{}）".format(kind or "无动作"))
