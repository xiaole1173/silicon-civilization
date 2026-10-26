"""Provider presets and multi-protocol chat calls.

支持三种协议（同一层适配器，调用方无感）：
- chat_completions   POST {base}/chat/completions    （OpenAI 兼容，绝大多数厂商）
- responses          POST {base}/responses           （OpenAI Responses API）
- anthropic_messages POST {base}/messages            （Anthropic Messages API）

只依赖标准库（urllib），课堂上零安装即可跑。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

PROTOCOLS = ("chat_completions", "responses", "anthropic_messages")

PROTOCOL_LABELS = {
    "chat_completions": "OpenAI 兼容（chat/completions）",
    "responses": "OpenAI Responses API（responses）",
    "anthropic_messages": "Anthropic Messages（messages）",
}

PROTOCOL_PATHS = {
    "chat_completions": "/chat/completions",
    "responses": "/responses",
    "anthropic_messages": "/messages",
}

PRESETS = [
    {
        "id": "deepseek", "label": "DeepSeek",
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-chat", "env": "DEEPSEEK_API_KEY",
        "protocol": "chat_completions",
    },
    {
        "id": "dashscope", "label": "阿里云百炼（通义）",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus", "env": "DASHSCOPE_API_KEY",
        "protocol": "chat_completions",
    },
    {
        "id": "zhipu", "label": "智谱 GLM",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus", "env": "ZHIPU_API_KEY",
        "protocol": "chat_completions",
    },
    {
        "id": "moonshot", "label": "月之暗面 Kimi",
        "api_base": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k", "env": "MOONSHOT_API_KEY",
        "protocol": "chat_completions",
    },
    {
        "id": "openai", "label": "OpenAI",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini", "env": "OPENAI_API_KEY",
        "protocol": "chat_completions",
    },
    {
        "id": "openai_responses", "label": "OpenAI（Responses 协议）",
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini", "env": "OPENAI_API_KEY",
        "protocol": "responses",
    },
    {
        "id": "anthropic", "label": "Anthropic Claude",
        "api_base": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-5", "env": "ANTHROPIC_API_KEY",
        "protocol": "anthropic_messages",
    },
    {
        "id": "openrouter", "label": "OpenRouter",
        "api_base": "https://openrouter.ai/api/v1",
        "model": "deepseek/deepseek-chat", "env": "OPENROUTER_API_KEY",
        "protocol": "chat_completions",
    },
    {
        "id": "ollama", "label": "本地 Ollama（无需 key）",
        "api_base": "http://localhost:11434/v1",
        "model": "qwen2.5:7b", "env": "",
        "protocol": "chat_completions",
    },
    {
        "id": "vllm", "label": "本地 vLLM / LM Studio",
        "api_base": "http://localhost:8000/v1",
        "model": "your-local-model", "env": "",
        "protocol": "chat_completions",
    },
    {
        "id": "custom", "label": "自定义（自行填 Base URL）",
        "api_base": "", "model": "", "env": "",
        "protocol": "chat_completions",
    },
]

PRESET_BY_ID = {p["id"]: p for p in PRESETS}


class ProviderError(RuntimeError):
    """上游模型服务返回的错误，携带可读原因。"""

    def __init__(self, message: str, status: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


def resolve_protocol(conf: dict) -> str:
    proto = str((conf or {}).get("protocol") or "chat_completions").strip()
    if proto not in PROTOCOLS:
        raise ProviderError("未知协议：" + proto + "（支持：" + " / ".join(PROTOCOLS) + "）")
    return proto


def join_url(api_base: str, protocol: str) -> str:
    base = (api_base or "").strip().rstrip("/")
    if not base:
        raise ProviderError("API Base URL 为空")
    return base + PROTOCOL_PATHS[protocol]


def resolve_key(conf: dict) -> str:
    key = str((conf or {}).get("api_key") or "").strip()
    if key:
        return key
    env_name = str((conf or {}).get("api_key_env") or "").strip()
    if env_name:
        return str(os.environ.get(env_name) or "").strip()
    return ""


def build_request(conf: dict, messages: list, *, max_tokens: int | None = None,
                  temperature: float | None = None, stream: bool = False) -> dict:
    """按协议构造请求（纯函数，便于单测）：返回 {url, headers, payload}。"""
    protocol = resolve_protocol(conf)
    model_name = str((conf.get("model") or "")).strip()
    if not model_name:
        raise ProviderError("模型名（model）为空")
    key = resolve_key(conf)
    temp = conf.get("temperature", 0.7) if temperature is None else temperature
    mt = conf.get("max_tokens") if max_tokens is None else max_tokens

    headers = {"Content-Type": "application/json"}
    url = join_url(conf.get("api_base", ""), protocol)

    if protocol == "chat_completions":
        payload = {"model": model_name, "messages": messages, "temperature": temp}
        if mt:
            payload["max_tokens"] = int(mt)
        if stream:
            payload["stream"] = True
        if conf.get("stream_usage"):
            payload["stream_options"] = {"include_usage": True}
        if key:
            headers["Authorization"] = "Bearer " + key
        return {"url": url, "headers": headers, "payload": payload}

    if protocol == "responses":
        # Responses API：input 可传消息数组；上限字段名是 max_output_tokens
        payload = {"model": model_name, "input": messages, "temperature": temp}
        if mt:
            payload["max_output_tokens"] = int(mt)
        if stream:
            payload["stream"] = True
        if key:
            headers["Authorization"] = "Bearer " + key
        return {"url": url, "headers": headers, "payload": payload}

    if protocol == "anthropic_messages":
        system_parts = []
        chat_messages = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                system_parts.append(str(content))
            elif role in ("user", "assistant"):
                chat_messages.append({"role": role, "content": content})
        payload = {
            "model": model_name,
            "max_tokens": int(mt or 512),
            "messages": chat_messages,
            "temperature": temp,
        }
        if stream:
            payload["stream"] = True
        if system_parts:
            payload["system"] = "\n".join(system_parts)
        if key:
            headers["x-api-key"] = key
            headers["anthropic-version"] = "2023-06-01"
        return {"url": url, "headers": headers, "payload": payload}

    raise ProviderError("未实现的协议：" + protocol)


def _http_error_text(status: int, body: str) -> str:
    hint = {
        400: "请求被拒绝（400）：参数或模型名可能不对",
        401: "认证失败：API Key 无效或未授权",
        403: "被拒绝（403）：Key 无权限或地区限制",
        404: "接口不存在（404）：Base URL 多半少了或多了 /v1，或协议选错",
        413: "请求过大（413）",
        429: "触发限流或余额不足（429）",
        500: "上游服务错误（500）",
        502: "上游网关错误（502）",
        503: "上游不可用（503）",
    }.get(status, "HTTP " + str(status))
    snippet = (body or "").strip().replace("\n", " ")[:300]
    return hint + ("；详情：" + snippet if snippet else "")


def _guard_body(raw) -> None:
    """网关有时返回登录页/HTML：直接报清楚，别让上层当成"空回答"。"""
    try:
        head = (raw or b"")[:200] if isinstance(raw, (bytes, bytearray)) else str(raw)[:200].encode()
        text = head.decode("utf-8", "ignore").lstrip().lower()
    except Exception:
        return
    if text.startswith("<!doctype html") or text.startswith("<html"):
        raise ProviderError("网关返回的是网页（可能需要登录/VPN），不是模型响应")


def call_chat(conf: dict, messages: list, *, resolution: dict | None = None,
              max_tokens: int | None = None, temperature: float | None = None,
              timeout: float = 60.0, extra_body: dict | None = None,
              stream: bool | None = None, on_delta=None,
              thinking_cap: int | None = None) -> dict:
    """调用任意已配置协议的端点，返回原始 JSON（流式则返回合成结果）。

    有些网关对部分模型强制要求 stream=true；
    这里遇到 "Stream must be set to true" 时自动改用流式重试一次，调用方不用关心。
    """
    _ = resolution
    conf = conf or {}
    use_stream = bool(conf.get("stream", False)) if stream is None else bool(stream)
    if on_delta is not None:
        use_stream = True          # 要实时进度就必须流式
    try:
        return _call_once(conf, messages, max_tokens=max_tokens, temperature=temperature,
                          timeout=timeout, extra_body=extra_body, stream=use_stream,
                          on_delta=on_delta, thinking_cap=thinking_cap)
    except ProviderError as exc:
        text = str(exc).lower()
        if (not use_stream) and exc.status == 400 and "stream must be set to true" in text:
            return _call_once(conf, messages, max_tokens=max_tokens, temperature=temperature,
                              timeout=timeout, extra_body=extra_body, stream=True,
                              on_delta=on_delta)
        # 该模型不支持流式：退回落式一次，保证不因此丢回合
        if use_stream and exc.status in (400, 405, 501):
            return _call_once(conf, messages, max_tokens=max_tokens, temperature=temperature,
                              timeout=timeout, extra_body=extra_body, stream=False,
                              on_delta=None)
        raise


def _call_once(conf, messages, *, max_tokens, temperature, timeout, extra_body, stream,
               on_delta=None, thinking_cap=None) -> dict:
    protocol = resolve_protocol(conf)
    req_spec = build_request(conf, messages, max_tokens=max_tokens,
                             temperature=temperature, stream=stream)
    payload = req_spec["payload"]
    if extra_body:
        payload.update(extra_body)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = dict(req_spec["headers"])
    if stream:
        headers["Accept"] = "text/event-stream"
    request = urllib.request.Request(req_spec["url"], data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            if stream:
                import time as _time
                return _read_stream(resp, protocol, on_delta,
                                    deadline=_time.time() + float(timeout),
                                    thinking_cap=thinking_cap)
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:800]
        except Exception:
            pass
        raise ProviderError(_http_error_text(exc.code, body), exc.code, body) from None
    except urllib.error.URLError as exc:
        raise ProviderError("无法连接该地址：" + str(exc.reason)) from None
    except TimeoutError:
        raise ProviderError("请求超时（{} 秒）".format(timeout)) from None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ProviderError("返回内容不是 JSON：" + raw[:300]) from None


def _read_stream(resp, protocol: str, on_delta=None, deadline: float | None = None,
                 thinking_cap: int | None = None) -> dict:
    """解析 SSE 流：边解析边回调增量（on_delta(kind, 片段)），最后拼成完整响应。

    deadline（time.time() 绝对时刻）用于防"细水长流"：socket 超时只管单次读取，
    模型若一直缓慢吐字，单次调用可能永远不返回，拖住整局。

    thinking_cap：思考字数闸门。推理模型会无限思考（实测能吐 1.7 万字还不给正文），
    一旦思考超过上限且还没有任何正文，就立刻掐断，交给上层重试并改用更短的预算。
    """
    text_parts: list = []
    think_parts: list = []
    think_len = 0
    capped = False
    final_obj = None

    def push(kind: str, piece) -> None:
        nonlocal think_len, capped
        if not isinstance(piece, str) or not piece:
            return
        if kind == "thinking":
            think_parts.append(piece)
            think_len += len(piece)
            if (thinking_cap is not None and think_len > thinking_cap and not text_parts):
                capped = True        # 只想不说：掐断，交给上层重试
        else:
            text_parts.append(piece)
        if on_delta is not None:
            try:
                on_delta(kind, piece)
            except Exception:
                pass

    import time as _time
    for raw_line in resp:
        if deadline is not None and _time.time() > deadline:
            break
        if capped:
            break
        line = raw_line.decode("utf-8", "replace").strip()
        if not line or line.startswith(":") or line.startswith("event:"):
            continue
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            if chunk == "[DONE]":
                break
            continue
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if protocol == "responses":
            kind = obj.get("type")
            if kind == "response.output_text.delta":
                push("answer", obj.get("delta"))
            elif kind in ("response.reasoning_summary_text.delta",
                          "response.reasoning_text.delta"):
                push("thinking", obj.get("delta"))
            elif kind in ("response.completed", "response.incomplete"):
                final_obj = obj.get("response") or final_obj
        elif protocol == "anthropic_messages":
            if obj.get("type") == "content_block_delta":
                delta = obj.get("delta") or {}
                if delta.get("type") == "thinking_delta":
                    push("thinking", delta.get("thinking"))
                else:
                    push("answer", delta.get("text"))
        else:
            for choice in obj.get("choices") or []:
                delta = choice.get("delta") or {}
                pushed_think = bool(delta.get("reasoning_content"))
                pushed_text = bool(delta.get("content"))
                push("thinking", delta.get("reasoning_content"))
                push("answer", delta.get("content"))
                message = choice.get("message") or {}
                # 有些实现最后一条只给完整内容：只有在没收到增量时才用，否则会重复
                if not pushed_text and not text_parts:
                    push("answer", message.get("content"))
                if not pushed_think and not think_parts:
                    push("thinking", message.get("reasoning_content"))

    text = "".join(text_parts)
    thinking = "".join(think_parts)
    marker = {"_thinking_capped": True} if capped else {}
    if protocol == "responses":
        if isinstance(final_obj, dict):
            out = dict(final_obj)
            out["_stream"] = True
            if not out.get("output_text") and text:
                out["output_text"] = text
            if thinking and not out.get("_reasoning"):
                out["_reasoning"] = thinking
            out.update(marker)
            return out
        return dict({"output_text": text, "_reasoning": thinking, "_stream": True}, **marker)
    if protocol == "anthropic_messages":
        content = []
        if thinking:
            content.append({"type": "thinking", "thinking": thinking})
        content.append({"type": "text", "text": text})
        return dict({"content": content, "_stream": True}, **marker)
    message = {"content": text}
    if thinking:
        message["reasoning_content"] = thinking
    return dict({"choices": [{"message": message}], "_stream": True}, **marker)


def extract_text(resp: dict, protocol: str = "chat_completions") -> str:
    """按协议从响应里取出首条文本。"""
    if not isinstance(resp, dict):
        return ""
    try:
        if protocol == "responses":
            if isinstance(resp.get("output_text"), str):
                return resp["output_text"]
            parts = []
            for item in resp.get("output") or []:
                for chunk in item.get("content") or []:
                    if chunk.get("type") in ("output_text", "text"):
                        parts.append(str(chunk.get("text") or ""))
            return "".join(parts)
        if protocol == "anthropic_messages":
            parts = []
            for chunk in resp.get("content") or []:
                if chunk.get("type") == "text":
                    parts.append(str(chunk.get("text") or ""))
            return "".join(parts)
        # 默认 chat_completions
        choices = resp.get("choices") or []
        if not choices:
            return ""
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(str(i.get("text", "")) for i in content
                           if isinstance(i, dict) and i.get("type") == "text")
        return ""
    except Exception:
        return ""


def extract_reasoning(resp: dict, protocol: str = "chat_completions") -> str:
    """取出模型的思考内容（不同协议位置不同）。没有就返回空串。"""
    if not isinstance(resp, dict):
        return ""
    parts = []
    try:
        if protocol == "responses":
            if isinstance(resp.get("_reasoning"), str) and resp["_reasoning"].strip():
                parts.append(resp["_reasoning"])
            for item in resp.get("output") or []:
                if item.get("type") != "reasoning":
                    continue
                for chunk in item.get("summary") or []:
                    if chunk.get("type") == "summary_text":
                        parts.append(str(chunk.get("text") or ""))
                for chunk in item.get("content") or []:
                    if chunk.get("type") in ("reasoning_text", "text"):
                        parts.append(str(chunk.get("text") or ""))
        elif protocol == "anthropic_messages":
            for chunk in resp.get("content") or []:
                if chunk.get("type") in ("thinking", "redacted_thinking"):
                    parts.append(str(chunk.get("thinking") or chunk.get("text") or ""))
        else:
            choices = resp.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                for key in ("reasoning_content", "reasoning", "thinking"):
                    value = message.get(key)
                    if isinstance(value, str) and value.strip():
                        parts.append(value)
    except Exception:
        return ""
    return "\n".join(p.strip() for p in parts if p and p.strip())


def test_model(conf: dict, timeout: float = 60.0) -> dict:
    """连通性自检：发一次最小请求，返回 ok / latency_ms / reply / error / protocol。"""
    started = time.time()
    protocol = "chat_completions"
    try:
        protocol = resolve_protocol(conf)
        # 推理型模型会把预算先花在 reasoning 上，给太小会导致"通了但没文本"
        resp = call_chat(conf, [{"role": "user", "content": "回复两个字：连通"}],
                         max_tokens=512, temperature=0, timeout=timeout)
        latency = int((time.time() - started) * 1000)
        reply = extract_text(resp, protocol).strip()
        return {"ok": True, "latency_ms": latency, "reply": reply[:200],
                "error": "", "protocol": protocol}
    except ProviderError as exc:
        latency = int((time.time() - started) * 1000)
        return {"ok": False, "latency_ms": latency, "reply": "",
                "error": str(exc), "protocol": protocol}
    except Exception as exc:  # pragma: no cover
        latency = int((time.time() - started) * 1000)
        return {"ok": False, "latency_ms": latency, "reply": "",
                "error": repr(exc), "protocol": protocol}
