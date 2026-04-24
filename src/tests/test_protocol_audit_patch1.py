"""协议审计 Patch 1 回归测试 — P0 阻塞修复。

覆盖 02-bug-findings.md 的 P0 项：
  - #1 裸消息（无 type 但有 role）应被识别为 message
  - #2 model 字段缺失应返回 400 而不是 KeyError
  - #9 ResponseUsage 的 input_tokens_details / output_tokens_details 始终写入
  - #15 chat 端 role=function 老协议消息应映射为 function_call_output
  - #20 stream_r2c 在 response.completed 之后应短路后续事件（防止收尾后又被改写）
"""

from __future__ import annotations

# 测试隔离
import os as _ap_os, sys as _ap_sys
_ap_sys.path.insert(0, _ap_os.path.dirname(_ap_os.path.dirname(_ap_os.path.dirname(_ap_os.path.abspath(__file__)))))
from src.tests import _isolation
_isolation.isolate()

import json
import pytest


def _import_modules():
    from src.openai.transform import (
        chat_to_responses, responses_to_chat, guard, common,
        stream_r2c, stream_c2r,
    )
    return {
        "chat_to_responses": chat_to_responses,
        "responses_to_chat": responses_to_chat,
        "guard": guard,
        "common": common,
        "stream_r2c": stream_r2c,
        "stream_c2r": stream_c2r,
    }


# ───────── #1 裸消息识别 ─────────


def test_bug1_bare_message_translates_to_chat(m):
    responses_to_chat = m["responses_to_chat"]
    body = {"model": "x", "input": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": [{"type": "input_text", "text": "hi"}]},
    ]}
    out = responses_to_chat.translate_request(body)
    assert len(out["messages"]) == 2
    assert out["messages"][0]["role"] == "system"
    assert out["messages"][0]["content"] == "sys"
    assert out["messages"][1]["role"] == "user"
    assert out["messages"][1]["content"] == "hi"


def test_bug1_bare_message_minimal(m):
    responses_to_chat = m["responses_to_chat"]
    body = {"model": "x", "input": [{"role": "user", "content": "hi"}]}
    out = responses_to_chat.translate_request(body)
    assert out["messages"] == [{"role": "user", "content": "hi"}]


def test_bug1_bare_assistant_message(m):
    responses_to_chat = m["responses_to_chat"]
    body = {"model": "x", "input": [
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": [{"type": "output_text", "text": "A"}]},
        {"role": "user", "content": "Q2"},
    ]}
    out = responses_to_chat.translate_request(body)
    assert len(out["messages"]) == 3
    assert out["messages"][1]["role"] == "assistant"
    assert out["messages"][1]["content"] == "A"


# ───────── #2 缺失 model 拒绝 ─────────


def test_bug2_responses_ingress_rejects_missing_model(m):
    guard = m["guard"]
    with pytest.raises(guard.GuardError) as exc_info:
        guard.guard_responses_ingress({"input": [{"role": "user", "content": "hi"}]})
    assert exc_info.value.status == 400
    assert "model" in exc_info.value.message.lower()


def test_bug2_chat_ingress_rejects_missing_model(m):
    guard = m["guard"]
    with pytest.raises(guard.GuardError) as exc_info:
        guard.guard_chat_ingress({"messages": [{"role": "user", "content": "hi"}]})
    assert exc_info.value.status == 400
    assert "model" in exc_info.value.message.lower()


def test_bug2_empty_string_model_also_rejected(m):
    guard = m["guard"]
    with pytest.raises(guard.GuardError):
        guard.guard_responses_ingress({"model": "", "input": []})
    with pytest.raises(guard.GuardError):
        guard.guard_chat_ingress({"model": "", "messages": []})


# ───────── #9 ResponseUsage 必填字段 ─────────


def test_bug9_response_usage_required_fields_zero_cached(m):
    common = m["common"]
    usage = common.build_response_usage(
        input_tokens=10, output_tokens=5, cached_tokens=0, reasoning_tokens=0
    )
    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 5
    assert usage["total_tokens"] == 15
    # spec: ResponseUsage.input_tokens_details required
    assert "input_tokens_details" in usage
    assert usage["input_tokens_details"] == {"cached_tokens": 0}
    # spec: ResponseUsage.output_tokens_details required
    assert "output_tokens_details" in usage
    assert usage["output_tokens_details"] == {"reasoning_tokens": 0}


