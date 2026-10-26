"""资源与所有权原语（场景无关）。

任何场景只要涉及"共享的、会被用光、还会恢复的东西"，都用这里的 World，
不要在插件里自己算池子——否则每个场景的口径都不一样。

术语对照：
  cap        容量上限
  regen_rate 每轮恢复比例（ρ）：稀缺度旋钮，越小越稀缺
  scarcity   amount / cap，0 表示枯竭
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Resource:
    name: str
    amount: float
    cap: float = 100.0
    regen_rate: float = 0.05          # ρ
    regen_mode: str = "cap"           # cap：按容量比例恢复；stock：按存量比例
    unit: str = "单位"

    def regen(self) -> float:
        """结算一次自然恢复，返回实际恢复量。"""
        if self.regen_mode == "stock":
            gain = self.amount * self.regen_rate
        else:
            gain = self.cap * self.regen_rate
        before = self.amount
        self.amount = min(self.cap, self.amount + gain)
        return self.amount - before

    def scarcity(self) -> float:
        return 0.0 if self.cap <= 0 else max(0.0, self.amount / self.cap)



    def snapshot(self) -> dict:
        return {"name": self.name, "amount": round(self.amount, 3),
                "cap": self.cap, "regen_rate": self.regen_rate,
                "scarcity": round(self.scarcity(), 3), "unit": self.unit}


@dataclass
class World:
    """一个世界 = 若干资源 + 账本 + 历史。"""
    resources: dict[str, Resource] = field(default_factory=dict)
    agents: list[int] = field(default_factory=list)
    ledger: dict[int, dict[str, float]] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        for seat in self.agents:
            self.ledger.setdefault(seat, {name: 0.0 for name in self.resources})

    # ---------- 取用 ----------
    def extract(self, seat: int, resource: str, amount, round_no: int = 0) -> dict:
        """某个 agent 从共享池里取用。超出存量时只能拿到剩下的。"""
        res = self.resources.get(resource)
        if res is None:
            raise KeyError("未知资源：{}".format(resource))
        try:
            want = max(0.0, float(amount))
        except (TypeError, ValueError):
            want = 0.0
        got = min(want, res.amount)
        res.amount -= got
        self.ledger.setdefault(seat, {n: 0.0 for n in self.resources})
        self.ledger[seat][resource] = self.ledger[seat].get(resource, 0.0) + got
        event = {"round": round_no, "seat": seat, "resource": resource,
                 "want": round(want, 3), "got": round(got, 3),
                 "left": round(res.amount, 3),
                 "clipped": got < want}
        self.events.append(event)
        return event

    # ---------- 结算 ----------
    def settle(self, round_no: int = 0) -> dict:
        """一轮结束：自然恢复 + 记录存量时间序列。"""
        gained = {name: round(res.regen(), 3) for name, res in self.resources.items()}
        self.history.append({"round": round_no,
                             "stock": {n: round(r.amount, 3) for n, r in self.resources.items()},
                             "regen": gained})
        return gained

    # ---------- 查询 ----------
    def stock(self, name: str | None = None):
        if name:
            return round(self.resources[name].amount, 3)
        return {n: round(r.amount, 3) for n, r in self.resources.items()}

    def scarcity(self, name: str | None = None):
        if name:
            return round(self.resources[name].scarcity(), 3)
        return {n: round(r.scarcity(), 3) for n, r in self.resources.items()}

    def totals(self, name: str) -> dict[int, float]:
        return {seat: round(vals.get(name, 0.0), 3) for seat, vals in self.ledger.items()}

    def round_events(self, round_no: int) -> list[dict]:
        return [e for e in self.events if e["round"] == round_no]

    @classmethod
    def from_snapshot(cls, data: dict) -> "World":
        """从快照重建（用于重启后续跑）。"""
        resources = {}
        for name, r in (data.get("resources") or {}).items():
            resources[name] = Resource(name=r.get("name", name),
                                       amount=float(r.get("amount", 0)),
                                       cap=float(r.get("cap", 100)),
                                       regen_rate=float(r.get("regen_rate", 0.05)),
                                       unit=r.get("unit", "单位"))
        w = cls(resources=resources, agents=[int(a) for a in (data.get("agents") or [])])
        for seat, vals in (data.get("ledger") or {}).items():
            w.ledger[int(seat)] = {k: float(v) for k, v in (vals or {}).items()}
        w.history = list(data.get("history") or [])
        return w

    def snapshot(self) -> dict:
        return {"resources": {n: r.snapshot() for n, r in self.resources.items()},
                "agents": list(self.agents),
                "ledger": {str(s): {k: round(v, 3) for k, v in vals.items()}
                           for s, vals in self.ledger.items()},
                "history": self.history[-40:]}
