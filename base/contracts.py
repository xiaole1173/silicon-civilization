"""合约与履约原语（场景无关）。

最小模型：一轮内提出"全员上限"契约，其他人选择接受；接受者若超额取用即记违约。
调解只是"违约后施加惩罚"的钩子，具体惩罚由场景决定（如下调下轮额度）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Contract:
    id: str
    round_no: int
    kind: str                 # "limit"
    value: float
    proposer: int
    accepted: set = field(default_factory=set)
    status: str = "open"      # open | active | kept | broken
    breaches: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"id": self.id, "round": self.round_no, "kind": self.kind,
                "value": self.value, "proposer": self.proposer,
                "accepted": sorted(self.accepted), "status": self.status,
                "breaches": list(self.breaches)}


class ContractBook:
    def __init__(self) -> None:
        self.contracts: list[Contract] = []
        self._seq = 0

    def propose(self, seat: int, value: float, round_no: int,
                kind: str = "limit") -> Contract:
        self._seq += 1
        c = Contract(id="c{}".format(self._seq), round_no=round_no, kind=kind,
                     value=float(value), proposer=seat, status="active")
        c.accepted.add(seat)          # 提议者默认自己接受
        self.contracts.append(c)
        return c

    def get(self, cid: str):
        for c in self.contracts:
            if c.id == cid:
                return c
        return None

    def accept(self, seat: int, cid: str) -> bool:
        c = self.get(cid)
        if not c or c.status != "active":
            return False
        c.accepted.add(seat)
        return True

    def check(self, round_no: int, actuals: dict) -> list:
        """结算本轮契约：返回违约记录。"""
        out = []
        for c in self.contracts:
            if c.round_no != round_no or c.status != "active":
                continue
            broken = False
            for seat in sorted(c.accepted):
                got = float(actuals.get(seat, 0) or 0)
                if got > c.value + 1e-9:
                    broken = True
                    c.breaches.append({"seat": seat, "value": c.value, "actual": got})
                    out.append({"contract": c.id, "seat": seat,
                                "value": c.value, "actual": got})
            c.status = "broken" if broken else "kept"
        return out

    def round_contracts(self, round_no: int) -> list:
        return [c for c in self.contracts if c.round_no == round_no]

    def stats(self) -> dict:
        proposed = len(self.contracts)
        accepted = sum(len(c.accepted) for c in self.contracts)
        breaches = sum(len(c.breaches) for c in self.contracts)
        joined = accepted or 0
        return {"contracts_proposed": proposed,
                "contracts_accepted": accepted,
                "contract_breaches": breaches,
                "breach_rate": round(breaches / joined, 4) if joined else 0.0}

    def to_dict(self) -> list:
        return [c.to_dict() for c in self.contracts]