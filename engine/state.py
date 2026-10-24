"""对局状态。座位号一律 1 起。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .scenario import GOD_ROLES, GOOD_ROLES, WOLF_ROLES, Scenario

WOLF = "werewolf"


@dataclass
class GameState:
    scenario: Scenario
    seat_roles: dict[int, str] = field(default_factory=dict)
    alive: set[int] = field(default_factory=set)
    day: int = 0
    phase: str = "init"
    witch_stock: dict = field(default_factory=lambda: {"antidote": 1, "poison": 1})
    guard_last: int | None = None      # 守卫上一晚守的人（不能连守同一人）
    revealed: set = field(default_factory=set)   # 已翻牌的白痴（免死但失去投票权）
    sheriff: int | None = None                   # 警长座位（票权 1.5，白天最后发言）
    deaths_last_night: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)       # 公开发言
    wolf_transcript: list[dict] = field(default_factory=list)  # 狼队夜间密聊（仅狼可见）
    private: dict = field(default_factory=dict)   # seat -> {"seer": [...]} 私有事实
    winner: str | None = None
    meta: dict = field(default_factory=dict)

    # ---------- 构造 ----------
    @classmethod
    def new(cls, scenario: Scenario, seed: int) -> "GameState":
        layout = scenario.role_layout(seed)
        seat_roles = {i + 1: layout[i] for i in range(len(layout))}
        st = cls(scenario=scenario, seat_roles=seat_roles,
                 alive=set(seat_roles.keys()),
                 witch_stock={"antidote": int(scenario.witch.get("antidote", 1)),
                              "poison": int(scenario.witch.get("poison", 1))})
        st.meta["seed"] = seed
        return st

    # ---------- 查询 ----------
    def role_of(self, seat: int) -> str:
        return self.seat_roles.get(seat, "")

    def is_alive(self, seat: int) -> bool:
        return seat in self.alive

    def seats_of(self, role: str) -> list[int]:
        return sorted(s for s, r in self.seat_roles.items() if r == role)

    def alive_of(self, role: str) -> list[int]:
        return [s for s in self.seats_of(role) if s in self.alive]

    def alive_roles(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for seat in self.alive:
            role = self.role_of(seat)
            counts[role] = counts.get(role, 0) + 1
        return counts

    def wolf_seats(self) -> list[int]:
        return sorted(s for s, r in self.seat_roles.items() if r in WOLF_ROLES)

    def alive_wolves(self) -> list[int]:
        return [s for s in self.wolf_seats() if s in self.alive]

    def is_wolf(self, seat: int) -> bool:
        """狼阵营：狼人与狼王都算。"""
        return self.role_of(seat) in WOLF_ROLES

    def alive_goods(self) -> list[int]:
        return sorted(s for s in self.alive if self.role_of(s) in GOOD_ROLES)

    def alive_gods(self) -> list[int]:
        return sorted(s for s in self.alive if self.role_of(s) in GOD_ROLES)

    def alive_villagers(self) -> list[int]:
        return self.alive_of("villager")

    def snapshot(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "alive": sorted(self.alive),
            "roles_alive": self.alive_roles(),
            "witch_stock": dict(self.witch_stock),
            "winner": self.winner,
        }
