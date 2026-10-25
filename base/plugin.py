"""插件协议：任何人写一个 plugins/<name>/plugin.py 就能接入新场景。

约定：
    class Plugin(BaseScenario):
        id = "discussion"
        name = "圆桌讨论"
        description = "..."
        default_config = {...}          # 页面上会渲染成表单
        def system_text(self, session): return "规则/背景（稳定块，放最前）"
        def setup(self, session):       # 建频道、建参与者
        def run(self, session):         # 阻塞循环，用 session.ask(...) 说话
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"


class BaseScenario:
    id = "base"
    name = "未命名场景"
    description = ""
    default_config: dict = {}

    # ---------- 供基座调用 ----------
    def system_text(self, session) -> str:
        return ""

    def setup(self, session) -> None:
        raise NotImplementedError

    def run(self, session) -> None:
        raise NotImplementedError

    # ---------- 可选钩子 ----------
    def facts(self, session, agent) -> dict:
        """事实卡：返回 {事实名: 值}，每轮会重新喂给模型（防记错）。"""
        return {}

    def validate(self, session, agent, text: str) -> tuple[bool, str]:
        """发言校验：返回 (是否合格, 不合格原因)。不合格会带着原因让模型重说。"""
        return True, ""

    def metrics(self, session) -> dict:
        """声明本场景的指标（基座收集、聚合、导出）。通用统计用 base.metrics。"""
        return {}

    def outcome(self, session) -> dict:
        """一局结论（胜方、轮数等），写进批次索引。"""
        return {}

    # ---------- 工具 ----------
    def merged_config(self, config: dict) -> dict:
        merged = dict(self.default_config)
        merged.update(config or {})
        return merged


_REGISTRY: dict[str, BaseScenario] = {}


def discover() -> dict[str, BaseScenario]:
    """扫描 plugins/ 下所有含 plugin.py 的目录并实例化。"""
    if _REGISTRY:
        return _REGISTRY
    if not PLUGINS_DIR.is_dir():
        return _REGISTRY
    for entry in sorted(PLUGINS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if not (entry / "plugin.py").is_file():
            continue
        try:
            module = importlib.import_module("plugins.{}.plugin".format(entry.name))
            for attr in vars(module).values():
                if (isinstance(attr, type) and issubclass(attr, BaseScenario)
                        and attr is not BaseScenario):
                    inst = attr()
                    _REGISTRY[inst.id] = inst
        except Exception as exc:  # 插件写坏了不影响其它插件
            print("[plugins] 跳过 {}：{}".format(entry.name, exc))
    return _REGISTRY


def get_plugin(plugin_id: str) -> BaseScenario | None:
    return discover().get(plugin_id)


def list_plugins() -> list:
    out = []
    for p in discover().values():
        out.append({"id": p.id, "name": p.name, "description": p.description,
                    "default_config": p.default_config})
    return out
