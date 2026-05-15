"""OAuth 账户标识符工具。

设计目标
--------
`email` 只是账户的**显示字段**，不是主键；真正的主键是联合键。
Claude 仍使用 ``claude:<email>``；OpenAI 使用
``openai:<workspace_id>``，其中 workspace_id 优先取 entry.workspace_id，
其次取 entry.chatgpt_account_id，二者都缺失时才回退到旧的 email。

调用约定
--------
- 对外展示：继续用 `email`（TG 菜单、通知、日志里的人类可读部分）
- 内部路由 / state_db / channel.key / 冷却 / 亲和：一律用 `account_key`
- channel.key 统一格式：``oauth:{account_key}``

本模块提供的工具函数专门负责上述拼接与解析，避免在各处散落 f-string。
"""

from __future__ import annotations

from typing import Any

from .oauth import (
    DEFAULT_PROVIDER as _DEFAULT_PROVIDER,
    normalize_provider as _normalize_provider,
)


def openai_workspace_id(acc: dict) -> str:
    """OpenAI OAuth 逻辑身份。

    `email` 对 OpenAI 只是展示字段；同一邮箱可以有多个 ChatGPT 工作区。
    Parrot 使用上游原始 workspace/chatgpt account id 作为逻辑身份，不做 hash。
    """
    for key in ("workspace_id", "chatgpt_account_id"):
        value = str(acc.get(key) or "").strip()
        if value:
            return value
    return ""


def account_identity(acc: dict) -> str:
    """账户 entry → provider 内部身份片段。"""
    provider = _normalize_provider(acc.get("provider") or _DEFAULT_PROVIDER)
    email = str(acc.get("email") or "")
    if provider == "openai":
        return openai_workspace_id(acc) or email
    return email


def account_key(acc_or_provider: dict | str, email: str | None = None) -> str:
    """构造标准 account_key。

    支持两种调用形式：
      - `account_key(acc_dict)`：从账户 entry 读取 provider 与身份字段
      - `account_key(provider, email)`：显式传 provider 与旧 email 身份
    """
    if isinstance(acc_or_provider, dict):
        provider = _normalize_provider(acc_or_provider.get("provider") or _DEFAULT_PROVIDER)
        return f"{provider}:{account_identity(acc_or_provider)}"
    provider = _normalize_provider(acc_or_provider or _DEFAULT_PROVIDER)
    return f"{provider}:{email or ''}"


def split_account_key(key: str) -> tuple[str, str]:
    """反向解析：``account_key`` → ``(provider, identity)``。

    - 合法三段式 `provider:email` → 精确拆分
    - 历史 email（不含 provider 前缀） → 兜底回退到 default provider
    """
    if not key:
        return (_DEFAULT_PROVIDER, "")
    if ":" in key:
        prov, _, rest = key.partition(":")
        prov = _normalize_provider(prov)
        if prov and rest:
            return (prov, rest)
    # 老数据 / 兜底：整段当 email
    return (_DEFAULT_PROVIDER, key)


def channel_key_for(acc_or_provider: dict | str, email: str | None = None) -> str:
    """构造 channel 层使用的 key：``oauth:{account_key}``。"""
    return f"oauth:{account_key(acc_or_provider, email)}"


def identity_from_channel_key(channel_key: str) -> str:
    """反向解析 channel key 得到 provider 内身份片段。"""
    if not channel_key.startswith("oauth:"):
        return channel_key
    body = channel_key[len("oauth:"):]
    _, identity = split_account_key(body)
    return identity


def email_from_channel_key(channel_key: str) -> str:
    """兼容旧调用名。

    对 Claude 返回 email；对 OpenAI 新 key 返回 workspace identity。真正需要
    展示 email 的路径应回查 account entry。
    """
    return identity_from_channel_key(channel_key)


def provider_from_channel_key(channel_key: str) -> str:
    """反向解析 channel key 得到 provider。"""
    if not channel_key.startswith("oauth:"):
        return _DEFAULT_PROVIDER
    body = channel_key[len("oauth:"):]
    prov, _ = split_account_key(body)
    return prov


def is_account_key(value: Any) -> bool:
    """粗略判断字符串是否是三段式 account_key（含合法 provider 前缀）。"""
    if not isinstance(value, str) or ":" not in value:
        return False
    prov = value.split(":", 1)[0]
    return _normalize_provider(prov) == prov and prov in ("claude", "openai")
