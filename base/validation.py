"""发言校验：把"明显编造"挡在出局之前。

基座只做通用校验（引用不存在的座位）；场景插件可以加自己的规则（如狼人杀的动作合法性）。
校验失败不是判死，而是"打回重说"——给模型一次改正机会。
"""
from __future__ import annotations

import re

_SEAT_REF = re.compile(r"(\d{1,2})\s*号")


def referenced_seats(text: str) -> list:
    return sorted({int(m.group(1)) for m in _SEAT_REF.finditer(text or "")})


def default_validator(session, agent, text: str) -> tuple[bool, str]:
    """通用校验：提到的座位必须真实存在。"""
    known = set(session.agents.keys())
    unknown = [s for s in referenced_seats(text) if s not in known]
    if unknown:
        return False, "你提到了不存在的座位：{}。在场只有 {}".format(
            "、".join(str(s) + " 号" for s in unknown), "、".join(str(s) + " 号" for s in sorted(known)))
    return True, ""


def compose_validator(plugin_validator, base_validator=default_validator):
    """组合校验：先跑通用，再跑插件自带。"""
    def _check(session, agent, text):
        ok, reason = (base_validator or (lambda *a: (True, "")))(session, agent, text)
        if not ok:
            return False, reason
        if plugin_validator:
            return plugin_validator(session, agent, text)
        return True, ""
    return _check
