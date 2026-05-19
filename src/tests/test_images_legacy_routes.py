"""Regression tests for OpenAI legacy Images API compatibility routes."""

from __future__ import annotations

import asyncio
import os as _ap_os
import sys as _ap_sys
from types import SimpleNamespace

# Keep imports isolated from any production config/state files.
_ap_sys.path.insert(0, _ap_os.path.dirname(_ap_os.path.dirname(_ap_os.path.dirname(_ap_os.path.abspath(__file__)))))
from src.tests import _isolation
_isolation.isolate()


def test_legacy_image_generation_routes_are_registered():
    import server

    routes = {
        route.path: route
        for route in server.app.routes
        if getattr(route, "path", None) in {"/v1/images/generations", "/images/generations"}
    }

    assert set(routes) == {"/v1/images/generations", "/images/generations"}
    for route in routes.values():
        assert "POST" in route.methods


def test_legacy_image_generation_routes_delegate_to_local_generate_handler(monkeypatch):
    import server
    from src.openai import images_simple

    seen = []
    sentinel = {"ok": True}

    async def fake_handle_generate(request):
        seen.append(request)
        return sentinel

    monkeypatch.setattr(images_simple, "handle_generate", fake_handle_generate)
    fake_request = SimpleNamespace(headers={}, json=lambda: {})

    assert asyncio.run(server.proxy_images_generations_legacy(fake_request)) is sentinel
    assert asyncio.run(server.proxy_images_generations_legacy_no_v1(fake_request)) is sentinel
    assert seen == [fake_request, fake_request]