def test_bug9_response_usage_with_cached_and_reasoning(m):
    common = m["common"]
    usage = common.build_response_usage(
        input_tokens=100, output_tokens=50, cached_tokens=30, reasoning_tokens=20
    )
    assert usage["input_tokens_details"]["cached_tokens"] == 30
    assert usage["output_tokens_details"]["reasoning_tokens"] == 20
    assert usage["total_tokens"] == 150


def test_bug9_responses_to_chat_usage_zero_details(m):
    """responses_to_chat._usage_chat_to_resps 必须始终带 details。"""
    responses_to_chat = m["responses_to_chat"]
    chat_resp = {
        "id": "cmpl-1",
        "model": "x",
        "choices": [{"message": {"role": "assistant", "content": "hi"},
                      "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    out = responses_to_chat.translate_response(chat_resp, model="x")
    assert "input_tokens_details" in out["usage"]
    assert out["usage"]["input_tokens_details"]["cached_tokens"] == 0
    assert "output_tokens_details" in out["usage"]
    assert out["usage"]["output_tokens_details"]["reasoning_tokens"] == 0


def test_bug9_stream_c2r_usage_details_in_terminal(m):
    stream_c2r = m["stream_c2r"]
    tr = stream_c2r.StreamTranslator(model="x")
    chunks = []
    for chunk in tr.feed(b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n'):
        chunks.append(chunk)
    for chunk in tr.feed(b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\n'):
        chunks.append(chunk)
    for chunk in tr.close():
        chunks.append(chunk)
    raw = b"".join(chunks).decode()
    # 找 response.completed
    completed = None
    for block in raw.split("\n\n"):
        if "response.completed" in block and "data:" in block:
            data_line = next(l for l in block.split("\n") if l.startswith("data:"))
            completed = json.loads(data_line[5:].strip())
            break
    assert completed is not None
    usage = completed["response"]["usage"]
    assert "input_tokens_details" in usage
    assert "output_tokens_details" in usage


def test_bug9_stream_r2c_usage_details(m):
    stream_r2c = m["stream_r2c"]
    tr = stream_r2c.StreamTranslator(model="x", include_usage=True)
    chunks = []
    for c in tr.feed(b'event: response.completed\ndata: {"response":{"status":"completed","usage":{"input_tokens":5,"output_tokens":3,"total_tokens":8}}}\n\n'):
        chunks.append(c)
    for c in tr.close():
        chunks.append(c)
    raw = b"".join(chunks).decode()
    # 取最后一个带 usage 的 chunk
    usage_obj = None
    for block in raw.split("\n\n"):
        if not block.startswith("data:") or "[DONE]" in block:
            continue
        try:
            obj = json.loads(block[5:].strip())
        except Exception:
            continue
        if "usage" in obj:
            usage_obj = obj["usage"]
    assert usage_obj is not None
    assert "prompt_tokens_details" in usage_obj
    assert usage_obj["prompt_tokens_details"]["cached_tokens"] == 0
    assert "completion_tokens_details" in usage_obj


# ───────── #15 role=function 老协议 ─────────


def test_bug15_chat_function_role_translates_to_function_call_output(m):
    chat_to_responses = m["chat_to_responses"]
    body = {
        "model": "x",
        "messages": [
            {"role": "user", "content": "what is the weather?"},
            {"role": "assistant", "content": None,
              "function_call": {"name": "get_weather", "arguments": "{}"}},
            {"role": "function", "name": "get_weather", "content": "sunny"},
        ],
    }
    out = chat_to_responses.translate_request(body)
    items = out["input"]
    # 最后应是 function_call_output（而非 message role=function）
    last = items[-1]
    assert last["type"] == "function_call_output"
    assert "sunny" in last["output"]
    # 确保没有 role=function 的 message item
    for it in items:
        if it.get("type") == "message":
            assert it.get("role") != "function"


# ───────── #20 stream_r2c terminal short-circuit ─────────


def test_bug20_completed_short_circuits_subsequent_events(m):
    stream_r2c = m["stream_r2c"]
    tr = stream_r2c.StreamTranslator(model="x")
    # 先送 text delta
    list(tr.feed(b'event: response.output_text.delta\ndata: {"delta":"hello"}\n\n'))
    # 再送 completed（带 stop）
    list(tr.feed(b'event: response.completed\ndata: {"response":{"status":"completed"}}\n\n'))
    assert tr.state.terminal_status == "completed"
    # 此时再来一个 text.delta（异常上游），应被短路
    out_after = b"".join(tr.feed(b'event: response.output_text.delta\ndata: {"delta":"BAD"}\n\n'))
    assert b"BAD" not in out_after
