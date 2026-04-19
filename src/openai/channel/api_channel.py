"""OpenAI 家族 API 渠道。

由 `src/channel/registry.py` 的 factory 分派触发：config 中 protocol 为
`openai-chat` 或 `openai-responses` 的 channel entry 会实例化本类。

MS-1 只提供骨架：能被实例化、能加入 registry、能参与 `/v1/models` 列表。
真正的 `build_upstream_request` / `restore_response` 在 MS-2 起逐步补齐。
"""

from __future__ import annotations

from typing import Optional

from ...channel.base import Channel, ChannelDisplay, UpstreamRequest


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
        # MS-2 起实现：按 (ingress_protocol, self.protocol) 选择透传或跨变体翻译。
        raise NotImplementedError(
            "OpenAIApiChannel.build_upstream_request is not yet implemented "
            "(scheduled for MS-2 in docs/openai/09-milestones.md)"
        )

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
