"""T5：对局快照与续跑。"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import base.persistence as persistence  # noqa: E402
from base import plugin as plugin_mod  # noqa: E402
from base import runner as runner_mod  # noqa: E402


def _seats(n=3):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "mock-x", "api_key": "x"}} for i in range(1, n + 1)]


class TestSnapshotRoundTrip(unittest.TestCase):
    def _session(self, sid):
        plugin = plugin_mod.get_plugin("commons")
        s = runner_mod.create_session(
            sid, plugin, {"scenario": "scenarios/commons.yaml", "rounds": 3,
                          "regen_rate": 0.05}, _seats(3), "快照测试")
        plugin.setup(s)
        s.add_message("public", 1, kind="speak", text="测试一句话")
        s.open_round("取用", "第 1 轮")
        s.close_round(s.rounds[-1], "共取 3")
        return s, plugin

    def test_save_and_restore(self):
        s, plugin = self._session("t-persist-1")
        path = persistence.save(s)
        self.assertTrue(os.path.exists(path))
        data = json.load(open(path, encoding="utf-8"))
        self.assertEqual(data["scenario"], "commons")
        self.assertTrue(data["messages"], "消息要落盘")
        self.assertIn("world", data["meta"], "世界状态要落盘")

        restored = persistence.restore(data, plugin)
        self.assertEqual(restored.id, s.id)
        self.assertEqual(len(restored.messages), len(s.messages))
        self.assertEqual(len(restored.rounds), len(s.rounds))
        self.assertTrue(hasattr(restored.meta.get("world"), "extract"),
                        "world 应被重建为对象而不是字典")

    def test_running_becomes_paused(self):
        s, plugin = self._session("t-persist-2")
        s.state = "running"
        data = json.loads(json.dumps(persistence_and_dump(s)))
        restored = persistence.restore(data, plugin)
        self.assertEqual(restored.state, "paused", "运行中快照恢复后应为暂停态")


def persistence_and_dump(session):
    path = persistence.save(session)
    return json.load(open(path, encoding="utf-8"))


class TestRunnerLoadsCheckpoints(unittest.TestCase):
    def test_ensure_loaded_picks_up_snapshot(self):
        plugin = plugin_mod.get_plugin("commons")
        s = runner_mod.create_session(
            "t-persist-3", plugin, {"scenario": "scenarios/commons.yaml", "rounds": 2},
            _seats(2), "加载测试")
        plugin.setup(s)
        persistence.save(s)
        runner_mod._LOADED = False
        ids = [x["id"] for x in runner_mod.list_sessions()]
        self.assertIn("t-persist-3", ids, "重启后应能从快照加载会话")


if __name__ == "__main__":
    unittest.main(verbosity=2)
