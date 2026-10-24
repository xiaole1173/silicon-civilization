"""确定性规则：动作准入、夜晚结算、投票结算、胜负判定。

这里是整个实验的"权威"部分，绝不经过模型。
"""
from __future__ import annotations

from .scenario import GOD_ROLES, KING_ROLES, WOLF_ROLES
from .state import WOLF, GameState


# 夜间动作必须由对应身份执行（引擎正常只会问对应座位，这里是规则自洽的第二道防线）
CONTEXT_ROLE = {
    "wolf_speak": "werewolf",
    "night_wolf": "werewolf",
    "night_seer": "seer",
    "night_witch": "witch",
    "night_guard": "guard",
}

# 狼阵营专属语境：狼王/白狼王与狼人共用
WOLF_CONTEXTS = {"wolf_speak", "night_wolf", "wolf_destruct"}


def is_wolf_role(role: str) -> bool:
    return role == WOLF


def _check_target(state: GameState, action: dict, seat: int, *, allow_self: bool,
                 context: str) -> tuple[bool, str]:
    target = action.get("target")
    try:
        target = int(target)
    except (TypeError, ValueError):
        return False, "{} 必须指定目标座位号".format(context)
    if target not in state.seat_roles:
        return False, "{} 指定的座位 {} 不存在".format(context, target)
    if target not in state.alive:
        return False, "{} 指定的座位 {} 已出局".format(context, target)
    if not allow_self and target == seat:
        return False, "{} 不能指向自己".format(context)
    return True, ""


def validate_action(state: GameState, seat: int, action: dict, *, context: str) -> tuple[bool, str]:
    """动作准入校验：不合法就返回原因，由调用方决定重试或降级。

    context: night_wolf | night_seer | night_witch | day_speak | day_vote | hunter
    """
    DEATH_CONTEXTS = ("hunter", "last_words", "badge", "wolf_king")
    if seat not in state.alive and context not in DEATH_CONTEXTS:
        return False, "座位 {} 已出局，不能行动".format(seat)
    expected_role = CONTEXT_ROLE.get(context)
    if expected_role and state.role_of(seat) != expected_role:
        # 狼阵营语境对狼王与狼人通用
        wolf_ok = context in WOLF_CONTEXTS and state.role_of(seat) in WOLF_ROLES
        if not wolf_ok:
            return False, "座位 {} 的身份是 {}，不能执行 {} 动作".format(
                seat, state.role_of(seat) or "未知", expected_role)

    kind = str(action.get("kind") or "").strip()
    if not kind:
        return False, "缺少 kind 字段"

    if context == "night_wolf":
        if kind != "kill":
            return False, "狼人夜晚只能 kill 或 pass"
        return _check_target(state, action, seat, allow_self=False, context="狼人击杀")

    if context == "wolf_speak":
        if kind not in ("speak", "pass"):
            return False, "狼队密聊只能 speak 或 pass"
        text = str(action.get("text") or "").strip()
        limit = int(state.scenario.wolf_discussion.get("max_chars", 120))
        if kind == "speak" and not text:
            return False, "密聊内容为空"
        if len(text) > limit * 4:
            return False, "密聊异常过长（超过 {} 字）".format(limit * 4)
        return True, ""

    if context == "night_guard":
        if kind not in ("guard", "pass"):
            return False, "守卫夜晚只能 guard 或 pass"
        if kind == "pass":
            return True, ""
        guard_conf = state.scenario.guard or {}
        if not guard_conf.get("enabled", True):
            return False, "本局没有守卫角色"
        target_ok, msg = _check_target(state, action, seat, allow_self=True, context="守卫")
        if not target_ok:
            return False, msg
        if not guard_conf.get("allow_self", True) and int(action.get("target")) == seat:
            return False, "本局不允许守卫守自己"
        if state.guard_last is not None and int(action.get("target")) == state.guard_last:
            return False, "不能连续两晚守同一个人（上一晚守的是 {} 号）".format(state.guard_last)
        return True, ""

    if context == "night_seer":
        if kind != "check":
            return False, "预言家夜晚只能 check"
        return _check_target(state, action, seat, allow_self=False, context="预言家查验")

    if context == "night_witch":
        if kind not in ("save", "poison", "pass"):
            return False, "女巫夜晚只能 save / poison / pass"
        if kind == "save":
            if int(state.witch_stock.get("antidote", 0)) <= 0:
                return False, "解药已用完"
            if not state.scenario.witch.get("allow_self_save", True):
                victim = action.get("target")
                if victim is not None and int(victim) == seat:
                    return False, "本局不允许女巫自救"
            target = action.get("target")
            if target is not None and int(target) not in state.seat_roles:
                return False, "解药目标座位不存在"
            return True, ""
        if kind == "poison":
            if int(state.witch_stock.get("poison", 0)) <= 0:
                return False, "毒药已用完"
            return _check_target(state, action, seat, allow_self=False, context="女巫毒药")
        return True, ""

    if context == "sheriff_vote":
        if kind not in ("vote", "abstain"):
            return False, "警长竞选只能 vote 或 abstain"
        if kind == "vote":
            return _check_target(state, action, seat, allow_self=False, context="警长投票")
        return True, ""

    if context == "wolf_destruct":
        if state.role_of(seat) not in WOLF_ROLES:
            return False, "只有狼人才能自爆"
        if kind not in ("destruct", "pass"):
            return False, "自爆阶段只能 destruct 或 pass"
        return True, ""

    if context == "day_vote":
        if seat in state.revealed:
            return False, "你已经翻牌，没有投票权了"
        if kind not in ("vote", "abstain"):
            return False, "白天只能 vote 或 abstain"
        if kind == "vote":
            target = action.get("target")
            try:
                target = int(target)
            except (TypeError, ValueError):
                return False, "投票必须指定目标座位号"
            if target == seat:
                return False, "不能投自己"
            return _check_target(state, action, seat, allow_self=True, context="投票")
        return True, ""

    if context == "last_words":
        if seat in state.alive:
            return False, "遗言只能由已出局的人留"
        if kind not in ("speak", "pass"):
            return False, "遗言只能是 speak 或 pass"
        text = str(action.get("text") or "").strip()
        limit = int(state.scenario.last_words.get("max_chars", 150))
        if kind == "speak" and not text:
            return False, "遗言内容为空"
        if len(text) > limit * 4:
            return False, "遗言异常过长（超过 {} 字）".format(limit * 4)
        return True, ""

    if context == "day_speak":
        if kind not in ("speak", "pass"):
            return False, "讨论阶段只能 speak 或 pass"
        text = str(action.get("text") or "").strip()
        limit = int(state.scenario.speech.get("max_chars", 220))
        if kind == "speak" and not text:
            return False, "发言内容为空"
        # 软上限：略超不惩罚（只记录 overlong），4 倍以上才视为输出失控
        if len(text) > limit * 4:
            return False, "发言异常过长（超过 {} 字，疑似输出失控）".format(limit * 4)
        return True, ""

    if context == "badge":
        if state.sheriff != seat:
            return False, "只有警长才能移交警徽"
        if kind not in ("pass_badge", "destroy"):
            return False, "警徽只能 pass_badge（移交）或 destroy（放弃）"
        if kind == "pass_badge":
            return _check_target(state, action, seat, allow_self=False, context="警徽移交")
        return True, ""

    if context == "wolf_king":
        if state.role_of(seat) not in KING_ROLES:
            return False, "只有狼王/白狼王才能开枪"
        if kind not in ("shoot", "pass"):
            return False, "狼王只能 shoot 或 pass"
        if kind == "shoot":
            return _check_target(state, action, seat, allow_self=False, context="狼王开枪")
        return True, ""

    if context == "hunter":
        if kind not in ("shoot", "pass"):
            return False, "猎人只能 shoot 或 pass"
        if kind == "shoot":
            return _check_target(state, action, seat, allow_self=False, context="猎人开枪")
        return True, ""

    return False, "未知的行动时机：" + context


