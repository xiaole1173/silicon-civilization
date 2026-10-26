"""Silicon Civilization · 本地服务（标准库实现，零依赖）

启动：
    python server/app.py            # 默认 http://127.0.0.1:8765
    python server/app.py 9000       # 指定端口

接口：
    GET    /api/health                       服务与注册表健康状态
    GET    /api/protocols                    支持的协议
    GET    /api/providers                    提供商预设
    GET    /api/models                       模型列表（key 已掩码）
    POST   /api/models                       新增模型
    GET    /api/models/{id}
    PUT    /api/models/{id}                  更新（key 留空=保留原 key）
    DELETE /api/models/{id}
    POST   /api/models/{id}/test             连通性自检（真实发一次请求）
    POST   /api/test-inline                  用请求体临时测连通（不写盘）
"""
from __future__ import annotations

import json
import mimetypes
import os
import queue
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
batch_progress = {}
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

import providers  # noqa: E402
import store  # noqa: E402
from engine.monitor import audit as audit_events  # noqa: E402
from base import plugin as plugin_mod  # noqa: E402
from base import runner as runner_mod  # noqa: E402

RUNS_DIR = ROOT / "runs"
TTS_DIR = ROOT / "data" / "tts_cache"
TTS_SCRIPT = ROOT / "scripts" / "tts.ps1"
DEFAULT_PAGE = "/web/models.html"
PORT = int(os.environ.get("PORT", "8765"))
HOST = os.environ.get("HOST", "127.0.0.1")


