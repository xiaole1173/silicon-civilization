"""注册表可靠性测试：损坏、备份恢复、BOM、绝不静默丢数据。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

import store  # noqa: E402


class StoreTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig = (store.DATA_DIR, store.MODELS_FILE, store.BACKUP_FILE)
        store.DATA_DIR = root
        store.MODELS_FILE = root / "models.json"
        store.BACKUP_FILE = root / "models.json.bak"
        store._ensure_file()

    def tearDown(self):
        store.DATA_DIR, store.MODELS_FILE, store.BACKUP_FILE = self._orig
        self._tmp.cleanup()

    def add(self, name, **kw):
        payload = {"name": name, "api_base": "https://api.deepseek.com/v1",
                   "model": "deepseek-chat", "api_key": "sk-placeholder-not-a-key"}
        payload.update(kw)
        model, errors = store.create_model(payload)
        self.assertEqual(errors, [], errors)
        return model


class TestStoreBasics(StoreTestBase):
    def test_create_and_list(self):
        self.add("甲")
        self.add("乙")
        names = [m["name"] for m in store.list_models()]
        self.assertEqual(names, ["甲", "乙"])

    def test_key_never_returned(self):
        model = self.add("甲")
        self.assertNotIn("api_key", model)
        self.assertTrue(model["api_key_set"])
        self.assertIn("****", model["api_key_masked"])

    def test_update_keeps_key_when_blank(self):
        model = self.add("甲")
        updated, errors, kind = store.update_model(model["id"], {"name": "甲改"})
        self.assertEqual(errors, [])
        self.assertTrue(updated["api_key_set"])
        raw = json.loads(store.MODELS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(raw["models"][0]["api_key"], "sk-placeholder-not-a-key")

    def test_default_protocol_and_validation(self):
        model = self.add("甲")
        self.assertEqual(model["protocol"], "chat_completions")
        _, errors = store.create_model({"name": "丙", "api_base": "https://x/v1",
                                        "model": "m", "protocol": "grpc"})
        self.assertTrue(errors)
        self.assertIn("协议", errors[0])

    def test_protocol_persisted(self):
        model = self.add("Claude", protocol="anthropic_messages")
        self.assertEqual(model["protocol"], "anthropic_messages")


class TestCorruptionSafety(StoreTestBase):
    def test_corrupt_file_raises_instead_of_empty(self):
        self.add("甲")
        self.add("乙")
        store.BACKUP_FILE.unlink(missing_ok=True)   # 没有备份可恢复时才该报错
        raw = store.MODELS_FILE.read_text(encoding="utf-8")
        store.MODELS_FILE.write_text(raw[:-15], encoding="utf-8")  # 截断
        with self.assertRaises(store.StoreError):
            store.list_models()

    def test_corrupt_file_quarantined(self):
        self.add("甲")
        store.BACKUP_FILE.unlink(missing_ok=True)
        store.MODELS_FILE.write_text("{ broken json", encoding="utf-8")
        with self.assertRaises(store.StoreError):
            store.list_models()
        quarantined = list(store.DATA_DIR.glob("models.corrupt-*.json"))
        self.assertTrue(quarantined, "损坏文件应另存一份以便抢救")

    def test_write_does_not_destroy_on_corruption(self):
        self.add("甲")
        store.BACKUP_FILE.unlink(missing_ok=True)
        original = store.MODELS_FILE.read_text(encoding="utf-8")
        store.MODELS_FILE.write_text(original[:-10], encoding="utf-8")
        broken = store.MODELS_FILE.read_text(encoding="utf-8")
        with self.assertRaises(store.StoreError):
            store.create_model({"name": "丙", "api_base": "https://x/v1", "model": "m"})
        # 关键断言：失败时文件不该被空列表覆盖
        self.assertEqual(store.MODELS_FILE.read_text(encoding="utf-8"), broken)
        self.assertNotEqual(store.MODELS_FILE.read_text(encoding="utf-8"), '{\n  "models": []\n}')

    def test_recovers_from_backup(self):
        self.add("甲")
        self.add("乙")
        self.assertTrue(store.BACKUP_FILE.exists(), "写入后应存在备份")
        backup = json.loads(store.BACKUP_FILE.read_text(encoding="utf-8"))
        self.assertTrue(backup["models"])
        store.MODELS_FILE.write_text("{ 坏掉的文件", encoding="utf-8")
        models = store.list_models()   # 应从备份恢复
        self.assertTrue(models)
        self.assertEqual(len(models), len(backup["models"]))

    def test_bom_file_is_tolerated(self):
        self.add("甲")
        raw = store.MODELS_FILE.read_text(encoding="utf-8")
        store.MODELS_FILE.write_bytes(b"\xef\xbb\xbf" + raw.encode("utf-8"))
        models = store.list_models()
        self.assertEqual(len(models), 1)

    def test_utf16_file_is_tolerated(self):
        self.add("甲")
        raw = json.loads(store.MODELS_FILE.read_text(encoding="utf-8"))
        store.MODELS_FILE.write_bytes(json.dumps(raw, ensure_ascii=False).encode("utf-16"))
        self.assertEqual(len(store.list_models()), 1)

    def test_empty_file_raises(self):
        store.MODELS_FILE.write_text("", encoding="utf-8")
        with self.assertRaises(store.StoreError):
            store.list_models()


class TestSlug(StoreTestBase):
    def test_chinese_name_gets_ascii_id(self):
        model = self.add("阿岚")
        self.assertRegex(model["id"], r"^[a-z0-9][a-z0-9-]*$", model["id"])
        self.assertTrue(model["id"].startswith("model-"))

    def test_ascii_name_kept(self):
        model = self.add("DeepSeek Chat")
        self.assertEqual(model["id"], "deepseek-chat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
