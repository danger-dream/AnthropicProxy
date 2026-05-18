"""Telegram update menu manual update smoke tests."""

from __future__ import annotations

import os as _ap_os, sys as _ap_sys
_ap_sys.path.insert(0, _ap_os.path.dirname(_ap_os.path.dirname(_ap_os.path.dirname(_ap_os.path.abspath(__file__)))))
from src.tests import _isolation
_isolation.isolate()

import os
import sys
import time


def _import_modules():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)
    from src import config, update_checker
    from src.telegram import ui
    from src.telegram.menus import update_menu
    return {
        "config": config,
        "update_checker": update_checker,
        "ui": ui,
        "update_menu": update_menu,
    }


class ApiRecorder:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, data=None):
        self.calls.append((method, dict(data) if data else {}))
        return {"ok": True, "result": {}}

    def by(self, method):
        return [d for m, d in self.calls if m == method]

    def last(self, method):
        calls = self.by(method)
        return calls[-1] if calls else None


def _install(m):
    rec = ApiRecorder()
    m["ui"].api = rec
    return rec


def _set_latest(m, version="v9.9.9"):
    m["update_checker"]._set_cache({
        "repo": "danger-dream/Parrot",
        "latest_version": version,
        "latest_name": "Test release",
        "latest_url": "https://example.test/release",
        "latest_body": "Changes",
        "latest_published_at": "2026-05-18T00:00:00Z",
        "latest_prerelease": False,
        "notified_for": None,
        "checked_at": 1,
    })


def test_manual_update_button_and_confirm_route(m):
    rec = _install(m)
    _set_latest(m)
    m["config"].update(lambda c: c.setdefault("updateChecker", {}).update({"ignoredVersions": []}))

    m["update_menu"].show(42, 100, "cb")
    edit = rec.last("editMessageText")
    buttons = [
        b["callback_data"]
        for row in edit["reply_markup"]["inline_keyboard"]
        for b in row
        if "callback_data" in b
    ]
    assert "upd:update_confirm" in buttons

    assert m["update_menu"].handle_callback(42, 100, "cb2", "upd:update_confirm") is True
    confirm = rec.last("editMessageText")
    assert "确认立即更新" in confirm["text"]
    assert "docker compose pull" in confirm["text"]
    confirm_buttons = [
        b["callback_data"]
        for row in confirm["reply_markup"]["inline_keyboard"]
        for b in row
        if "callback_data" in b
    ]
    assert "upd:update_run" in confirm_buttons

    m["config"].update(lambda c: c.setdefault("updateChecker", {}).update({"ignoredVersions": ["v9.9.9"]}))
    m["update_menu"].show(42, 100, "cb3")
    ignored_edit = rec.last("editMessageText")
    ignored_buttons = [
        b["callback_data"]
        for row in ignored_edit["reply_markup"]["inline_keyboard"]
        for b in row
        if "callback_data" in b
    ]
    assert "upd:update_confirm" not in ignored_buttons


def test_manual_update_concurrency_guard(m):
    uc = m["update_checker"]
    uc._set_manual_update_running(False)
    m["config"].update(lambda c: c.setdefault("updateChecker", {}).update({
        "updateCommand": "sleep 0.2",
        "workingDirectory": os.getcwd(),
    }))

    messages: list[str] = []
    started, msg = uc.start_manual_update(messages.append)
    assert started is True, msg
    started2, msg2 = uc.start_manual_update(messages.append)
    assert started2 is False
    assert "正在执行" in msg2

    deadline = time.time() + 2
    while uc.is_manual_update_running() and time.time() < deadline:
        time.sleep(0.02)
    assert uc.is_manual_update_running() is False
    assert any("执行完成" in s for s in messages)
