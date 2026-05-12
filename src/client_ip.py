"""客户端真实 IP 提取工具。

优先读取常见 CDN / 反代请求头；都没有时回退到 socket peer IP。
用于日志、亲和 fingerprint、client-level soft affinity。
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Optional


# 单值头：按可信优先级排列。
_SINGLE_IP_HEADERS = (
    "cf-connecting-ip",        # Cloudflare
    "true-client-ip",          # Cloudflare Enterprise / Akamai
    "fastly-client-ip",        # Fastly
    "x-real-ip",               # Nginx / OpenResty
    "x-client-ip",
    "x-cluster-client-ip",
    "x-forwarded",             # Some proxies use a single IP here
    "x-appengine-user-ip",     # Google App Engine
    "x-envoy-external-address",# Envoy
    "fly-client-ip",           # Fly.io
    "x-vercel-forwarded-for",  # Vercel often single-valued
    "x-nf-client-connection-ip",# Netlify
    "ali-cdn-real-ip",         # Alibaba CDN
    "cdn-src-ip",              # Some domestic CDNs
    "x-bd-client-ip",          # Baidu-style deployments
)

# 列表头：取第一个合法 IP（通常为最原始客户端）。
_LIST_IP_HEADERS = (
    "x-forwarded-for",
    "x-original-forwarded-for",
    "forwarded",               # RFC 7239: for=...
)


def _header_get(headers: Any, name: str) -> Optional[str]:
    if not headers:
        return None
    try:
        val = headers.get(name)
        if val:
            return str(val)
    except Exception:
        pass
    # 兜底兼容普通 dict / 测试 fake headers
    try:
        lname = name.lower()
        for k, v in headers.items():
            if str(k).lower() == lname and v:
                return str(v)
    except Exception:
        pass
    return None


def _strip_port_and_brackets(token: str) -> str:
    token = token.strip().strip('"').strip("'")
    if not token or token.lower() == "unknown":
        return ""

    # RFC 7239: for="[2001:db8::1]:1234"
    if token.startswith("["):
        end = token.find("]")
        if end > 0:
            return token[1:end].strip()

    # IPv4:port
    if token.count(":") == 1:
        host, port = token.rsplit(":", 1)
        if port.isdigit():
            return host.strip()

    # 裸 IPv6 不处理端口（多冒号）。
    return token


def _valid_ip(token: str) -> Optional[str]:
    host = _strip_port_and_brackets(token)
    if not host:
        return None
    # Forwarded 可能有 obfuscated identifier：for=_hidden
    if host.startswith("_"):
        return None
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _first_ip_from_csv(value: str) -> Optional[str]:
    for part in value.split(","):
        ip = _valid_ip(part)
        if ip:
            return ip
    return None


def _first_ip_from_forwarded(value: str) -> Optional[str]:
    # Forwarded: for=203.0.113.43, for="[2001:db8:cafe::17]:4711";proto=https
    for match in re.finditer(r"(?i)(?:^|[;,\s])for=([^;,\s]+|\"[^\"]+\")", value):
        raw = match.group(1).strip()
        ip = _valid_ip(raw)
        if ip:
            return ip
    return None


def get_client_ip(request: Any, default: str = "?") -> str:
    """从 Request 中提取真实客户端 IP。

    优先级：Cloudflare/常见 CDN 单值头 → X-Forwarded-For 等列表头 →
    RFC 7239 Forwarded → request.client.host。
    """
    headers = getattr(request, "headers", None)

    for name in _SINGLE_IP_HEADERS:
        val = _header_get(headers, name)
        if not val:
            continue
        ip = _first_ip_from_csv(val)
        if ip:
            return ip

    for name in _LIST_IP_HEADERS:
        val = _header_get(headers, name)
        if not val:
            continue
        if name == "forwarded":
            ip = _first_ip_from_forwarded(val)
        else:
            ip = _first_ip_from_csv(val)
        if ip:
            return ip

    try:
        host = getattr(getattr(request, "client", None), "host", None)
        ip = _valid_ip(str(host)) if host else None
        return ip or (str(host) if host else default)
    except Exception:
        return default
