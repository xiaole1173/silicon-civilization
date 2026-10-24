"""模型注册表：把「名称 / 协议 / api_base / api_key / model」持久化到 data/models.json。

安全与可靠性约定：
- api_key 只存在服务器本地文件里，任何读取接口都只返回掩码；
- 读文件失败**绝不静默返回空列表**（那会导致下一次写入把数据覆盖销毁）；
- 每次写入前把当前文件复制成 models.json.bak，读失败时自动从备份恢复；
- 兼容带 BOM / UTF-16 的文件（PowerShell、记事本可能这么写）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_FILE = DATA_DIR / "models.json"
BACKUP_FILE = DATA_DIR / "models.json.bak"

_LOCK = threading.Lock()

DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 512
DEFAULT_PROTOCOL = "chat_completions"
PROTOCOLS = ("chat_completions", "responses", "anthropic_messages")


class StoreError(RuntimeError):
    """注册表读写失败：宁可报错，也不能静默丢数据。"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _ensure_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not MODELS_FILE.exists():
        MODELS_FILE.write_text(json.dumps({"models": []}, ensure_ascii=False, indent=2),
                               encoding="utf-8")


def _decode(raw: bytes) -> str:
    """兼容 BOM 与 UTF-16（PowerShell 5.1 / 记事本可能这么存）。"""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def _load(path: Path) -> dict:
    raw = path.read_bytes()
    if not raw.strip():
        raise StoreError("文件为空：" + str(path))
    data = json.loads(_decode(raw))
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise StoreError("文件结构不对（缺少 models 数组）：" + str(path))
    return data


def _quarantine(path: Path) -> str:
    """把损坏文件另存一份，供人工抢救。"""
    target = path.with_name("models.corrupt-{}.json".format(time.strftime("%Y%m%d-%H%M%S")))
    try:
        shutil.copy2(path, target)
        return str(target)
    except Exception:
        return ""


def _read_all() -> dict:
    """读注册表。失败时先尝试备份恢复；再失败就抛错（绝不返回空表）。"""
    _ensure_file()
    try:
        return _load(MODELS_FILE)
    except Exception as exc:
        quarantined = _quarantine(MODELS_FILE)
        if BACKUP_FILE.exists():
            try:
                data = _load(BACKUP_FILE)
                _write_all(data, make_backup=False)
                return data
            except Exception:
                pass
        raise StoreError(
            "模型注册表读取失败：{}。已把损坏文件另存为 {}，请检查 data/ 目录；"
            "为避免覆盖数据，本次操作已中止。".format(exc, quarantined or "（另存失败）")
        ) from None


