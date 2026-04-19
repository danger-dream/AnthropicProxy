"""会话亲和指纹。

核心设计（docs/06 §6.3）：同一会话在第 N 次请求到达与第 N-1 次请求完成
这两个时刻计算出的 hash 必然相等，据此把同一会话粘到同一渠道，避免
上游 prefix cache 失效。

查询（到达时）：去掉当前 user turn（messages[-1]），取剩下的最后两条 → hash
写入（完成时）：在 messages 末尾追加 assistant 回复，取最后两条 → hash

推导：
  N 次到达时 messages = [..., a_{N-1}, u_N]
    truncated = [..., a_{N-1}]   最后两条 = [u_{N-1}, a_{N-1}]
  N-1 次完成时 messages 曾是 [..., u_{N-1}]，加 a_{N-1} 后
    full = [..., u_{N-1}, a_{N-1}]  最后两条 = [u_{N-1}, a_{N-1}]
  两侧同形 → hash 相等。
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional


# 按 Anthropic Messages API 标准把每种 block 归一到稳定字段集合，
# 屏蔽两类来源的"噪声字段"，防止 hash 跑偏：
#   1) 客户端 cache_control ephemeral 标记随位置流动
#   2) 上游 SSE 中额外的非标字段（如 tool_use.caller={"type":"direct"}），
#      Claude Code 等客户端回发历史时会剔除，造成写入/查询两端不一致
_BLOCK_FIELDS: dict[str, tuple[str, ...]] = {
    "text":                  ("type", "text"),
    "thinking":              ("type", "thinking", "signature"),
    "redacted_thinking":     ("type", "data"),
    "tool_use":              ("type", "id", "name", "input"),
    "server_tool_use":       ("type", "id", "name", "input"),
    "mcp_tool_use":          ("type", "id", "name", "input", "server_name"),
    "tool_result":           ("type", "tool_use_id", "content", "is_error"),
    "mcp_tool_result":       ("type", "tool_use_id", "content", "is_error"),
    "image":                 ("type", "source"),
    "document":              ("type", "source", "title", "context", "citations"),
    "web_search_tool_result": ("type", "tool_use_id", "content"),
}

# message 顶层只保留稳定标识。上游回包上的 id / stop_reason / usage / model 等
# 都不应参与 fingerprint（客户端回发到历史里通常只带 role + content）。
_MSG_FIELDS: tuple[str, ...] = ("role", "content")


def _normalize_block(block):
    if not isinstance(block, dict):
        return block
    btype = block.get("type")
    wl = _BLOCK_FIELDS.get(btype)
    if wl is None:
        # 未知 block 类型：保底剥 cache_control，其它保留，避免误伤未来新类型
        return {k: v for k, v in block.items() if k != "cache_control"}
    # 对 content 字段递归（tool_result.content 可能嵌套 text/image block 列表）
    out = {}
    for k in wl:
        if k not in block:
            continue
        v = block[k]
        if k == "content" and isinstance(v, list):
            v = [_normalize_block(b) for b in v]
        out[k] = v
    return out


# thinking / redacted_thinking 是模型的中间推理，客户端回发到历史时策略不稳定
# （Claude Code 在某些场景直接丢弃），不应参与 fingerprint
_SKIP_BLOCK_TYPES = {"thinking", "redacted_thinking"}


def _normalize_msg(msg):
    """把一条 message 归一化为稳定的"可 hash"形状。"""
    if not isinstance(msg, dict):
        return msg
    out: dict = {}
    for k in _MSG_FIELDS:
        if k not in msg:
            continue
        v = msg[k]
        if k == "content":
            if isinstance(v, list):
                v = [
                    _normalize_block(b)
                    for b in v
                    if not (isinstance(b, dict) and b.get("type") in _SKIP_BLOCK_TYPES)
                ]
            # 字符串 content 保持原样
        out[k] = v
    return out


def _canon(msg_obj) -> str:
    """消息对象的 canonical JSON（稳定 key 排序 + 标准字段归一）。"""
    return json.dumps(
        _normalize_msg(msg_obj),
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )


def _make_hash(api_key_name: str, client_ip: str, msg_a, msg_b) -> str:
    raw = f"{api_key_name or ''}|{client_ip or ''}|{_canon(msg_a)}|{_canon(msg_b)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def fingerprint_query(api_key_name: str, client_ip: str, messages: list) -> Optional[str]:
    """请求到达时查询用。

    要求 messages 至少有 3 条（倒数第二条 + 第二条），否则返回 None
    （新会话无历史可锚定，跳过亲和）。
    """
    if not messages or len(messages) < 3:
        return None
    truncated = messages[:-1]
    last_two = truncated[-2:]
    return _make_hash(api_key_name, client_ip, last_two[0], last_two[1])


def fingerprint_write(api_key_name: str, client_ip: str,
                      messages: list, assistant_response: dict) -> Optional[str]:
    """响应完成时写入用。

    在 messages 末尾拼上本次产生的 assistant_response，取最后两条 hash。
    至少需要 2 条消息（当前请求 + assistant），少于则返回 None。
    """
    if not messages:
        return None
    full = list(messages)
    full.append(assistant_response)
    if len(full) < 2:
        return None
    last_two = full[-2:]
    return _make_hash(api_key_name, client_ip, last_two[0], last_two[1])
