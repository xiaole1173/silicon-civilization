"""狼人杀插件：把 engine/ 的规则搬进基座。

分工：
- 规则层（engine.rules / engine.state）保持纯函数，不碰 IO、不碰模型；
- 基座负责上下文、流式、频道、校验重说；
- 本插件只做"什么时候问谁、拿到动作后交给规则结算"。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from base.plugin import BaseScenario                      # noqa: E402
from engine import prompts as ep                          # noqa: E402
from engine import rules                                  # noqa: E402
from engine.scenario import Scenario                      # noqa: E402
from engine.state import GameState                        # noqa: E402

ROLE_KEYS = ("werewolf", "seer", "witch", "hunter", "guard", "villager")

# 相位 -> (动作上下文, 默认预算)
BUDGET = {
    "wolf_speak": 1024, "night_wolf": 1024, "night_seer": 1024,
    "night_guard": 1024, "night_witch": 1536, "day_speak": 2048,
    "day_vote": 1024, "hunter": 768, "last_words": 1024,
}


class WerewolfPlugin(BaseScenario):
    id = "werewolf"
    name = "狼人杀"
    description = "12/9 人狼人杀：夜晚密商、白天陈述与表决"
    default_config = {
        "scenario": "scenarios/werewolf12_standard.yaml",
        "seed": 1,
        "rounds_per_day": 1,
    }

    ABILITY = {
        "werewolf": "夜里和同伴一起带走一个人，白天要装成村民。",
        "seer": "每夜可以查验一个人是狼还是人。",
        "witch": "一瓶救命药、一瓶致命药，每晚最多用一瓶，不能救自己。",
        "hunter": "被狼杀或被票出时可以开枪带走一人；被毒杀不能开枪。",
        "guard": "每夜可以守一个人，不能连续两晚守同一人。",
        "idiot": "被投票放逐会翻牌免死，但此后失去投票权。",
        "villager": "没有特殊能力，只能靠陈述和表决找狼。",
    }

    # ---------- 基础 ----------
    def _cfg(self, session) -> dict:
        return self.merged_config(session.config)

    def _state(self, session) -> GameState:
        return session.meta["game"]

    def _scenario(self, session) -> Scenario:
        return self._state(session).scenario

    def _role_label(self, session, role: str) -> str:
        return self._scenario(session).role_label(role)

    def _seat_of(self, agent) -> int:
        return agent.id

    # ---------- 稳定块 ----------
    def system_text(self, session) -> str:
        sc = self._scenario(session)
        theme = sc.theme
        roles = "、".join("{}×{}".format(self._role_label(session, r), n)
                         for r, n in sc.roles.items())
        return (
            "{}\n\n本局 {} 人，角色构成：{}。\n"
            "流程：夜里被策反者会联合带走一人，其他人各有能力；白天所有人公开陈述，然后表决把一人逐出；"
            "被带走或被逐出就是真的死了，不会复活。\n"
            "每次只输出一个 JSON 对象，不要输出其它文字。".format(
                theme.get("premise", "").strip(), sc.players, roles)
        )

    # ---------- 事实卡 ----------
    def facts(self, session, agent) -> dict:
        st = self._state(session)
        seat = self._seat_of(agent)
        role = st.role_of(seat)
        out = {
            "你的身份": self._role_label(session, role),
            "你的能力": self.ABILITY.get(role, ""),
            "在场": ["{}（{}）".format(i, session.agents[i].name) for i in sorted(st.alive)],
        }
        deaths = st.deaths_last_night or []
        if deaths:
            out["昨夜出局"] = ["{}号（{}）".format(d["seat"], self._role_label(session, d.get("role", "")))
                              for d in deaths]
        if role == "werewolf":
            mates = [s for s in st.alive_wolves() if s != seat]
            if mates:
                out["你的同伴"] = ["{}号".format(s) for s in mates]
        seer = (st.private.get(seat) or {}).get("seer") or []
        if seer:
            out["你的查验"] = [
                "第{}夜查{}号：{}".format(r.get("day"), r.get("target"),
                                          "被策反者" if r.get("is_wolf") else "普通人")
                for r in seer[-6:]
            ]
        if role == "witch":
            out["你的药"] = "救命 {} / 致命 {}".format(
                st.witch_stock.get("antidote", 0), st.witch_stock.get("poison", 0))
            if st.meta.get("pending_wolf_target"):
                out["今夜被袭击"] = "{}号".format(st.meta["pending_wolf_target"])
        if role == "guard" and st.guard_last:
            out["昨夜你守的"] = "{}号".format(st.guard_last)
        return out

    # ---------- 校验：复用规则层 ----------
    def _validator(self, context: str):
        def check(session, agent, text: str):
            st = self._state(session)
            action = ep.parse_action(text or "")
            if not action:
                return False, "没有解析出 JSON 动作，请只输出一个 JSON 对象"
            ok, reason = rules.validate_action(st, self._seat_of(agent), action, context=context)
            return ok, reason
        return check

    # ---------- 开局 ----------
    def setup(self, session) -> None:
        cfg = self._cfg(session)
        path = cfg.get("scenario") or "scenarios/werewolf12.yaml"
        if not os.path.isabs(path):
            path = os.path.join(ROOT, path)
        scenario = Scenario.load(path)
        seed = int(cfg.get("seed") or 1)
        state = GameState.new(scenario, seed)
        session.meta["game"] = state
        session.meta["turn"] = 0

        # 座位与角色对齐：座位号就是 agent.id
        if len(session.agents) != scenario.players:
            raise ValueError("座位数 {} 与场景人数 {} 不一致".format(
                len(session.agents), scenario.players))

        wolves = [s for s in state.seat_roles if state.role_of(s) == "werewolf"]
        session.add_channel("wolves", "狼队密聊", subscribers=wolves)
        session.add_channel("dead", "遗言", subscribers=[])

        layout = "、".join("{}号={}".format(s, self._role_label(session, r))
                          for s, r in sorted(state.seat_roles.items()))
        session.narrate("开局（{}，seed {}）：{}".format(scenario.theme.get("name", "本局"), seed, layout))

    # ---------- 主循环 ----------
    def run(self, session) -> None:
        st = self._state(session)
        sc = self._scenario(session)
        cfg = self._cfg(session)
        rounds_per_day = max(1, int(cfg.get("rounds_per_day") or 1))

        while True:
            st.day += 1
            st.phase = "night"
            session.meta["turn"] = st.day
            session.narrate("第 {} 夜".format(st.day))

            # 守卫
            guard_target = None
            for seat in st.alive_of("guard"):
                action = self._act(session, seat, "night_guard",
                                   "夜深了，你要决定守谁（不能连续两晚守同一人）。")
                if action.get("kind") == "guard":
                    picked = self._pick_target(session, seat, action)
                    if picked is not None:
                        guard_target = picked
            if guard_target is not None:
                st.guard_last = guard_target

            # 狼队密商
            if (sc.wolf_discussion or {}).get("enabled", True):
                for rnd in range(1, int((sc.wolf_discussion or {}).get("rounds", 1)) + 1):
                    for seat in sorted(st.alive_wolves()):
                        self._act(session, seat, "wolf_speak",
                                  "夜里，你们几位私下商议今晚带走谁（第 {} 轮）。".format(rnd),
                                  channel="wolves")

            # 狼刀
            wolf_votes = {}
            for seat in st.alive_wolves():
                action = self._act(session, seat, "night_wolf", "决定今晚带走谁。")
                wolf_votes[seat] = (self._pick_target(session, seat, action)
                                    if action.get("kind") == "kill" else None)
            wolf_target, detail = rules.resolve_wolf_votes(wolf_votes)
            st.meta["pending_wolf_target"] = wolf_target
            if wolf_target:
                session.narrate("狼队的目标：{}号（{}）".format(
                    wolf_target, "多数决" if detail.get("rule") == "majority_lowest_seat" else detail.get("rule")))

            # 预言家
            for seat in st.alive_of("seer"):
                action = self._act(session, seat, "night_seer", "你要查验一位在场者的真实身份。")
                target = self._pick_target(session, seat, action)
                if target is None:
                    continue
                is_wolf = st.role_of(target) == "werewolf"
                st.private.setdefault(seat, {}).setdefault("seer", []).append(
                    {"day": st.day, "target": target, "is_wolf": is_wolf})
                session.narrate("（{}号查验了 {}号）".format(seat, target), channel="private")

            # 女巫
            witch_action = {"kind": "pass"}
            for seat in st.alive_of("witch"):
                witch_action = self._act(session, seat, "night_witch",
                                         "决定是否用药（救命/致命各一瓶）。")
                witch_action["_seat"] = seat

            # 结算
            night = rules.resolve_night(st, wolf_target, witch_action, guard_target)
            deaths = rules.apply_deaths(st, night["deaths"])
            st.deaths_last_night = [dict(d) for d in deaths]
            tags = []
            if night.get("guarded"):
                tags.append("守卫生效")
            if night.get("saved"):
                tags.append("女巫救人")
            if night.get("poisoned"):
                tags.append("女巫用毒")
            if night.get("same_night_rescue"):
                tags.append("同守同救")
            session.narrate("夜晚结算：{}".format(
                "、".join("{}号（{}）".format(d["seat"], self._role_label(session, d["role"]))
                         for d in deaths) or "平安夜") + ("｜" + "，".join(tags) if tags else ""))

            # 猎人
            for d in list(deaths):
                if d["cause"] == "wolf" and rules.can_hunter_shoot(st, d["seat"], d["cause"]):
                    action = self._act(session, d["seat"], "hunter", "你已出局，可以开枪带走一人。")
                    shot = self._pick_target(session, d["seat"], action) if action.get("kind") == "shoot" else None
                    if shot is not None:
                        rules.apply_deaths(st, [{"seat": shot, "cause": "hunter"}])
                        session.narrate("猎人 {}号 开枪带走 {}号".format(d["seat"], shot))

            winner = rules.check_win(st)
            if winner:
                break

            # ---------- 白天 ----------
            st.phase = "day"
            session.narrate("第 {} 天".format(st.day))
            for rnd in range(1, rounds_per_day + 1):
                for seat in sorted(st.alive):
                    self._act(session, seat, "day_speak",
                              "第 {} 天，轮到你陈述（第 {} 轮）。".format(st.day, rnd))

            eliminated = self._vote(session)
            if eliminated:
                outcome = rules.resolve_vote_death(st, eliminated)
                if outcome.get("revealed"):
                    session.narrate("{}号翻牌——是白痴，免于出局，此后失去投票权".format(eliminated))
                    eliminated = None
            if eliminated:
                rules.apply_deaths(st, [{"seat": eliminated, "cause": "vote"}])
                session.narrate("{}号被逐出（身份：{}）".format(
                    eliminated, self._role_label(session, st.role_of(eliminated))))
                if rules.can_hunter_shoot(st, eliminated, "vote"):
                    action = self._act(session, eliminated, "hunter", "你被逐出，可以开枪带走一人。")
                    shot2 = self._pick_target(session, eliminated, action) if action.get("kind") == "shoot" else None
                    if shot2 is not None:
                        rules.apply_deaths(st, [{"seat": shot2, "cause": "hunter"}])
                if (sc.last_words or {}).get("after_vote", True):
                    self._act(session, eliminated, "last_words",
                              "你被逐出，这是你最后一次开口（所有人都会听到）。")

            winner = rules.check_win(st)
            if winner:
                break
            if st.day >= int((sc.win or {}).get("max_days", 8)):
                winner = "draw"
                break

        st.winner = winner
        label = {"good": "好人阵营胜", "werewolves": "狼人阵营胜", "draw": "平局"}.get(winner, winner)
        session.narrate("对局结束：{}（共 {} 天）".format(label, st.day))
        session.end(winner)

    # ---------- 工具 ----------
    def _vote(self, session) -> int | None:
        st = self._state(session)
        sc = self._scenario(session)
        first = self._vote_round(session, None)
        policy = str((sc.vote or {}).get("tie", "revote_once"))
        quorum = str((sc.vote or {}).get("quorum", "above_abstain"))

        ok, detail = rules.quorum_check(first, quorum, len(st.alive))
        if not ok:
            session.narrate("票数不足（{}）→ 本轮无人出局".format(detail))
            return None
        if not first["tie"]:
            return first["eliminated"]
        session.narrate("平票：{} 号".format("、".join(str(s) for s in first["top"])))
        if policy == "lowest_seat":
            return first["top"][0]
        if policy == "no_elimination":
            return None
        second = self._vote_round(session, first["top"])
        ok2, detail2 = rules.quorum_check(second, quorum, len(st.alive))
        if not ok2:
            session.narrate("重投票数不足（{}）→ 无人出局".format(detail2))
            return None
        if second["tie"]:
            session.narrate("再次平票 → 无人出局")
            return None
        return second["eliminated"]

    def _vote_round(self, session, candidates) -> dict:
        st = self._state(session)
        votes = {}
        # 已翻牌的白痴没有投票权
        for seat in sorted(st.alive - set(st.revealed)):
            hint = "表决把谁逐出。" if candidates is None else \
                "在 {} 号之间重投。".format("、".join(str(s) for s in candidates))
            action = self._act(session, seat, "day_vote", hint)
            target = action.get("target")
            try:
                target = int(target) if action.get("kind") == "vote" else None
            except (TypeError, ValueError):
                target = None
            if target is not None and candidates is not None and target not in candidates:
                target = None
            votes[seat] = target
        result = rules.tally_votes(votes)
        session.narrate("表决结果：" + "，".join(
            "{}->{}".format(s, v if v else "弃") for s, v in sorted(votes.items())))
        return result

    @staticmethod
    def _as_target(action: dict):
        """安全取目标：模型给 null / 字符串 / 越界都不会把对局搞崩。"""
        try:
            value = int(action.get("target"))
        except (TypeError, ValueError):
            return None
        return value

    def _pick_target(self, session, seat: int, action: dict, *, allow_self=False):
        """取一个合法目标；非法时退化为"随便挑一个在场者"，保证回合能继续。"""
        st = self._state(session)
        target = self._as_target(action)
        ok = target is not None and target in st.alive and (allow_self or target != seat)
        if ok:
            return target
        pool = [s for s in sorted(st.alive) if allow_self or s != seat]
        return pool[0] if pool else None

    def _act(self, session, seat: int, context: str, instruction: str,
             channel: str = "public") -> dict:
        """问一个座位要动作；校验不过会带原因重说，最终拿不到就退化为 pass/abstain。"""
        st = self._state(session)
        agent = session.agents.get(seat)
        if agent is None or seat not in st.alive:
            return {"kind": "pass"}
        tag = ep.CONTEXT_TAG.get(context, "")
        schema = ep.SCHEMA_TEXT.get(context, "")
        prompt = "{}{}\n输出格式：{}".format(tag, instruction, schema)
        msg = session.ask(agent, prompt, channel=channel, kind="speak",
                          budget=BUDGET.get(context, 1024),
                          validator=self._validator(context), retries=1,
                          label=context)
        raw = (msg.text if msg else "") or ""
        action = ep.parse_action(raw)
        if not action:
            action = {"kind": "abstain"} if context == "day_vote" else {"kind": "pass"}

        # 把结构化动作翻译成人话：历史和界面上不该出现裸 JSON
        if msg is not None:
            if action.get("kind") == "speak" and action.get("text"):
                msg.text = str(action["text"])
            else:
                msg.text = self._display_text(action)
                msg.kind = "action"
            msg.meta = dict(msg.meta or {})
            msg.meta["action"] = action
            msg._render_cache = None
        return action

    @staticmethod
    def _display_text(action: dict) -> str:
        kind = action.get("kind")
        target = action.get("target")
        words = {
            "kill": "（决定对 {} 号动手）",
            "check": "（查验 {} 号）",
            "guard": "（守 {} 号）",
            "save": "（用解药救 {} 号）",
            "poison": "（用毒药毒 {} 号）",
            "vote": "（投票给 {} 号）",
            "shoot": "（开枪带走 {} 号）",
        }
        if kind in words and target not in (None, ""):
            return words[kind].format(target)
        if kind == "abstain":
            return "（弃权）"
        if kind == "pass":
            return "（没有动作）"
        return "（{}）".format(kind or "无动作")
