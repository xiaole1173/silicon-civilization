"""假的 OpenAI 兼容服务：支持 /chat/completions 与 /responses，且支持 SSE 流式。

用途：不需要 Key 就能验证"提示词 -> 思考/回答流 -> JSON 动作 -> 准入校验 -> 事件流 -> 网页"整条链路。
用法：python scripts/mock_llm_server.py   # 监听 127.0.0.1:8799
"""
from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8799


def parse_ctx(user_text: str) -> dict:
    seat = None
    m = re.search(r"你是座位 (\d+) 号", user_text)
    if m:
        seat = int(m.group(1))
    alive = []
    m = re.search(r"当前存活：([\d、]+)", user_text)
    if m:
        alive = [int(x) for x in m.group(1).split("、") if x.strip().isdigit()]
    return {"seat": seat, "alive": alive, "text": user_text}


def choose(user_text: str):
    ctx = parse_ctx(user_text)
    seat, alive = ctx["seat"], ctx["alive"]
    others = [s for s in alive if s != seat]
    first = others[0] if others else seat

    if "【夜间·暗中联络】" in user_text:
        return ({"kind": "speak", "text": "我建议刀 {} 号，他白天带节奏最凶。".format(first)},
                "队友都在，先统一目标：{} 号是最大威胁。".format(first))
    if "【夜间·目标选择】" in user_text:
        return ({"kind": "kill", "target": first, "reason": "验刀"},
                "挑一个发言最积极的先刀，试试水。")
    if "【夜间·核查】" in user_text:
        return ({"kind": "check", "target": first},
                "先确认 {} 号的身份，他前面带过节奏。".format(first))
    if "【夜间·守护】" in user_text:
        return ({"kind": "guard", "target": first},
                "按惯例守看起来像神职的 {} 号。".format(first))
    if "【夜间·医疗】" in user_text:
        m = re.search(r"今晚被袭击】座位 (\d+)", user_text)
        if m and "解药 1 瓶" in user_text:
            return ({"kind": "save", "target": int(m.group(1))},
                    "{} 号被刀，前期救人收益更高。".format(m.group(1)))
        return ({"kind": "pass"}, "今晚不急着用药，留到关键轮次。")
    if "【日间·公开陈述】" in user_text:
        return ({"kind": "speak", "text": "我是好人，我认为 {} 号有问题。".format(first)},
                "局势还不清楚，先给一个压力位。")
    if "【日间·表决】" in user_text:
        return ({"kind": "vote", "target": first, "reason": "压力位"},
                "把票集中在 {} 号身上，逼他表态。".format(first))
    if "【出局·反制】" in user_text:
        return ({"kind": "pass"}, "没有把握，先不开枪。")
    # 非狼人杀场景（例如圆桌讨论）：直接给一段自然语言
    return ({"_plain": "我说说我的看法：这个话题真正的难点不在选哪一个，而在于谁来维护、坏了谁修。"
                       "如果没有人负责，保留什么都会烂掉。"},
            "先想清楚立论，再给一句能被追问的理由。")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream(self, body: dict, thinking: str, content: str) -> None:
        responses = self.path.rstrip("/").endswith("/responses")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def chunk(payload: dict) -> None:
            line = "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()

        for i in range(0, len(thinking), 12):
            piece = thinking[i:i + 12]
            if responses:
                chunk({"type": "response.reasoning_summary_text.delta", "delta": piece})
            else:
                chunk({"choices": [{"index": 0, "delta": {"reasoning_content": piece}}]})
            time.sleep(0.02)

        for i in range(0, len(content), 8):
            piece = content[i:i + 8]
            if responses:
                chunk({"type": "response.output_text.delta", "delta": piece})
            else:
                chunk({"choices": [{"index": 0, "delta": {"content": piece}}]})
            time.sleep(0.02)

        if responses:
            chunk({"type": "response.completed", "response": {
                "id": "resp_mock", "object": "response", "model": body.get("model", "mock"),
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [{"type": "summary_text", "text": thinking}]},
                    {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": content}]},
                ],
            }})
        else:
            chunk({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop",
                                "message": {"role": "assistant", "content": content,
                                            "reasoning_content": thinking}}]})
            self.wfile.write("data: [DONE]\n\n".encode("utf-8"))
            self.wfile.flush()
        self.close_connection = True

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            body = {}
        messages = body.get("messages") or body.get("input") or []
        user_text = ""
        for msg in reversed(messages if isinstance(messages, list) else []):
            if isinstance(msg, dict) and msg.get("role") == "user":
                user_text = str(msg.get("content") or "")
                break
        action, thinking = choose(user_text)
        content = action.get("_plain") if isinstance(action.get("_plain"), str) \
            else json.dumps(action, ensure_ascii=False)
        time.sleep(0.05)

        if body.get("stream"):
            self._stream(body, thinking, content)
            return

        if self.path.rstrip("/").endswith("/responses"):
            self._send({
                "id": "resp_mock", "object": "response", "model": body.get("model", "mock"),
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": [{"type": "summary_text", "text": thinking}]},
                    {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": content}]},
                ],
                "usage": {"input_tokens": 120, "output_tokens": 60},
            })
            return

        self._send({
            "id": "chatcmpl-mock", "object": "chat.completion",
            "model": body.get("model", "mock"),
            "choices": [{
                "index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": content,
                            "reasoning_content": thinking},
            }],
            "usage": {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180},
        })


if __name__ == "__main__":
    print("mock llm server on http://127.0.0.1:%d/v1 (chat + responses + stream)" % PORT)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
