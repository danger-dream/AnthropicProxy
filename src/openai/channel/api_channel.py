"""OpenAI 家族 API 渠道。

由 `src/channel/registry.py` 的 factory 分派触发：config 中 protocol 为
`openai-chat` 或 `openai-responses` 的 channel entry 会实例化本类。

MS-2：实现同协议透传（chat→chat / responses→responses）。跨变体请求
（chat ingress 打到 responses 上游、或反之）暂时抛 NotImplementedError，
由 MS-3 起的 transform/stream_*.py 接入翻译器。
"""

from __future__ import annotations

import json
from typing import Optional

from ...channel.base import Channel, ChannelDisplay, UpstreamRequest
from ..transform import common


# User-Agent 故意不伪装成官方 SDK：上游看到 proxy 身份便于排错，也避免与
# anthropic 家族的 CC 伪装语义混淆。
_UA = "anthropic-proxy/openai-adapter"


class OpenAIApiChannel(Channel):
    """OpenAI 家族（chat / responses 上游）的 API 渠道。"""

    type = "api"
    cc_mimicry = False  # OpenAI 家族永远不走 Claude Code 伪装

    def __init__(self, entry: dict):
        self.name = entry["name"]
        self.key = f"api:{self.name}"
        self.display_name = self.name
        self.base_url = (entry.get("baseUrl") or "").rstrip("/")
        self.api_key = entry.get("apiKey", "")
        self.models: list[dict] = list(entry.get("models") or [])
        self.enabled = bool(entry.get("enabled", True))
        self.disabled_reason = entry.get("disabled_reason")
        self.protocol = entry.get("protocol", "openai-chat")
        if self.protocol not in ("openai-chat", "openai-responses"):
            raise ValueError(
                f"OpenAIApiChannel got invalid protocol: {self.protocol!r}"
            )

    def supports_model(self, requested_model: str) -> Optional[str]:
        for m in self.models:
            if m.get("alias") == requested_model:
                return m.get("real")
        return None

    def list_client_models(self) -> list[str]:
        return [m.get("alias", "") for m in self.models if m.get("alias")]

    async def build_upstream_request(
        self, requested_body: dict, resolved_model: str,
        *, ingress_protocol: str = "chat",
    ) -> UpstreamRequest:
        """按 (ingress_protocol, self.protocol) 分派。

        - `(chat, openai-chat)` / `(responses, openai-responses)` → 同协议透传
        - `(chat, openai-responses)` / `(responses, openai-chat)` → 跨变体（MS-3）
        - 其他组合：scheduler family 过滤应已拦住；这里做防御性 400
        """
        if ingress_protocol not in ("chat", "responses"):
            raise ValueError(
                f"OpenAIApiChannel got non-openai ingress_protocol={ingress_protocol!r}; "
                "scheduler should have filtered this at family level."
            )

        if ingress_protocol == "chat" and self.protocol == "openai-chat":
            return self._build_chat_passthrough(requested_body, resolved_model)
        if ingress_protocol == "responses" and self.protocol == "openai-responses":
            return self._build_responses_passthrough(requested_body, resolved_model)

        # 跨变体：暂不支持
        raise NotImplementedError(
            f"cross-variant translation ingress={ingress_protocol!r} → "
            f"upstream={self.protocol!r} is scheduled for MS-3 "
            "(see docs/openai/09-milestones.md)"
        )

    # ─── 同协议透传 ────────────────────────────────────────────

    def _build_chat_passthrough(self, body: dict, resolved_model: str) -> UpstreamRequest:
        payload = common.filter_chat_passthrough(body)
        payload["model"] = resolved_model
        return UpstreamRequest(
            url=f"{self.base_url}/v1/chat/completions",
            headers=self._headers(),
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            dynamic_tool_map=None,
        )

    def _build_responses_passthrough(self, body: dict, resolved_model: str) -> UpstreamRequest:
        payload = common.filter_responses_passthrough(body)
        payload["model"] = resolved_model
        return UpstreamRequest(
            url=f"{self.base_url}/v1/responses",
            headers=self._headers(),
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            dynamic_tool_map=None,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": _UA,
        }

    async def restore_response(self, chunk: bytes,
                               dynamic_map: Optional[dict] = None) -> bytes:
        # OpenAI 家族不做工具名还原，原样返回
        return chunk

    def display(self) -> ChannelDisplay:
        return ChannelDisplay(
            key=self.key,
            type="api",
            display_name=self.name,
            enabled=self.enabled,
            disabled_reason=self.disabled_reason,
            models=self.list_client_models(),
        )