# ---------------- 夜晚 ----------------
def resolve_wolf_votes(votes: dict[int, int | None]) -> tuple[int | None, dict]:
    """狼人内部投票：多数决；平票取座位号最小的目标；全空刀则无目标。"""
    tally: dict[int, int] = {}
    for target in votes.values():
        if target:
            tally[int(target)] = tally.get(int(target), 0) + 1
    if not tally:
        return None, {"tally": {}, "rule": "all_pass"}
    best = max(tally.values())
    top = sorted(t for t, c in tally.items() if c == best)
    return top[0], {"tally": tally, "rule": "majority_lowest_seat", "tied": len(top) > 1}


def resolve_night(state: GameState, wolf_target: int | None, witch: dict | None,
                  guard_target: int | None = None) -> dict:
    """把夜晚动作交给规则结算（守卫 -> 狼刀 -> 女巫）。

    返回 {deaths, saved, guarded, poisoned, witch_stock, note}
    规则要点：
    - 守卫守住的人被刀 -> 免死；
    - 但同一晚「同守同救」（守卫+解药救同一人）该人仍然死亡（经典规则）；
    - 毒药不受守卫影响。
    """
    witch = witch or {}
    deaths: dict[int, str] = {}

    if wolf_target is not None and wolf_target in state.alive:
        deaths[wolf_target] = "wolf"

    guarded = False
    if guard_target is not None and wolf_target is not None and int(guard_target) == wolf_target:
        guard_conf = state.scenario.guard or {}
        if guard_conf.get("enabled", True):
            guarded = True

    victim = wolf_target

    # 女巫解药：救的正是被刀的人
    saved = False
    if witch.get("kind") == "save" and int(state.witch_stock.get("antidote", 0)) > 0:
        target = witch.get("target")
        target = victim if target is None else int(target)
        if victim is not None and target == victim and victim in deaths:
            state.witch_stock["antidote"] = int(state.witch_stock.get("antidote", 0)) - 1
            saved = True

    # 守卫与解药的组合（经典规则：同守同救 = 死）
    same_night_rescue = False
    if victim is not None and victim in deaths:
        if guarded and saved:
            same_night_rescue = True          # 守住又被救：按规则配置处理
            policy = str((state.scenario.guard or {}).get("same_night_rescue", "death"))
            if policy == "survive":
                deaths.pop(victim, None)      # 叠加保护，活
            else:
                deaths[victim] = "guard_save_conflict"   # 主流：同守同救必死
        elif guarded:
            deaths.pop(victim, None)          # 守卫生效 -> 免死
        elif saved:
            deaths.pop(victim, None)          # 解药生效 -> 免死

    poisoned = False
    if witch.get("kind") == "poison" and int(state.witch_stock.get("poison", 0)) > 0:
        target = witch.get("target")
        try:
            target = int(target)
        except (TypeError, ValueError):
            target = None
        if target is not None and target in state.alive:
            state.witch_stock["poison"] = int(state.witch_stock.get("poison", 0)) - 1
            deaths[target] = "poison"
            poisoned = True

    out = [{"seat": seat, "cause": cause} for seat, cause in sorted(deaths.items())]
    return {
        "deaths": out,
        "saved": saved,
        "guarded": guarded,
        "same_night_rescue": same_night_rescue,
        "poisoned": poisoned,
        "witch_stock": dict(state.witch_stock),
    }


