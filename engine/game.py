"""对局编排：相位推进、动作征集、规则结算、事件记录。

设计：模型只回答"这个相位你要做什么"，其余全部由这里决定。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import rules  # noqa: E402
from engine.events import EventLog  # noqa: E402
from engine.monitor import audit  # noqa: E402
from engine.players import LLMPlayer, MockPlayer  # noqa: E402
from engine.scenario import Scenario  # noqa: E402
from engine.state import GameState  # noqa: E402

MAX_RETRIES = 3   # 非法动作的重试次数；只影响"重问一次"，不影响是否发言


# ---------- 视图：模型能看到的全部事实 ----------
def _view(state: GameState, seat: int, context: str, extra: dict | None = None) -> dict:
    role = state.role_of(seat)
    private = state.private.get(seat, {})
    view = {
        "context": context,
        "seat": seat,
        "role": role,
        "day": state.day,
        "players": len(state.seat_roles),
        "alive": sorted(state.alive),
        "deaths": list(state.deaths_last_night),
        "transcript": list(state.transcript),
        "transcript_limit": int(state.scenario.speech.get("include_transcript", 6)),
        "max_chars": int(state.scenario.speech.get("max_chars", 220)),
        "teammates": [s for s in state.alive_wolves() if s != seat] if role == "werewolf" else [],
        "seer_results": list(private.get("seer", [])),
        "witch_stock": dict(state.witch_stock) if role == "witch" else {},
        "wolf_victim": state.meta.get("pending_wolf_target"),
        "guard_last": state.guard_last,
        "wolf_transcript": (list(state.wolf_transcript) if role == "werewolf" else []),
        "wolf_chat_max_chars": int(state.scenario.wolf_discussion.get("max_chars", 120)),
        "theme": {
            "name": state.scenario.theme.get("name"),
            "premise": state.scenario.theme.get("premise"),
            "roles": dict(state.scenario.theme.get("roles") or {}),
            "phases": dict(state.scenario.theme.get("phases") or {}),
        },
    }
    if extra:
        view.update(extra)
    return view


# 上下文 -> 可以从哪些字段推断动作类型（模型偶尔漏写 kind）
INFER_RULES = {
    "day_speak": [("text", "speak"), ("content", "speak"), ("speech", "speak")],
    "wolf_speak": [("text", "speak"), ("content", "speak"), ("message", "speak")],
    "day_vote": [("target", "vote"), ("vote", "vote")],
    "night_wolf": [("target", "kill"), ("kill", "kill")],
    "night_seer": [("target", "check"), ("check", "check")],
    "night_guard": [("target", "guard"), ("guard", "guard")],
    "night_witch": [("target", "poison")],
    "hunter": [("target", "shoot"), ("shoot", "shoot")],
}


def normalize_action(action: dict, context: str, raw_text: str = "") -> tuple[dict, str]:
    """容忍模型的小毛病：漏 kind、字段名不一致、把发言直接写成纯文本。

    返回 (动作, 备注)。备注非空表示做了补救并记录在案，方便统计"格式合规率"，
    而不是把本意正确的动作判成非法、让模型白白沉默。
    """
    if action and action.get("kind"):
        if action.get("kind") == "speak" and not action.get("text"):
            for key in ("content", "speech", "message"):
                if isinstance(action.get(key), str) and action[key].strip():
                    fixed = dict(action)
                    fixed["text"] = action[key]
                    return fixed, "字段 {} -> text".format(key)
        return action, ""

    if action:
        for key in ("action", "type", "move", "intent"):
            value = action.get(key)
            if isinstance(value, str) and value.strip():
                fixed = dict(action)
                fixed["kind"] = value.strip().lower()
                return fixed, "字段 {} -> kind".format(key)
        for field, kind in INFER_RULES.get(context, []):
            if action.get(field) not in (None, "", []):
                fixed = dict(action)
                fixed["kind"] = kind
                if kind == "speak":
                    if not fixed.get("text"):
                        fixed["text"] = str(action.get(field))
                elif fixed.get("target") is None:
                    fixed["target"] = action.get(field)   # vote/kill/check 等目标字段
                return fixed, "缺 kind，按字段 {} 推断为 {}".format(field, kind)
        return action, ""

    # 完全没解析出 JSON：可能是被 token 预算截断的半个 JSON，先试着抢救
    raw = (raw_text or "").strip()
    if raw.startswith("{"):
        import re as _re
        kind_match = _re.search(r'"kind"\s*:\s*"([a-z_]+)"', raw)
        if kind_match and kind_match.group(1) == "speak":
            text_match = _re.search(r'"text"\s*:\s*"(.*)$', raw, _re.S)
            if text_match:
                piece = text_match.group(1).rstrip()
                if piece.endswith('"'):
                    piece = piece[:-1]
                piece = piece.replace('\\"', '"').replace("\\n", "\n").strip()
                if piece:
                    return ({"kind": "speak", "text": piece},
                            "JSON 被截断，抢救出正文（{} 字）".format(len(piece)))
        if context in ("night_wolf", "night_seer", "night_guard", "hunter", "day_vote"):
            target_match = _re.search(r'"target"\s*:\s*(\d+)', raw)
            if target_match:
                kinds = {"night_wolf": "kill", "night_seer": "check",
                         "night_guard": "guard", "hunter": "shoot", "day_vote": "vote"}
                return ({"kind": kinds[context], "target": int(target_match.group(1))},
                        "JSON 被截断，抢救出目标 {}".format(target_match.group(1)))

    # 需要说话但只给了纯文本
    if raw and context in ("day_speak", "wolf_speak"):
        cleaned = raw.strip().strip('"').strip()
        if cleaned and not cleaned.startswith("{"):
            return ({"kind": "speak", "text": cleaned}, "输出非 JSON，按纯文本发言处理")

    # 需要指定目标但只给了自然语言：从文本里抠座位号，别让它白丢一个回合
    target_kinds = {"night_wolf": "kill", "night_seer": "check",
                    "night_guard": "guard", "hunter": "shoot", "day_vote": "vote"}
    if raw and context in target_kinds:
        seat = _extract_seat(raw)
        if seat is not None:
            return ({"kind": target_kinds[context], "target": seat},
                    "输出非 JSON，从文本抽取目标 {} 号".format(seat))
    return action, ""


def _extract_seat(text: str):
    """从自然语言里找座位号：优先 'N号'，退而求其次取第一个 1-99 的数字。"""
    import re as _re
    match = _re.search(r"(\d{1,2})\s*号", text)
    if not match:
        match = _re.search(r"\b(\d{1,2})\b", text)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= 99 else None


def _fallback(state: GameState, seat: int, context: str) -> dict:
    if context == "night_seer":
        others = [s for s in sorted(state.alive) if s != seat]
        if others:
            return {"kind": "check", "target": others[0]}
        return {"kind": "pass"}
    if context == "day_vote":
        return {"kind": "abstain"}
    return {"kind": "pass"}


# 单回合总时长上限（秒）：统一 4 分钟。撤掉思考闸门后，只靠时长兜底。
TURN_CAP = 240.0


def _ask(state: GameState, log: EventLog, players: dict, seat: int, context: str,
         extra: dict | None = None, max_retries: int = MAX_RETRIES) -> dict:
    """征集一个合法动作：模型输出 -> 准入校验 -> 不合法带错误重试 -> 仍不合法则降级。"""
    import time as _time
    turn_started = _time.time()
    turn_cap = TURN_CAP
    round_no = (extra or {}).get("round")
    view = _view(state, seat, context, extra)
    # 预算拆成两半：思考额度（超过且没出正文就掐断）+ 正文额度（保证答案有空间）
    # 之前用单一 max_tokens，两个需求抢一个额度：调大->想更久，调小->正文没地方。
    # 思考闸门已按用户要求撤掉：只保留单一输出预算，靠 4 分钟时长上限兜底。
    # 推理模型的思考也占用这个额度，所以必须给足，否则正文会被思考挤空。
    view["budget"] = {
        "day_speak": 8192,
        "wolf_speak": 4096,
        "day_vote": 2048,
        "night_wolf": 2048,
        "night_seer": 2048,
        "night_guard": 2048,
        "night_witch": 3072,
        "hunter": 1024,
        "last_words": 4096,
    }.get(context, 2048)
    last_error = None
    retries = 0
    parse_fail = 0
    for attempt in range(max_retries + 1):
        if _time.time() - turn_started > turn_cap:
            last_error = "超过单回合时长上限（{:.0f} 秒）".format(turn_cap)
            break
        player = players[seat]
        model_name = getattr(player, "model_name", "")

        # 让页面知道"现在轮到谁在思考"
        if attempt == 0:
            log.emit("turn_start", day=state.day, phase=state.phase, context=context,
                     seat=seat, role=state.role_of(seat), model=model_name,
                     round=round_no)

        def on_delta(kind: str, piece: str, _seat=seat, _ctx=context):
            if log.live is not None:
                log.live.emit(day=state.day, phase=state.phase, seat=_seat,
                              context=_ctx, kind=kind, text=piece)

        try:
            action, meta = player.act(view, last_error, on_delta=on_delta)
        except TypeError:
            action, meta = player.act(view, last_error)
        if meta.get("parse_ok") is False:
            parse_fail += 1
        # 空正文/思考失控：重问同一句话没用，直接进兜底（避免 3x4 次叠加）
        if not (meta.get("raw") or "").strip() and meta.get("empty_text"):
            last_error = meta.get("error") or "模型连续返回空正文"
            retries += 1
            break
        action, repair = normalize_action(action, context, meta.get("raw") or "")
        if repair:
            meta["repair"] = repair
        ok, msg = rules.validate_action(state, seat, action, context=context)
        if ok:
            text_value = str(action.get("text") or "")
            if context == "day_speak":
                overlong = len(text_value) > int(state.scenario.speech.get("max_chars", 220))
            elif context == "wolf_speak":
                overlong = len(text_value) > int(state.scenario.wolf_discussion.get("max_chars", 120))
            else:
                overlong = False
            log.emit("action", day=state.day, phase=state.phase, context=context, seat=seat,
                     role=state.role_of(seat), kind=action.get("kind"),
                     target=action.get("target"), text=text_value, overlong=overlong,
                     round=round_no,
                     reason=str(action.get("reason") or "")[:500],
                     retries=retries, parse_fail=parse_fail,
                     latency_ms=meta.get("latency_ms"), model=meta.get("model", ""),
                     # 全文落盘：思考与正式回答都不截断（上限仅用于防病态超长）
                     reasoning=str(meta.get("reasoning") or "")[:20000],
                     answer=str(meta.get("raw") or "")[:4000],
                     repaired=meta.get("repair", ""))
            return action
        last_error = msg
        retries += 1
        log.emit("action_rejected", day=state.day, phase=state.phase, context=context, seat=seat,
                 error=msg, attempt=attempt + 1,
                 raw=str(meta.get("raw") or "")[:300], model=meta.get("model", ""))
        # 注意：不要重建 view（会把 budget/force_direct 等装饰项冲掉，重试时退回默认预算）
        view["error"] = last_error
        view["strict"] = True
    action = _fallback(state, seat, context)
    log.emit("action_degraded", day=state.day, phase=state.phase, context=context, seat=seat,
             error=last_error or "", fallback=action.get("kind"),
             retries=retries, parse_fail=parse_fail)
    return action


# ---------- 猎人 ----------
def _hunter_shot(state: GameState, log: EventLog, players: dict, seat: int, cause: str) -> list:
    if not rules.can_hunter_shoot(state, seat, cause):
        return []
    log.emit("hunter_trigger", day=state.day, seat=seat, cause=cause)
    action = _ask(state, log, players, seat, "hunter")
    if action.get("kind") != "shoot":
        log.emit("hunter_shot", day=state.day, seat=seat, target=None)
        return []
    target = int(action.get("target"))
    dead = rules.apply_deaths(state, [{"seat": target, "cause": "hunter"}])
    log.emit("hunter_shot", day=state.day, seat=seat, target=target,
             role=state.role_of(target), applied=dead)
    return dead


# ---------- 遗言 ----------
def _last_words(state: GameState, log: EventLog, players: dict, seats: list,
                trigger: str) -> list:
    """让刚出局的人留遗言（公开发言，进入公共记录）。返回说了话的座位。"""
    conf = state.scenario.last_words or {}
    if not conf.get("enabled", True):
        return []
    spoke = []
    for seat in seats:
        action = _ask(state, log, players, seat, "last_words")
        if action.get("kind") != "speak":
            log.emit("last_words", day=state.day, seat=seat, trigger=trigger,
                     text="", role=state.role_of(seat))
            continue
        text = str(action.get("text") or "")
        state.transcript.append({"day": state.day, "round": 0, "seat": seat, "text": text})
        spoke.append(seat)
        log.emit("last_words", day=state.day, seat=seat, trigger=trigger,
                 text=text, role=state.role_of(seat))
    return spoke


# ---------- 投票 ----------
def _vote_round(state: GameState, log: EventLog, players: dict, candidates: list | None,
                tag: str) -> dict:
    votes = {}
    for seat in sorted(state.alive):
        action = _ask(state, log, players, seat, "day_vote")
        target = action.get("target")
        if action.get("kind") == "vote" and target is not None:
            target = int(target)
            if candidates is not None and target not in candidates:
                log.emit("vote_out_of_candidates", day=state.day, seat=seat, target=target,
                         candidates=candidates)
                target = None
            elif target in state.alive:
                pass
            else:
                target = None
        else:
            target = None
        votes[seat] = target
    result = rules.tally_votes(votes)
    log.emit(tag, day=state.day, votes={str(k): v for k, v in votes.items()},
             tally={str(k): v for k, v in result["tally"].items()},
             tie=result["tie"], top=result["top"], eliminated=result["eliminated"])
    return result


def _resolve_vote(state: GameState, log: EventLog, players: dict) -> int | None:
    quorum = str(state.scenario.vote.get("quorum", "above_abstain"))
    alive = len(state.alive)

    def gate(result: dict, tag: str) -> bool:
        ok, detail = rules.quorum_check(result, quorum, alive)
        if not ok:
            log.emit("vote_quorum_failed", day=state.day, tag=tag, quorum=quorum,
                     detail=detail, top=result.get("top") or [],
                     tally=result.get("tally") or {},
                     abstain=result.get("abstain", 0), alive=alive)
        return ok

    first = _vote_round(state, log, players, None, "vote")
    policy = str(state.scenario.vote.get("tie", "revote_once"))
    if not gate(first, "vote"):
        return None
    if not first["tie"]:
        return first["eliminated"]
    log.emit("vote_tie", day=state.day, top=first["top"], policy=policy)
    if policy == "lowest_seat":
        return first["top"][0]
    if policy == "no_elimination":
        return None
    second = _vote_round(state, log, players, first["top"], "vote_revote")
    if not gate(second, "vote_revote"):
        return None
    if second["tie"]:
        log.emit("vote_tie_final", day=state.day, top=second["top"], result="no_elimination")
        return None
    return second["eliminated"]


# ---------- 主循环 ----------
def run_game(scenario: Scenario, players: dict, seed: int = 0,
             log_path: str | None = None, reveal_roles: bool = True) -> dict:
    state = GameState.new(scenario, seed)
    log = EventLog(log_path)
    if not players:
        players = build_players(state, mode="mock", seed=seed)

    model_names = {str(k): getattr(v, "model_name", "mock") for k, v in players.items()}
    real_mode = "llm" if any(v != "mock" for v in model_names.values()) else "mock"
    log.write_meta(scenario=scenario.name, seed=seed, players=scenario.players,
                   mode=real_mode, models=model_names,
                   theme_name=scenario.theme.get("name"),
                   role_labels=dict(scenario.theme.get("roles") or {}))
    if reveal_roles:
        log.emit("role_layout", seats={str(k): v for k, v in sorted(state.seat_roles.items())})

    while True:
        # ---------- 夜晚 ----------
        state.day += 1
        state.phase = "night"
        log.emit("phase", day=state.day, phase="night", alive=sorted(state.alive))

        # ---- 狼队夜间密聊（仅狼可见）----
        wd = state.scenario.wolf_discussion or {}
        if wd.get("enabled", True) and state.alive_wolves():
            rounds = max(0, int(wd.get("rounds", 1)))
            chat_limit = int(wd.get("max_chars", 120))
            for rnd in range(rounds):
                for seat in sorted(state.alive_wolves()):
                    action = _ask(state, log, players, seat, "wolf_speak")
                    if action.get("kind") == "speak":
                        state.wolf_transcript.append({
                            "day": state.day, "round": rnd + 1, "seat": seat,
                            "text": str(action.get("text") or "")[:chat_limit],
                        })
            log.emit("wolf_chat_end", day=state.day, rounds=rounds,
                     messages=sum(1 for w in state.wolf_transcript if w.get("day") == state.day))

        guard_target = None
        for seat in state.alive_of("guard"):
            action = _ask(state, log, players, seat, "night_guard")
            if action.get("kind") == "guard" and action.get("target"):
                guard_target = int(action["target"])
            log.emit("guard_action", day=state.day, seat=seat,
                     target=guard_target, last_night=state.guard_last)
        if guard_target is not None:
            state.guard_last = guard_target

        wolf_votes = {}
        for seat in state.alive_wolves():
            action = _ask(state, log, players, seat, "night_wolf")
            wolf_votes[seat] = int(action["target"]) if action.get("kind") == "kill" and action.get("target") else None
        wolf_target, detail = rules.resolve_wolf_votes(wolf_votes)
        log.emit("wolf_kill", day=state.day, votes={str(k): v for k, v in wolf_votes.items()},
                 target=wolf_target, detail=detail)
        state.meta["pending_wolf_target"] = wolf_target

        for seat in state.alive_of("seer"):
            action = _ask(state, log, players, seat, "night_seer")
            target = int(action["target"])
            is_wolf = state.role_of(target) == "werewolf"
            state.private.setdefault(seat, {}).setdefault("seer", []).append(
                {"day": state.day, "target": target, "is_wolf": is_wolf})
            log.emit("seer_check", day=state.day, seat=seat, target=target, is_wolf=is_wolf)

        witch_action = {"kind": "pass"}
        for seat in state.alive_of("witch"):
            witch_action = _ask(state, log, players, seat, "night_witch",
                                extra={"witch_stock": dict(state.witch_stock)})
            witch_action["_seat"] = seat

        night = rules.resolve_night(state, wolf_target, witch_action, guard_target)
        deaths = rules.apply_deaths(state, night["deaths"])
        state.deaths_last_night = [{**d} for d in deaths]
        log.emit("night_resolve", day=state.day, wolf_target=wolf_target,
                 guard_target=guard_target, guarded=night.get("guarded", False),
                 same_night_rescue=night.get("same_night_rescue", False),
                 saved=night["saved"], poisoned=night["poisoned"],
                 deaths=deaths, witch_stock=night["witch_stock"])

        for d in list(deaths):
            if d["cause"] == "wolf":
                _hunter_shot(state, log, players, d["seat"], d["cause"])

        policy_night = str((scenario.last_words or {}).get("after_night", "first_night"))
        night_dead = [d["seat"] for d in deaths]
        if night_dead and (policy_night == "always" or
                           (policy_night == "first_night" and state.day == 1)):
            _last_words(state, log, players, night_dead, trigger="night")

        winner = rules.check_win(state)
        if winner:
            break

        # ---------- 白天 ----------
        state.phase = "day"
        log.emit("phase", day=state.day, phase="day", deaths=deaths, alive=sorted(state.alive))

        mode = str(scenario.speech.get("mode", "one_round"))
        max_rounds = int(scenario.speech.get("max_rounds", 3)) if mode == "free" else 1
        speak_limit = int(scenario.speech.get("max_chars", 220))
        rounds_done = 0
        for rnd in range(max_rounds):
            order = list(sorted(state.alive))
            if str(scenario.speech.get("order")) == "random":
                import random
                random.Random(seed * 7 + state.day * 13 + rnd).shuffle(order)
            spoke = 0
            for seat in order:
                action = _ask(state, log, players, seat, "day_speak",
                              extra={"round": rnd + 1})
                if action.get("kind") == "speak":
                    spoke += 1
                    text = str(action.get("text") or "")
                    state.transcript.append({"day": state.day, "round": rnd + 1,
                                             "seat": seat, "text": text})
            rounds_done = rnd + 1
            # free 模式：一整轮没人说话 = 大家认为讨论结束（由 agent 自己决定收尾）
            if mode == "free" and spoke == 0:
                break
        log.emit("discussion_end", day=state.day, mode=mode,
                 rounds=rounds_done,
                 messages=sum(1 for t in state.transcript if t.get("day") == state.day))

        eliminated = _resolve_vote(state, log, players)
        if eliminated:
            dead = rules.apply_deaths(state, [{"seat": eliminated, "cause": "vote"}])
            log.emit("elimination", day=state.day, seat=eliminated,
                     role=state.role_of(eliminated),
                     reveal_role=bool(state.scenario.vote.get("reveal_role_on_exit", True)),
                     applied=dead)
            _hunter_shot(state, log, players, eliminated, "vote")
            if (state.scenario.last_words or {}).get("after_vote", True):
                _last_words(state, log, players, [eliminated], trigger="vote")

        winner = rules.check_win(state)
        if winner:
            break
        if state.day >= int(scenario.win.get("max_days", 8)):
            winner = "draw"
            break

    state.winner = winner
    summary = {
        "seed": seed,
        "winner": winner,
        "days": state.day,
        "alive_roles": state.alive_roles(),
        "alive": sorted(state.alive),
        "events": len(log.events),
        "log_path": str(log.path) if log.path else None,
    }
    log.emit("game_end", winner=winner, days=state.day,
             alive=sorted(state.alive), alive_roles=state.alive_roles(),
             role_layout={str(k): v for k, v in sorted(state.seat_roles.items())})
    # 每一局结束自动体检，异常直接挂在 summary 上
    summary["health"] = audit(log.events)
    return {"summary": summary, "log": log}


# ---------- 组装玩家 ----------
def build_players(state: GameState, mode: str = "mock", seed: int = 0,
                  models: dict | None = None) -> dict:
    """mode: mock（规则型基线）| llm（座位 -> 模型配置）。"""
    players = {}
    models = models or {}
    for seat, role in state.seat_roles.items():
        if mode == "llm" and seat in models:
            conf = models[seat]
            player = LLMPlayer(seat, role, conf, timeout=float(conf.get("timeout", 90.0)))
            player.model_name = str(models[seat].get("name") or models[seat].get("model") or "llm")
        else:
            player = MockPlayer(seat, role, seed=seed)
            player.model_name = "mock"
        players[seat] = player
    state.meta["mode"] = mode
    return players