def json_bytes(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "SiliconCiv/0.2"
    protocol_version = "HTTP/1.1"

    # ---------- 基础工具 ----------
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json_bytes(obj), "application/json; charset=utf-8")

    def _error(self, status: int, message: str, errors=None) -> None:
        self._json(status, {"ok": False, "error": message, "errors": errors or []})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _guard(self, fn, *args):
        """统一异常出口：注册表坏了要明说，不能静默返回空列表。"""
        try:
            return fn(*args)
        except store.StoreError as exc:
            return self._error(500, str(exc))
        except providers.ProviderError as exc:
            return self._error(502, str(exc))
        except Exception as exc:  # pragma: no cover
            return self._error(500, "服务器内部错误：" + repr(exc))

    # ---------- 路由 ----------
    def do_OPTIONS(self):
        self._send(204, b"", "text/plain", {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        })

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/api/"):
            return self._guard(self._api_get, path)
        return self._guard(self._static, path)

    do_HEAD = do_GET

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        return self._guard(self._api_post, path)

    def do_PUT(self):
        path = urllib.parse.urlparse(self.path).path
        return self._guard(self._api_put, path)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        return self._guard(self._api_delete, path)

    # ---------- API ----------
    def _api_get(self, path: str):
        if path == "/api/health":
            return self._json(200, {"ok": True, "service": "silicon-civilization",
                                    "time": store._now(), "store": store.store_health()})
        if path == "/api/protocols":
            return self._json(200, {"ok": True, "protocols": [
                {"id": p, "label": providers.PROTOCOL_LABELS[p],
                 "path": providers.PROTOCOL_PATHS[p]} for p in providers.PROTOCOLS]})
        if path == "/api/providers":
            return self._json(200, {"ok": True, "providers": providers.PRESETS})
        if path == "/api/models":
            return self._json(200, {"ok": True, "models": store.list_models()})
        if path == "/api/runs":
            return self._json(200, {"ok": True, "runs": self._list_runs()})
        if path == "/api/plugins":
            return self._json(200, {"ok": True, "plugins": plugin_mod.list_plugins()})
        if path == "/api/sessions":
            return self._json(200, {"ok": True, "sessions": runner_mod.list_sessions()})
        if path == "/api/batches":
            return self._list_batches()
        if path.startswith("/api/batches/"):
            rest = path[len("/api/batches/"):].strip("/")
            bid, _, tail = rest.partition("/")
            if tail == "chart":
                return self._batch_file(bid, "chart.svg", "image/svg+xml")
            return self._batch_detail(bid)
        if path == "/api/replay":
            return self._json(200, {"ok": True, "logs": self._list_session_logs()})
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 3 and parts[1] == "sessions":
            sid = parts[2]
            if len(parts) == 4 and parts[3] == "stream":
                return self._stream_session(sid)
            if len(parts) == 4 and parts[3] == "log":
                return self._session_log(sid)
        if len(parts) == 4 and parts[1] == "replay" and parts[3] == "viz":
            return self._session_viz(parts[2])
            sess = runner_mod.get_session(sid)
            if not sess:
                return self._error(404, "会话不存在")
            return self._json(200, {"ok": True, "session": sess.snapshot()})
        if len(parts) >= 3 and parts[1] == "runs":
            name = parts[2]
            if len(parts) == 4 and parts[3] == "audit":
                return self._audit_run(name)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                offset = int((query.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            if len(parts) == 4 and parts[3] == "live":
                return self._read_live(name, offset)
            return self._read_run(name, offset)
        if len(parts) == 3 and parts[1] == "models":
            model = store.get_model(parts[2])
            if not model:
                return self._error(404, "模型不存在")
            return self._json(200, {"ok": True, "model": model})
        return self._error(404, "未知接口")

    # ---------- 对局日志 ----------
    def _run_path(self, name: str) -> Path | None:
        import re as _re
        if not _re.fullmatch(r"[A-Za-z0-9._-]+.jsonl", name or ""):
            return None
        target = (RUNS_DIR / name).resolve()
        try:
            target.relative_to(RUNS_DIR.resolve())
        except ValueError:
            return None
        return target if target.is_file() else None

    def _list_runs(self):
        out = []
        if not RUNS_DIR.is_dir():
            return out
        for path in sorted(RUNS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
            info = {"name": path.name, "size": path.stat().st_size,
                    "mtime": int(path.stat().st_mtime)}
            try:
                with path.open(encoding="utf-8", errors="replace") as fh:
                    first = fh.readline()
                meta = json.loads(first)
                info.update({"seed": meta.get("seed"), "players": meta.get("players"),
                             "scenario": meta.get("scenario"), "mode": meta.get("mode")})
            except Exception:
                pass
            out.append(info)
        return out

    def _read_run(self, name: str, offset: int):
        target = self._run_path(name)
        if not target:
            return self._error(404, "日志不存在")
        size = target.stat().st_size
        if offset > size:
            offset = 0
        with target.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read(2 * 1024 * 1024)          # 单次最多 2MB
        consumed = 0
        events = []
        for raw in chunk.split(b"\n"):
            if not raw.strip():
                consumed += len(raw) + 1
                continue
            try:
                events.append(json.loads(raw.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                break                                  # 末尾不完整行，下次再读
            consumed += len(raw) + 1
        return self._json(200, {"ok": True, "events": events, "size": size,
                                "next_offset": offset + min(consumed, len(chunk)),
                                "finished": any(e.get("event") == "game_end" for e in events)})

    def _read_live(self, name: str, offset: int):
        """增量读取"逐块思考/回答"侧车日志，供页面做打字机效果。"""
        base = name[:-6] if name.endswith(".jsonl") else name
        target = (RUNS_DIR / (base + ".live.jsonl")).resolve()
        try:
            target.relative_to(RUNS_DIR.resolve())
        except ValueError:
            return self._error(403, "禁止访问该路径")
        if not target.is_file():
            return self._json(200, {"ok": True, "events": [], "size": 0,
                                    "next_offset": 0, "finished": False})
        size = target.stat().st_size
        if offset > size:
            offset = 0
        with target.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read(1024 * 1024)
        consumed = 0
        events = []
        for raw in chunk.split(b"\n"):
            if not raw.strip():
                consumed += len(raw) + 1
                continue
            try:
                events.append(json.loads(raw.decode("utf-8")))
            except (json.JSONDecodeError, UnicodeDecodeError):
                break
            consumed += len(raw) + 1
        return self._json(200, {"ok": True, "events": events, "size": size,
                                "next_offset": offset + min(consumed, len(chunk))})

    def _audit_run(self, name: str):
        target = self._run_path(name)
        if not target:
            return self._error(404, "日志不存在")
        events = []
        with target.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return self._json(200, {"ok": True, "report": audit_events(events)})

    def _api_post(self, path: str):
        parts = [p for p in path.split("/") if p]
        if path == "/api/models":
            model, errors = store.create_model(self._body())
            if errors:
                return self._error(400, "；".join(errors), errors)
            return self._json(201, {"ok": True, "model": model})
        if len(parts) == 4 and parts[1] == "models" and parts[3] == "test":
            return self._test(parts[2])
        if path == "/api/test-inline":
            return self._test_inline()
        if path == "/api/tts":
            return self._tts()
        if path == "/api/sessions":
            return self._create_session()
        if path == "/api/batches":
            return self._start_batch()
        parts = [p for p in path.split("/") if p]
        if len(parts) == 4 and parts[1] == "sessions" and parts[3] == "resume":
            ok = runner_mod.resume_session(parts[2])
            if not ok:
                return self._error(409, "该会话不可续跑（需处于暂停状态）")
            return self._json(200, {"ok": True, "resumed": parts[2]})
        if len(parts) == 4 and parts[1] == "sessions" and parts[3] == "stop":
            ok = runner_mod.stop_session(parts[2], "用户手动结束")
            if not ok:
                return self._error(404, "会话不存在")
            return self._json(200, {"ok": True, "stopped": parts[2]})
        return self._error(404, "未知接口")

    # ---------- 批次 ----------
    def _batches_dirs(self):
        return [ROOT / "runs" / "batches", ROOT / "runs" / "experiments"]

    def _batches_dir(self):
        return ROOT / "runs" / "batches"

    def _find_batch_dir(self, bid: str):
        for base in self._batches_dirs():
            cand = base / bid
            if cand.is_dir():
                return cand
        return None

    def _list_batches(self):
        items = []
        dirs = []
        for base in self._batches_dirs():
            if base.is_dir():
                dirs.extend(list(base.glob("*/")))
        dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        if dirs:
            for d in dirs[:80]:
                summary_path = d / "summary.json"
                info = {"id": d.name, "mtime": int(d.stat().st_mtime),
                        "source": d.parent.name}
                if summary_path.exists():
                    try:
                        with summary_path.open(encoding="utf-8") as fh:
                            data = json.load(fh)
                        info.update({"runs": data.get("runs"), "executed": data.get("executed"),
                                     "errors": len(data.get("errors") or []),
                                     "concurrency": data.get("concurrency"),
                                     "has_report": bool(data.get("report"))})
                    except Exception:
                        pass
                items.append(info)
        return self._json(200, {"ok": True, "batches": items,
                                "progress": dict(batch_progress)})

    def _batch_detail(self, bid: str):
        d = self._find_batch_dir(bid)
        if d is None:
            return self._error(404, "批次不存在")
        out = {"ok": True, "id": bid, "rows": [], "report": "", "summary": {}}
        sp = d / "summary.json"
        if sp.exists():
            try:
                with sp.open(encoding="utf-8") as fh:
                    out["summary"] = json.load(fh)
            except Exception:
                pass
        idx = d / "index.csv"
        if idx.exists():
            try:
                import csv
                with idx.open(encoding="utf-8-sig") as fh:
                    out["rows"] = [dict(r) for r in csv.DictReader(fh)]
            except Exception:
                pass
        rp = d / "REPORT.md"
        if rp.exists():
            try:
                out["report"] = rp.read_text(encoding="utf-8")
            except Exception:
                pass
        out["has_chart"] = (d / "chart.svg").exists()
        return self._json(200, out)

    def _batch_file(self, bid: str, name: str, ctype: str):
        d = self._find_batch_dir(bid)
        if d is None:
            return self._error(404, "批次不存在")
        p = d / name
        if not p.exists():
            return self._error(404, "文件不存在")
        try:
            data = p.read_bytes()
        except Exception as exc:
            return self._error(500, repr(exc))
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _start_batch(self):
        body = self._body()
        plugin_id = str(body.get("plugin") or "commons")
        seeds = body.get("seeds") or "1-3"
        sweep = body.get("sweep") or ""
        concurrency = int(body.get("concurrency") or 1)
        models = int(body.get("models") or 6)
        scenario = str(body.get("scenario") or "")
        rounds = int(body.get("rounds") or 0)

        forced = str(body.get("seat_model") or "").strip()
        if forced:
            ids = [forced] * int(models)
        else:
            ids = [m["id"] for m in store.list_models() if m["id"] != "model-d3cf3bfe"]
        if not ids:
            return self._error(400, "模型库为空")
        seats = []
        for i, mid in enumerate(ids[:models], start=1):
            conf = store.get_model(mid, with_secret=True)
            if not conf:
                return self._error(400, "模型不存在：" + mid)
            seats.append({"name": "{}号".format(i), "model_conf": conf})

        def parse_seeds(text):
            out = []
            for part in str(text).split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    a, b = part.split("-", 1)
                    out.extend(range(int(a), int(b) + 1))
                else:
                    out.append(int(part))
            return out

        def parse_sweep(text):
            sw = {}
            for chunk in str(text or "").split(";"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                k, _, vals = chunk.partition("=")
                items = []
                for v in vals.split(","):
                    v = v.strip()
                    if not v:
                        continue
                    try:
                        items.append(int(v))
                    except ValueError:
                        try:
                            items.append(float(v))
                        except ValueError:
                            items.append(v)
                sw[k.strip()] = items
            return sw

        base_cfg = {}
        if scenario:
            base_cfg["scenario"] = scenario
        if rounds:
            base_cfg["rounds"] = rounds

        def worker():
            import base.batch as batch_mod
            batch_progress["state"] = "running"
            batch_progress["started"] = time.time()

            def progress(row, done, total):
                batch_progress.update({"done": done, "total": total,
                                       "last": row.get("run_id"),
                                       "state_run": row.get("state")})

            try:
                result = batch_mod.run_batch(
                    plugin_id, seats=seats, base_config=base_cfg,
                    sweep=parse_sweep(sweep), seeds=parse_seeds(seeds),
                    concurrency=concurrency, on_progress=progress)
                batch_progress.update({"state": "done", "batch_id": result.get("batch_id"),
                                       "report": result.get("report")})
            except Exception as exc:
                batch_progress.update({"state": "error", "error": repr(exc)[:200]})

        batch_progress.update({"state": "starting", "done": 0, "total": 0, "error": ""})
        threading.Thread(target=worker, daemon=True).start()
        return self._json(202, {"ok": True, "started": True,
                                "plugin": plugin_id, "seats": len(seats)})

    # ---------- 基座：会话 ----------
    def _list_session_logs(self):
        base = ROOT / "runs" / "sessions"
        items = []
        if base.is_dir():
            files = sorted(base.glob("*.jsonl"), key=lambda x: x.stat().st_mtime, reverse=True)
            for p in files[:80]:
                st = p.stat()
                items.append({"id": p.stem, "size": st.st_size, "mtime": int(st.st_mtime)})
        return items

    def _session_viz(self, sid):
        """把 JSONL 日志归一化成回放台需要的结构（与场景无关）。"""
        path = ROOT / "runs" / "sessions" / (sid + ".jsonl")
        if not path.exists():
            return self._error(404, "没有这局的日志")
        agents, rounds, order = {}, [], []
        world_series = []
        round_by_id = {}
        state_seq = []
        final = {}
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                t = ev.get("type")
                if t == "meta":
                    for a in ev.get("agents") or []:
                        agents[a["id"]] = {"id": a["id"], "name": a.get("name", ""),
                                           "role": a.get("role", ""),
                                           "model": a.get("model", ""),
                                           "actions": 0}
                elif t == "round_start":
                    rnd = ev.get("round") or {}
                    item = {"id": rnd.get("id"), "title": rnd.get("title", ""),
                            "subtitle": rnd.get("subtitle", ""),
                            "kind": rnd.get("kind", ""), "summary": "", "items": []}
                    rounds.append(item)
                    round_by_id[item["id"]] = item
                    order.append(item["id"])
                elif t == "round_end":
                    rnd = round_by_id.get(ev.get("round"))
                    if rnd:
                        rnd["summary"] = ev.get("summary", "")
                elif t == "message_start":
                    m = ev.get("message") or {}
                    meta = m.get("meta") or {}
                    rid = m.get("round") or meta.get("round")
                    rnd = round_by_id.get(rid)
                    sid_sender = m.get("sender")
                    if sid_sender is not None and sid_sender not in agents:
                        # 老日志没有 meta：从消息反推参与者
                        agents[sid_sender] = {"id": sid_sender,
                                              "name": m.get("sender_name") or ("%s 号" % sid_sender),
                                              "role": meta.get("role", ""),
                                              "model": meta.get("model", ""),
                                              "actions": 0}
                    if rnd is not None and sid_sender is not None:
                        act = meta.get("action") or {}
                        rnd["items"].append({
                            "id": m.get("id"), "seat": m.get("sender"),
                            "name": m.get("sender_name", ""),
                            "role": meta.get("role", ""),
                            "model": meta.get("model", ""),
                            "kind": act.get("kind") or ("speak" if m.get("kind") != "action" else ""),
                            "target": act.get("target"),
                            "text": "",
                            "thinking": "",
                            "latency_ms": meta.get("latency_ms"),
                            "failed": meta.get("ok") is False,
                        })
                        if m.get("sender") in agents:
                            agents[m["sender"]]["actions"] += 1
                elif t == "message_end":
                    mid = ev.get("id")
                    for rnd in rounds:
                        for it in rnd["items"]:
                            if it["id"] == mid:
                                it["text"] = ev.get("text") or ""
                                think = (ev.get("thinking") or "").strip()
                                it["thinking"] = think[:600]
                                meta = ev.get("meta") or {}
                                if meta.get("role"):
                                    it["role"] = meta["role"]
                                if meta.get("latency_ms"):
                                    it["latency_ms"] = meta["latency_ms"]
                                it["failed"] = meta.get("ok") is False
                                break
                elif t == "world":
                    world_series.append({"round": ev.get("round", 0),
                                         "stock": ev.get("stock"),
                                         "cap": ev.get("cap"),
                                         "scarcity": ev.get("scarcity")})
                elif t == "state":
                    state_seq.append({"alive": ev.get("alive") or [],
                                      "sheriff": ev.get("sheriff")})
                elif t == "session" and ev.get("state") == "ended":
                    final = {"winner": ev.get("winner"), "messages": ev.get("messages")}
        total_items = sum(len(r["items"]) for r in rounds)
        return self._json(200, {
            "ok": True, "id": sid,
            "agents": list(agents.values()),
            "rounds": rounds,
            "states": state_seq,
            "final": final,
            "world": world_series,
            "metrics": {"rounds": len(rounds), "actions": total_items,
                        "agents": len(agents)},
        })

    def _session_log(self, sid):
        """从 JSONL 日志重放：会话重启后依然可回看。"""
        path = ROOT / "runs" / "sessions" / (sid + ".jsonl")
        if not path.exists():
            return self._error(404, "没有这局的日志")
        events = []
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                if ev.get("type") == "delta":   # 增量可由 message_end 还原，跳过以减小体积
                    continue
                events.append(ev)
        return self._json(200, {"ok": True, "events": events, "id": sid})

    def _create_session(self):
        body = self._body()
        plugin = plugin_mod.get_plugin(str(body.get("plugin") or ""))
        if not plugin:
            return self._error(400, "插件不存在：" + str(body.get("plugin")))
        seats_in = body.get("seats") or []
        if not seats_in:
            return self._error(400, "至少需要一个座位")
        seats = []
        for idx, seat in enumerate(seats_in, start=1):
            model_id = str(seat.get("model_id") or "")
            conf = store.get_model(model_id, with_secret=True)
            if not conf:
                return self._error(400, "座位 {} 的模型不存在：{}".format(idx, model_id))
            seats.append({
                "name": str(seat.get("name") or "{}号".format(idx)),
                "model_conf": conf,
                "persona": str(seat.get("persona") or ""),
            })
        sid = "s" + time.strftime("%m%d-%H%M%S")
        session = runner_mod.create_session(
            sid, plugin, body.get("config") or {}, seats,
            title=str(body.get("title") or plugin.name))
        runner_mod.start(session)
        return self._json(201, {"ok": True, "session": session.snapshot(),
                                "stream": "/api/sessions/{}/stream".format(sid)})

    def _sse(self, event: dict) -> bool:
        """写一条 SSE 事件；返回 False 表示客户端断开。"""
        try:
            payload = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _stream_session(self, sid: str):
        sess = runner_mod.get_session(sid)
        if not sess:
            return self._error(404, "会话不存在")
        q = sess.broker.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        head = sess.snapshot()
        head.pop("messages", None)
        if not self._sse({"type": "snapshot", **head}):
            sess.broker.unsubscribe(q)
            return
        for m in sess.messages:
            if not self._sse({"type": "message_start", "message": m.to_dict()}):
                sess.broker.unsubscribe(q)
                return
            if m.text or m.thinking:
                self._sse({"type": "message_end", "id": m.id, "text": m.text,
                           "thinking": m.thinking, "meta": m.meta})

        try:
            while True:
                try:
                    event = q.get(timeout=15)
                except queue.Empty:
                    if not self._sse({"type": "ping", "ts": int(time.time())}):
                        break
                    continue
                if not self._sse(event):
                    break
                if event.get("type") == "session" and event.get("state") in ("ended", "closed"):
                    break
        finally:
            sess.broker.unsubscribe(q)
            self.close_connection = True

    def _api_put(self, path: str):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[1] == "models":
            model, errors, kind = store.update_model(parts[2], self._body())
            if kind == "missing":
                return self._error(404, "模型不存在")
            if errors:
                return self._error(400, "；".join(errors), errors)
            return self._json(200, {"ok": True, "model": model})
        return self._error(404, "未知接口")

    def _api_delete(self, path: str):
        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[1] == "models":
            if not store.delete_model(parts[2]):
                return self._error(404, "模型不存在")
            return self._json(200, {"ok": True})
        return self._error(404, "未知接口")

    def _test(self, model_id: str):
        conf = store.get_model(model_id, with_secret=True)
        if not conf:
            return self._error(404, "模型不存在")
        result = providers.test_model(conf)
        store.record_test(model_id, result)
        return self._json(200, {"ok": True, "result": result})

    def _test_inline(self):
        payload = self._body()
        conf = {
            "name": str(payload.get("name") or "inline"),
            "protocol": str(payload.get("protocol") or providers.PROTOCOLS[0]),
            "api_base": str(payload.get("api_base") or "").strip(),
            "model": str(payload.get("model") or "").strip(),
            "api_key": str(payload.get("api_key") or ""),
            "api_key_env": str(payload.get("api_key_env") or ""),
            "temperature": payload.get("temperature", 0),
            "max_tokens": payload.get("max_tokens", 16),
        }
        if not conf["api_base"] or not conf["model"]:
            return self._error(400, "Base URL 和模型名必填")
        result = providers.test_model(conf)
        return self._json(200, {"ok": True, "result": result})

    # ---------- 语音合成 ----------
    VOICES = {
        "kangkang": "Microsoft Kangkang",
        "huihui": "Microsoft Huihui",
        "yaoyao": "Microsoft Yaoyao",
        "zira": "Microsoft Zira Desktop",
    }

    def _tts(self):
        """把一段文字合成为 WAV（Windows SAPI，本地离线，零下载）。结果按内容哈希缓存。"""
        body = self._body()
        text = str(body.get("text") or "").strip()
        if not text:
            return self._error(400, "text 不能为空")
        text = text[:600]
        voice_key = str(body.get("voice") or "kangkang").strip().lower()
        voice = self.VOICES.get(voice_key, self.VOICES["kangkang"])
        try:
            rate = int(body.get("rate") or 0)
        except (TypeError, ValueError):
            rate = 0
        rate = max(-10, min(10, rate))

        import hashlib
        digest = hashlib.md5((text + "|" + voice + "|" + str(rate)).encode("utf-8")).hexdigest()
        TTS_DIR.mkdir(parents=True, exist_ok=True)
        target = TTS_DIR / (digest + ".wav")
        if not target.is_file():
            tmp_txt = TTS_DIR / (digest + ".txt")
            tmp_txt.write_text(text, encoding="utf-8")
            try:
                import subprocess
                proc = subprocess.run(
                    ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(TTS_SCRIPT),
                     "-TextFile", str(tmp_txt), "-OutFile", str(target),
                     "-VoiceName", voice, "-Rate", str(rate)],
                    capture_output=True, timeout=60,
                )
            except Exception as exc:
                return self._error(500, "语音合成失败：{}".format(exc))
            finally:
                try:
                    tmp_txt.unlink()
                except Exception:
                    pass
            if proc.returncode != 0 or not target.is_file():
                detail = (proc.stderr or b"").decode("utf-8", "replace")[:300]
                return self._error(500, "语音合成失败（SAPI 返回 {}）：{}".format(proc.returncode, detail))
        data = target.read_bytes()
        return self._send(200, data, "audio/wav", {"Cache-Control": "public, max-age=86400"})

    # ---------- 静态文件 ----------
    def _static(self, path: str):
        if path in ("/", "/index.html"):
            path = DEFAULT_PAGE
        rel = urllib.parse.unquote(path.lstrip("/"))
        target = (ROOT / rel).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            return self._error(403, "禁止访问该路径")
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self._error(404, "文件不存在：" + rel)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)


def main() -> None:
    port = PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    server = ThreadingHTTPServer((HOST, port), Handler)
    print("Silicon Civilization server running at http://%s:%d" % (HOST, port))
    print("  model manager : http://%s:%d/web/models.html" % (HOST, port))
    print("  replay board  : http://%s:%d/viz/index.html" % (HOST, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