def _write_all(data: dict, *, make_backup: bool = True) -> None:
    """原子写入：先备份当前的完好文件，再写临时文件并替换。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if make_backup and MODELS_FILE.exists():
        try:
            shutil.copy2(MODELS_FILE, BACKUP_FILE)
        except Exception:
            pass
    tmp = MODELS_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, MODELS_FILE)


def slugify(text: str) -> str:
    """生成 ASCII-only 的 id。

    id 会出现在 URL 里，绝不能包含非 ASCII 字符（http.client 拼请求行会直接失败）。
    中文名称会退化成 model-<hash>，可读名称保留在 name 字段。
    """
    raw = (text or "").strip()
    s = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if len(s) >= 2:
        return s
    return "model-" + hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def is_safe_id(text: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", (text or "").strip()))


def mask_key(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return "****"
    return k[:5] + "****" + k[-4:]


def public_view(model: dict) -> dict:
    """对外视图：绝不包含明文 key。"""
    return {
        "id": model.get("id", ""),
        "name": model.get("name", ""),
        "protocol": model.get("protocol", DEFAULT_PROTOCOL),
        "provider": model.get("provider", "custom"),
        "api_base": model.get("api_base", ""),
        "model": model.get("model", ""),
        "api_key_masked": mask_key(model.get("api_key", "")),
        "api_key_set": bool((model.get("api_key") or "").strip()),
        "api_key_env": model.get("api_key_env", ""),
        "temperature": model.get("temperature", DEFAULT_TEMPERATURE),
        "max_tokens": model.get("max_tokens", DEFAULT_MAX_TOKENS),
        "notes": model.get("notes", ""),
        "created_at": model.get("created_at", ""),
        "updated_at": model.get("updated_at", ""),
        "last_test": model.get("last_test") or {},
    }


def _clean(payload: dict, existing: dict | None = None) -> tuple:
    """把请求体规整成模型字典；返回 (model, errors)。"""
    errors = []
    base = dict(existing or {})

    name = str(payload.get("name", base.get("name", "")) or "").strip()
    if not name:
        errors.append("名称不能为空")

    protocol = str(payload.get("protocol", base.get("protocol", DEFAULT_PROTOCOL))
                   or DEFAULT_PROTOCOL).strip()
    if protocol not in PROTOCOLS:
        errors.append("协议只能是：" + " / ".join(PROTOCOLS))

    provider = str(payload.get("provider", base.get("provider", "custom")) or "custom").strip()
    api_base = str(payload.get("api_base", base.get("api_base", "")) or "").strip()
    if not api_base:
        errors.append("API Base URL 不能为空")
    elif not (api_base.startswith("http://") or api_base.startswith("https://")):
        errors.append("API Base URL 必须以 http:// 或 https:// 开头")

    model_name = str(payload.get("model", base.get("model", "")) or "").strip()
    if not model_name:
        errors.append("模型名（model）不能为空")

    # api_key 三态：有值=更新；空串=保留；空串+clear_key=true=清空
    api_key = base.get("api_key", "")
    if "api_key" in payload:
        incoming = str(payload.get("api_key") or "").strip()
        if incoming:
            api_key = incoming
        elif payload.get("clear_key"):
            api_key = ""

    api_key_env = str(payload.get("api_key_env", base.get("api_key_env", "")) or "").strip()

    try:
        temperature = float(payload.get("temperature", base.get("temperature", DEFAULT_TEMPERATURE)))
    except (TypeError, ValueError):
        temperature = DEFAULT_TEMPERATURE
    temperature = max(0.0, min(2.0, temperature))

    try:
        max_tokens = int(payload.get("max_tokens", base.get("max_tokens", DEFAULT_MAX_TOKENS)))
    except (TypeError, ValueError):
        max_tokens = DEFAULT_MAX_TOKENS
    max_tokens = max(16, min(32000, max_tokens))

    want_id = str(payload.get("id") or "").strip()
    if want_id and not is_safe_id(want_id):
        errors.append("id 只能用 a-z、0-9 和连字符（会出现在 URL 里）")

    model = {
        "id": base.get("id") or (want_id if want_id else slugify(name)),
        "name": name,
        "protocol": protocol,
        "provider": provider,
        "api_base": api_base.rstrip("/"),
        "model": model_name,
        "api_key": api_key,
        "api_key_env": api_key_env,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "notes": str(payload.get("notes", base.get("notes", "")) or "").strip(),
        "created_at": base.get("created_at") or _now(),
        "updated_at": _now(),
        "last_test": base.get("last_test") or {},
    }
    return model, errors


def list_models() -> list:
    with _LOCK:
        data = _read_all()
    return [public_view(m) for m in data["models"]]


def get_model(model_id: str, *, with_secret: bool = False):
    with _LOCK:
        data = _read_all()
    for m in data["models"]:
        if m.get("id") == model_id:
            return m if with_secret else public_view(m)
    return None


def create_model(payload: dict) -> tuple:
    model, errors = _clean(payload)
    if errors:
        return None, errors
    with _LOCK:
        data = _read_all()
        existing_ids = {m.get("id") for m in data["models"]}
        if model["id"] in existing_ids:
            suffix = 2
            while "{}-{}".format(model["id"], suffix) in existing_ids:
                suffix += 1
            model["id"] = "{}-{}".format(model["id"], suffix)
        data["models"].append(model)
        _write_all(data)
    return public_view(model), []


def update_model(model_id: str, payload: dict) -> tuple:
    with _LOCK:
        data = _read_all()
        for idx, m in enumerate(data["models"]):
            if m.get("id") != model_id:
                continue
            merged, errors = _clean(payload, existing=m)
            if errors:
                return None, errors, "invalid"
            merged["id"] = model_id
            data["models"][idx] = merged
            _write_all(data)
            return public_view(merged), [], "ok"
    return None, ["模型不存在"], "missing"


def delete_model(model_id: str) -> bool:
    with _LOCK:
        data = _read_all()
        before = len(data["models"])
        data["models"] = [m for m in data["models"] if m.get("id") != model_id]
        if len(data["models"]) == before:
            return False
        _write_all(data)
        return True


def record_test(model_id: str, result: dict) -> None:
    with _LOCK:
        data = _read_all()
        for m in data["models"]:
            if m.get("id") == model_id:
                m["last_test"] = {
                    "ok": bool(result.get("ok")),
                    "latency_ms": int(result.get("latency_ms") or 0),
                    "error": str(result.get("error") or "")[:400],
                    "protocol": str(result.get("protocol") or ""),
                    "at": _now(),
                }
                break
        _write_all(data)


def store_health() -> dict:
    """给监控用：资产文件状态，不暴露任何密钥。"""
    info = {"file": str(MODELS_FILE), "exists": MODELS_FILE.exists(),
            "backup": BACKUP_FILE.exists()}
    try:
        with _LOCK:
            data = _read_all()
        info["ok"] = True
        info["count"] = len(data["models"])
    except StoreError as exc:
        info["ok"] = False
        info["error"] = str(exc)
    return info
