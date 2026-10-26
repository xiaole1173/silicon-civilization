"""批量运行器：条件矩阵、断点续跑、指标落盘。"""
from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "server"))

import providers  # noqa: E402
from base import batch as batch_mod  # noqa: E402


def _seats(n=3):
    return [{"name": "{}号".format(i),
             "model_conf": {"protocol": "chat_completions",
                            "api_base": "http://127.0.0.1:9/v1",
                            "model": "fake", "api_key": "x"}} for i in range(1, n + 1)]


def fake_call(conf, messages, **kw):
    return {"choices": [{"finish_reason": "stop",
                         "message": {"content": "我觉得可以先讨论一下公共资源。"}}]}


class TestConditionPlan(unittest.TestCase):
    def test_single_condition_when_no_sweep(self):
        self.assertEqual(batch_mod.build_conditions({}), [{}])

    def test_cartesian_product(self):
        conds = batch_mod.build_conditions({"communication": ["on", "off"],
                                            "regen_rate": [0.02, 0.05]})
        self.assertEqual(len(conds), 4)
        self.assertIn({"communication": "off", "regen_rate": 0.05}, conds)

    def test_run_plan_ids_unique(self):
        specs = batch_mod.plan_runs("b1", {"communication": ["on", "off"]}, [1, 2])
        ids = [s.run_id for s in specs]
        self.assertEqual(len(ids), 4)
        self.assertEqual(len(set(ids)), 4)


class TestBatchRun(unittest.TestCase):
    def test_runs_and_writes_index(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(providers, "call_chat", side_effect=fake_call):
            summary = batch_mod.run_batch(
                "discussion", seats=_seats(3),
                base_config={"rounds": 1, "topic": "测试"},
                sweep={"communication": ["on", "off"]}, seeds=[1, 2],
                out_root=td, resume=True)
            self.assertEqual(summary["runs"], 4)
            self.assertEqual(summary["executed"], 4)
            self.assertEqual(len(summary["errors"]), 0)
            rows = list(csv.DictReader(open(summary["index"], encoding="utf-8-sig")))
            self.assertEqual(len(rows), 4)
            # 指标由插件声明、基座收集
            self.assertIn("m_utterances", rows[0])
            self.assertTrue(os.path.exists(summary["manifest"]))
            man = json.load(open(summary["manifest"], encoding="utf-8"))
            self.assertEqual(man["plugin"], "discussion")

    def test_resume_skips_completed(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(providers, "call_chat", side_effect=fake_call):
            first = batch_mod.run_batch("discussion", seats=_seats(3),
                                        base_config={"rounds": 1},
                                        seeds=[1, 2], out_root=td)
            self.assertEqual(first["executed"], 2)
            # 同条件重跑：批次 id 由条件哈希决定 → 落在同一目录 → 全部跳过
            index = first["index"]
            rows = list(csv.DictReader(open(index, encoding="utf-8-sig")))
            self.assertEqual(len(rows), 2)
            second = batch_mod.run_batch("discussion", seats=_seats(3),
                                         base_config={"rounds": 1},
                                         seeds=[1, 2], out_root=td,
                                         resume=True)
            self.assertEqual(second["batch_id"], first["batch_id"],
                             "同条件应复用同一批次 id")
            self.assertEqual(second["executed"], 0, "已完成的对局应被跳过")
            self.assertEqual(second["skipped"], 2)


class TestCommunicationSwitch(unittest.TestCase):
    def test_off_hides_others_messages(self):
        from base import plugin as pm
        from base import runner as rm
        plugin = pm.get_plugin("discussion")
        seats = _seats(3)
        s1 = rm.create_session("t-comm-on", plugin, {"rounds": 1}, seats, "on")
        plugin.setup(s1)
        s2 = rm.create_session("t-comm-off", plugin, {"rounds": 1, "communication": "off"},
                               seats, "off")
        plugin.setup(s2)
        # 造两条来自别人的消息
        for s in (s1, s2):
            s.add_message("public", 2, kind="speak", text="我是2号")
        self.assertTrue(s1.visible_to(1, s1.messages[-1]), "沟通开时可见")
        self.assertFalse(s2.visible_to(1, s2.messages[-1]), "沟通关时不可见")


class TestBatchConcurrency(unittest.TestCase):
    def test_concurrent_runs_all_recorded(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(providers, "call_chat", side_effect=fake_call):
            summary = batch_mod.run_batch(
                "discussion", seats=_seats(3), base_config={"rounds": 1},
                seeds=[1, 2, 3, 4], out_root=td, concurrency=3)
            self.assertEqual(summary["executed"], 4)
            self.assertEqual(summary["concurrency"], 3)
            self.assertEqual(len(summary["errors"]), 0)
            rows = list(csv.DictReader(open(summary["index"], encoding="utf-8-sig")))
            self.assertEqual(len(rows), 4)
            ids = {r["run_id"] for r in rows}
            self.assertEqual(len(ids), 4, "并发下不能丢局或互相覆盖")


if __name__ == "__main__":
    unittest.main(verbosity=2)