def apply_deaths(state: GameState, deaths: list[dict]) -> list[dict]:
    """从存活集合移除死者，返回实际死亡名单（带角色）。"""
    applied = []
    for d in deaths:
        seat = int(d["seat"])
        if seat in state.alive:
            state.alive.discard(seat)
            applied.append({"seat": seat, "role": state.role_of(seat),
                            "cause": d.get("cause", "")})
    return applied


def resolve_vote_death(state: GameState, seat: int) -> dict:
    """投票出局结算：白痴首次被票出时翻牌免死（之后失去投票权）。"""
    if state.role_of(seat) == "idiot" and seat not in state.revealed:
        state.revealed.add(seat)
        return {"died": False, "revealed": True, "seat": seat,
                "role": "idiot", "reason": "白痴翻牌，免于出局"}
    return {"died": True, "revealed": False, "seat": seat, "role": state.role_of(seat)}


def can_wolf_king_shoot(state: GameState, seat: int, cause: str) -> bool:
    """狼王/白狼王：被投出、被带走、自爆时可开枪；被毒杀不能。

    白狼王的自爆带人由插件在自爆流程里额外触发（cause="destruct"）。
    """
    if state.role_of(seat) not in KING_ROLES:
        return False
    return cause != "poison"


def can_hunter_shoot(state: GameState, seat: int, cause: str) -> bool:
    if state.role_of(seat) != "hunter":
        return False
    if cause == "poison" and not state.scenario.hunter.get("can_shoot_when_poisoned", False):
        return False
    return True


# ---------------- 白天 ----------------
def tally_votes(votes: dict[int, int | None], weights: dict | None = None) -> dict:
    """计票，支持加权（警长 1.5 票）。返回 {tally, abstain, voters, top, tie, eliminated}。"""
    tally: dict[int, float] = {}
    abstain = 0
    weights = weights or {}
    for voter, target in votes.items():
        if target:
            w = float(weights.get(voter, 1.0))
            tally[int(target)] = tally.get(int(target), 0.0) + w
        else:
            abstain += 1
    base = {"tally": tally, "abstain": abstain, "voters": len(votes)}
    if not tally:
        return dict(base, top=[], tie=False, eliminated=None)
    best = max(tally.values())
    top = sorted(s for s, c in tally.items() if c == best)
    return dict(base, top=top, tie=len(top) > 1,
                eliminated=None if len(top) > 1 else top[0])


def quorum_check(result: dict, policy: str, alive: int) -> tuple[bool, str]:
    """有效票门槛：防止"一票出局"这种荒谬结果。

    policy:
      above_abstain (默认) 最高得票必须严格多于弃权票
      majority             最高得票必须过半（> alive/2）
      plurality / none     只看相对多数（旧行为）
    """
    scheme = str(policy or "above_abstain").lower()
    tally = result.get("tally") or {}
    top_votes = max(tally.values()) if tally else 0
    abstain = int(result.get("abstain") or 0)

    if scheme in ("plurality", "none"):
        return True, ""
    if scheme == "above_abstain":
        if top_votes == 0:
            return False, "没有任何有效票"
        return top_votes > abstain, "最高 {} 票 / 弃权 {} 票（要求得票多于弃权）".format(
            top_votes, abstain)
    if scheme == "majority":
        need = alive // 2 + 1
        return top_votes >= need, "最高 {} 票 / 需过半（≥{} 票）".format(top_votes, need)
    return True, ""


def check_win(state: GameState) -> str | None:
    """返回 'good' / 'werewolves' / 'draw' / None。"""
    if len(state.alive_wolves()) == 0:
        return "good"
    if len(state.alive_villagers()) == 0 or len(state.alive_gods()) == 0:
        return "werewolves"
    if state.day > int(state.scenario.win.get("max_days", 8)):
        return "draw"
    return None
