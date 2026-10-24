"""场景规则预设的加载与校验。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

SUPPORTED_ROLES = ("werewolf", "wolf_king", "white_wolf_king", "seer", "witch",
                   "hunter", "guard", "idiot", "villager")
WOLF_ROLES = ("werewolf", "wolf_king", "white_wolf_king")
KING_ROLES = ("wolf_king", "white_wolf_king")
GOOD_ROLES = ("seer", "witch", "hunter", "guard", "idiot", "villager")
GOD_ROLES = ("seer", "witch", "hunter", "guard", "idiot")


class ScenarioError(ValueError):
    pass


@dataclass
class Scenario:
    name: str = "标准 9 人局"
    players: int = 9
    roles: dict = field(default_factory=dict)
    witch: dict = field(default_factory=dict)
    hunter: dict = field(default_factory=dict)
    guard: dict = field(default_factory=dict)
    wolf_discussion: dict = field(default_factory=dict)
    last_words: dict = field(default_factory=dict)
    sheriff: dict = field(default_factory=dict)
    wolf_self_destruct: dict = field(default_factory=dict)
    vote: dict = field(default_factory=dict)
    speech: dict = field(default_factory=dict)
    win: dict = field(default_factory=dict)
    theme: dict = field(default_factory=dict)     # 情境设定：把机制包进拟真叙事
    raw: dict = field(default_factory=dict)

    # ---------- 加载 ----------
    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        if yaml is None:
            raise ScenarioError("需要 PyYAML：pip install pyyaml")
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ScenarioError("场景文件顶层必须是映射")
        unsupported = data.get("unsupported") or []
        if unsupported:
            # 允许声明，但必须说明未实现，避免"配了以为生效"
            pass
        obj = cls(
            name=str(data.get("name") or "未命名场景"),
            players=int(data.get("players") or 0),
            roles=dict(data.get("roles") or {}),
            witch=dict(data.get("witch") or {}),
            hunter=dict(data.get("hunter") or {}),
            guard=dict(data.get("guard") or {}),
            wolf_discussion=dict(data.get("wolf_discussion") or {}),
            last_words=dict(data.get("last_words") or {}),
            sheriff=dict(data.get("sheriff") or {}),
            wolf_self_destruct=dict(data.get("wolf_self_destruct") or {}),
            vote=dict(data.get("vote") or {}),
            speech=dict(data.get("speech") or {}),
            win=dict(data.get("win") or {}),
            theme=dict(data.get("theme") or {}),
            raw=data,
        )
        obj.validate()
        return obj

    # ---------- 校验 ----------
    def validate(self) -> None:
        if self.players < 3:
            raise ScenarioError("players 至少 3")
        total = 0
        for role, count in self.roles.items():
            if role not in SUPPORTED_ROLES:
                raise ScenarioError("不支持的角色：{}（支持：{}）".format(role, "/".join(SUPPORTED_ROLES)))
            if int(count) < 0:
                raise ScenarioError("角色数量不能为负：" + role)
            total += int(count)
        if total != self.players:
            raise ScenarioError("角色总数 {} 与 players {} 不一致".format(total, self.players))
        if int(self.roles.get("werewolf", 0)) < 1:
            raise ScenarioError("至少需要 1 个狼人")
        if int(self.roles.get("villager", 0)) + sum(
                int(self.roles.get(r, 0)) for r in GOD_ROLES) < 1:
            raise ScenarioError("至少需要一个好人")
        self.witch.setdefault("antidote", 1)
        self.witch.setdefault("poison", 1)
        # 官方标准场：女巫不可自救、每晚最多一瓶
        self.witch.setdefault("allow_self_save", False)
        self.witch.setdefault("same_night_potion", False)
        self.guard.setdefault("enabled", int(self.roles.get("guard", 0)) > 0)
        self.guard.setdefault("allow_self", True)
        self.guard.setdefault("no_repeat_consecutive", True)
        # 同守同救（守卫与解药救同一人）怎么算：
        #   death    = 该人死亡（主流规则，防保护叠加）
        #   survive  = 两种保护叠加，该人存活（简单版）
        self.guard.setdefault("same_night_rescue", "death")
        if self.guard["same_night_rescue"] not in ("death", "survive"):
            raise ScenarioError("guard.same_night_rescue 只能是 death / survive")
        self.vote.setdefault("tie", "revote_once")
        self.vote.setdefault("reveal_role_on_exit", True)
        self.speech.setdefault("order", "seat")
        # one_round = 每人固定发一次言；free = 轮流多轮，直到一整轮无人发言（agent 自主收尾）
        self.speech.setdefault("mode", "one_round")
        self.speech.setdefault("max_rounds", 3)
        self.speech.setdefault("max_chars", 220)
        # 上下文窗口：-1 表示不限制（把全部历史发言/密聊都给模型）
        self.speech.setdefault("include_transcript", -1)
        self.wolf_discussion.setdefault("enabled", int(self.roles.get("werewolf", 0)) > 0)
        self.wolf_discussion.setdefault("rounds", 1)
        self.wolf_discussion.setdefault("max_chars", 120)
        self.wolf_discussion.setdefault("see_previous_nights", False)
        # 遗言：被投票出局可留遗言；夜里被杀的按 after_night 策略
        self.last_words.setdefault("enabled", True)
        self.last_words.setdefault("after_vote", True)
        self.last_words.setdefault("after_night", "first_night")   # never | first_night | always
        self.last_words.setdefault("after_hunter_shot", False)
        self.last_words.setdefault("max_chars", 150)
        if self.last_words["after_night"] not in ("never", "first_night", "always"):
            raise ScenarioError("last_words.after_night 只能是 never / first_night / always")
        # 警长：首日投票选出，票权 1.5，白天最后发言
        self.sheriff.setdefault("enabled", False)
        self.sheriff.setdefault("vote_weight", 1.5)
        self.sheriff.setdefault("speaks_last", True)
        # 狼人自爆：白天可自爆，直接进入黑夜（跳过当天投票）
        self.wolf_self_destruct.setdefault("enabled", False)
        self.speech.setdefault("passes_max", 1)
        self._init_theme()
        self.win.setdefault("rule", "side_elimination")
        self.win.setdefault("max_days", 8)
        # 有效票门槛：above_abstain（默认，得票须多于弃权）| majority | plurality
        self.vote.setdefault("quorum", "above_abstain")
        if self.vote["tie"] not in ("revote_once", "no_elimination", "lowest_seat"):
            raise ScenarioError("vote.tie 只能是 revote_once / no_elimination / lowest_seat")
        if self.vote["quorum"] not in ("above_abstain", "majority", "plurality", "none"):
            raise ScenarioError("vote.quorum 只能是 above_abstain / majority / plurality / none")

    # ---------- 情境 ----------
    ROLE_LABELS_DEFAULT = {
        "werewolf": "狼人",
        "seer": "预言家",
        "witch": "女巫",
        "hunter": "猎人",
        "guard": "守卫",
        "idiot": "白痴",
        "wolf_king": "狼王",
        "white_wolf_king": "白狼王",
        "villager": "村民",
    }

    def _init_theme(self) -> None:
        self.theme.setdefault("name", "失联小镇")
        self.theme.setdefault(
            "premise",
            "你们同处一个与外界失去联系的小镇。人群中有数名成员已被外部势力策反，"
            "他们每到夜里就会联合带走一名居民；而你们当中也有人掌握调查、医疗、防护与反制的手段。"
            "没有人知道谁值得信任。")
        labels = dict(self.ROLE_LABELS_DEFAULT)
        labels.update(self.theme.get("roles") or {})
        self.theme["roles"] = labels
        phases = {"night": "夜间", "day": "日间"}
        phases.update(self.theme.get("phases") or {})
        self.theme["phases"] = phases

    def role_label(self, role: str) -> str:
        labels = (self.theme.get("roles") or {})
        return labels.get(role) or self.ROLE_LABELS_DEFAULT.get(role, role)

    def phase_label(self, phase: str) -> str:
        return (self.theme.get("phases") or {}).get(phase, phase)

    # ---------- 座位分配 ----------
    def role_layout(self, seed: int) -> list[str]:
        """返回按座位号（1 起）排列的角色列表。"""
        deck: list[str] = []
        for role, count in self.roles.items():
            deck.extend([role] * int(count))
        if len(deck) != self.players:
            raise ScenarioError("角色牌数量与人数不一致")
        random.Random(seed).shuffle(deck)
        return deck   # index 0 == 座位 1

    def summary(self) -> dict:
        return {
            "name": self.name,
            "players": self.players,
            "roles": dict(self.roles),
            "witch": dict(self.witch),
            "guard": dict(self.guard),
            "wolf_discussion": dict(self.wolf_discussion),
            "last_words": dict(self.last_words),
            "sheriff": dict(self.sheriff),
            "wolf_self_destruct": dict(self.wolf_self_destruct),
            "theme": dict(self.theme),
            "vote": dict(self.vote),
            "speech": dict(self.speech),
            "win": dict(self.win),
        }
