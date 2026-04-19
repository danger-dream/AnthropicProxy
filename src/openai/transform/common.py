"""OpenAI 两套对话接口的通用工具：字段白名单、usage 归一、SSE 帧工具。

所有函数为纯函数、无 I/O；调用方按需组合。
"""

from __future__ import annotations

import json
from typing import Any


# ─── 请求字段白名单 ──────────────────────────────────────────────
#
# 透传路径用：从下游请求体里只拷这些键给上游，把 proxy 内部字段（如 _api_key_name）
# 和上游不认的字段（如 previous_response_id 出现在 chat 上游时）过滤掉。
# 与官方文档对齐；新字段出现时在此处追加（MS-8 验收再扫一遍）。

CHAT_REQ_ALLOWED: frozenset[str] = frozenset({
    "model", "messages", "stream", "stream_options",
    "temperature", "top_p", "n",
    "max_completion_tokens", "max_tokens", "stop",
    "frequency_penalty", "presence_penalty",
    "logprobs", "top_logprobs", "logit_bias",
    "tools", "tool_choice", "parallel_tool_calls",
    "response_format", "modalities", "audio",
    "store", "metadata", "seed", "prediction",
    "reasoning_effort", "verbosity", "web_search_options",
    "service_tier", "user", "safety_identifier",
    "prompt_cache_key", "prompt_cache_retention",
})


RESPONSES_REQ_ALLOWED: frozenset[str] = frozenset({
    "model", "input", "stream", "stream_options", "instructions",
    "previous_response_id", "conversation", "context_management",
    "include", "temperature", "top_p", "top_logprobs",
    "max_output_tokens", "max_tool_calls",
    "tools", "tool_choice", "parallel_tool_calls",
    "text", "reasoning", "truncation",
    "store", "metadata", "prompt", "background",
    "service_tier", "user", "safety_identifier",
    "prompt_cache_key", "prompt_cache_retention",
})


def filter_chat_passthrough(body: dict) -> dict:
    """同协议 /v1/chat/completions 透传：保留白名单字段。"""
    return {k: v for k, v in body.items() if k in CHAT_REQ_ALLOWED}


def filter_responses_passthrough(body: dict) -> dict:
    """同协议 /v1/responses 透传：保留白名单字段。"""
    return {k: v for k, v in body.items() if k in RESPONSES_REQ_ALLOWED}


# ─── SSE 帧工具 ──────────────────────────────────────────────────


def sse_frame_chat(obj: dict) -> bytes:
    """构造 `data: {json}\\n\\n` 一帧。用于 translator / 错误收尾。"""
    payload = json.dumps(obj, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def sse_frame_responses(event: str, obj: dict) -> bytes:
    """构造 `event: <name>\\ndata: {json}\\n\\n` 一帧。"""
    payload = json.dumps(obj, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


def sse_done_chat() -> bytes:
    """Chat SSE 终止帧。"""
    return b"data: [DONE]\n\n"


# ─── usage 归一 ──────────────────────────────────────────────────
#
# 与 src/upstream.py 的 extract_usage_*_json 保持一致形状（4 键 anthropic 风味），
# 供 handler / translator 共用。

def extract_usage_chat(obj: Any) -> dict:
    if not isinstance(obj, dict):
        return _zero()
    u = obj.get("usage") or {}
    details = u.get("prompt_tokens_details") or {}
    return {
        "input_tokens": int(u.get("prompt_tokens", 0) or 0),
        "output_tokens": int(u.get("completion_tokens", 0) or 0),
        "cache_creation": 0,
        "cache_read": int(details.get("cached_tokens", 0) or 0),
    }


def extract_usage_responses(obj: Any) -> dict:
    if not isinstance(obj, dict):
        return _zero()
    u = obj.get("usage") or {}
    in_details = u.get("input_tokens_details") or {}
    return {
        "input_tokens": int(u.get("input_tokens", 0) or 0),
        "output_tokens": int(u.get("output_tokens", 0) or 0),
        "cache_creation": 0,
        "cache_read": int(in_details.get("cached_tokens", 0) or 0),
    }


def _zero() -> dict:
    return {"input_tokens": 0, "output_tokens": 0, "cache_creation": 0, "cache_read": 0}
