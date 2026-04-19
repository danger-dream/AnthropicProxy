"""Capability guard：在 ingress 入口 + upstream 选型阶段拦截无法完成的请求。

MS-2 只实现"同 ingress 自检"与"跨变体未实现"的拒绝路径：
  - Chat ingress：拒绝 `n>1` / `audio` 输出（本版本不支持，暂 400）
  - Responses ingress：拒绝 `background:true` / `conversation` 对象（首版不做）
  - 当需要跨变体翻译但 `openai.translation.enabled=false` 时，handler 在调度阶段
    自然得到空候选，返回 503 —— 不在此处干预。

真正的跨变体翻译死角（built-in tools / previous_response_id 无 Store 等）
在 MS-3 / MS-5 补齐。
"""

from __future__ import annotations

from typing import Any


class GuardError(Exception):
    """带 HTTP status + OpenAI error type + 人类可读 message，供 handler 映射。"""

    def __init__(self, status: int, err_type: str, message: str,
                 *, param: str | None = None):
        super().__init__(message)
        self.status = int(status)
        self.err_type = err_type
        self.message = message
        self.param = param


def _fail(status: int, err_type: str, message: str, *, param: str | None = None):
    raise GuardError(status, err_type, message, param=param)


# ─── Chat ingress ────────────────────────────────────────────────

def guard_chat_ingress(body: dict) -> None:
    """Chat 入口自检（不管上游）：拒绝本 proxy 不支持的特性。

    现阶段拒绝：
      - `n>1`：本 proxy 不聚合多候选
      - `audio` 输出（modalities 含 "audio"）：本版本不支持 audio 输出
    """
    from typing import Any as _Any  # noqa: F401
    if not isinstance(body, dict):
        _fail(400, "invalid_request_error", "request body must be a JSON object")

    n = body.get("n")
    if isinstance(n, int) and n > 1:
        _fail(400, "invalid_request_error",
              f"n={n} is not supported by this proxy", param="n")

    modalities = body.get("modalities")
    if isinstance(modalities, list) and "audio" in modalities:
        _fail(400, "invalid_request_error",
              "audio output modality is not supported by this proxy",
              param="modalities")


# ─── Responses ingress ───────────────────────────────────────────

def guard_responses_ingress(body: dict, *, store_enabled: bool = True) -> None:
    """Responses 入口自检。

    - background:true → 400（首版不支持异步模式）
    - conversation 对象 → 400（首版不支持 conversation 资源，仅 previous_response_id）
    - previous_response_id 带了但 Store 关闭 → 400

    跨变体特有的 built-in tools 等在上游选型阶段（OpenAIApiChannel.build_upstream_request
    或 MS-3 的 responses_to_chat.guard）再拦一次，这里只做 ingress 无关检查。
    """
    if not isinstance(body, dict):
        _fail(400, "invalid_request_error", "request body must be a JSON object")

    if body.get("background") is True:
        _fail(400, "invalid_request_error",
              "background responses are not supported by this proxy",
              param="background")

    if "conversation" in body:
        _fail(400, "invalid_request_error",
              "conversation resource is not yet supported; use previous_response_id instead",
              param="conversation")

    if body.get("previous_response_id") and not store_enabled:
        _fail(400, "invalid_request_error",
              "previous_response_id requires openai.store.enabled=true",
              param="previous_response_id")
