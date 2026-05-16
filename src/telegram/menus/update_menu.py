"""🆕 版本更新菜单。

入口：「⚙ 系统设置 → 🆕 版本更新」
功能：
- 显示当前版本 / 最新版本 / 发布时间 / changelog 摘要
- 立即检查（同步阻塞拉一次）
- 忽略此版本（加入 ignoredVersions）/ 清空忽略列表
- 设置：总开关 / 间隔 / 是否含 prerelease
"""

from __future__ import annotations

from typing import Optional

from ... import __version__, config, update_checker
from .. import states, ui


def _cfg() -> dict:
    return config.get().get("updateChecker") or {}


def _update_cfg(patch: dict) -> None:
    def _mut(c):
        c.setdefault("updateChecker", {}).update(patch)
    config.update(_mut)


def _format_main_text() -> str:
    cfg = _cfg()
    enabled = bool(cfg.get("enabled", True))
    interval = int(cfg.get("intervalSeconds", 3600) or 3600)
    include_pre = bool(cfg.get("includePrerelease", True))
    repo = cfg.get("repo") or "danger-dream/Parrot"
    ignored = list(cfg.get("ignoredVersions") or [])

    st = update_checker.get_cached() or {}
    latest = st.get("latest_version")
    latest_name = st.get("latest_name") or ""
    latest_pub = st.get("latest_published_at") or ""
    latest_pre = bool(st.get("latest_prerelease"))
    latest_url = st.get("latest_url") or ""
    latest_body = (st.get("latest_body") or "").strip()
    if len(latest_body) > 800:
        latest_body = latest_body[:800].rstrip() + "…"

    lines = [
        "🆕 <b>版本更新</b>",
        "",
        f"当前版本: <code>v{__version__}</code>",
        f"仓库: <code>{ui.escape_html(repo)}</code>",
        f"自动检查: <code>{'开' if enabled else '关'}</code> · 间隔 <code>{interval}s</code> · "
        f"含预发布: <code>{'是' if include_pre else '否'}</code>",
        f"已忽略: <code>{', '.join(ignored) if ignored else '无'}</code>",
        "",
    ]

    if not latest:
        lines.append("ℹ 暂无 release 数据；点「🔄 立即检查」拉取。")
    else:
        is_newer = update_checker._has_newer(latest)
        head = "🟢 有新版本" if is_newer and latest not in set(ignored) else (
               "🔕 新版本已忽略" if is_newer else "✅ 已是最新")
        lines.append(f"<b>最新 release</b>: <code>{ui.escape_html(latest)}</code>"
                     f"{' (pre-release)' if latest_pre else ''} — {head}")
        if latest_name:
            lines.append(f"标题: {ui.escape_html(latest_name)}")
        if latest_pub:
            lines.append(f"发布: <code>{ui.escape_html(latest_pub)}</code>")
        if latest_body:
            lines.append("")
            lines.append("<b>Changelog:</b>")
            lines.append(ui.escape_html(latest_body))
        if latest_url:
            lines.append("")
            lines.append(f"🔗 <code>{ui.escape_html(latest_url)}</code>")

    return "\n".join(lines)


def _format_kb() -> dict:
    cfg = _cfg()
    enabled = bool(cfg.get("enabled", True))
    include_pre = bool(cfg.get("includePrerelease", True))
    interval = int(cfg.get("intervalSeconds", 3600) or 3600)
    ignored = set(cfg.get("ignoredVersions") or [])
    st = update_checker.get_cached() or {}
    latest = st.get("latest_version")

    rows: list[list[dict]] = []
    rows.append([
        ui.btn(f"{'🟢 自动检查: 开' if enabled else '🔴 自动检查: 关'}", "upd:toggle_enabled"),
        ui.btn(f"{'🧪 含预发布' if include_pre else '🚫 不含预发布'}", "upd:toggle_pre"),
    ])
    rows.append([
        ui.btn(f"⏱ 间隔: {interval}s", "upd:edit_interval"),
        ui.btn("🔄 立即检查", "upd:refresh"),
    ])
    if latest and update_checker._has_newer(latest):
        if latest in ignored:
            rows.append([ui.btn(f"✅ 取消忽略 {latest}", f"upd:unignore:{latest}")])
        else:
            rows.append([ui.btn(f"🔕 忽略 {latest}", f"upd:ignore:{latest}")])
    if ignored:
        rows.append([ui.btn(f"🧹 清空忽略列表（{len(ignored)}）", "upd:clear_ignored")])
    rows.append([ui.btn("◀ 返回设置", "menu:settings"), ui.btn("🏠 主菜单", "menu:main")])
    return ui.inline_kb(rows)


def show(chat_id: int, message_id: int, cb_id: Optional[str] = None) -> None:
    if cb_id is not None:
        ui.answer_cb(cb_id)
    ui.edit(chat_id, message_id, ui.truncate(_format_main_text()), reply_markup=_format_kb())


def send_new(chat_id: int) -> None:
    ui.send(chat_id, ui.truncate(_format_main_text()), reply_markup=_format_kb())


# ─── 操作 ────────────────────────────────────────────────────────


def _toggle_enabled(chat_id: int, message_id: int, cb_id: str) -> None:
    cur = bool(_cfg().get("enabled", True))
    _update_cfg({"enabled": not cur})
    ui.answer_cb(cb_id, "已关闭" if cur else "已开启")
    show(chat_id, message_id)


def _toggle_pre(chat_id: int, message_id: int, cb_id: str) -> None:
    cur = bool(_cfg().get("includePrerelease", True))
    _update_cfg({"includePrerelease": not cur})
    ui.answer_cb(cb_id, "已切换")
    show(chat_id, message_id)


def _edit_interval(chat_id: int, message_id: int, cb_id: str) -> None:
    ui.answer_cb(cb_id)
    states.set_state(chat_id, "upd_interval")
    ui.edit(
        chat_id, message_id,
        "请输入检查间隔（秒，≥300=5 分钟，推荐 3600=1 小时）：\n\n例：<code>3600</code>",
        reply_markup=ui.inline_kb([[ui.btn("❌ 取消", "menu:update")]]),
    )


def _on_interval_input(chat_id: int, text: str) -> None:
    try:
        v = int((text or "").strip())
        if v < 300:
            raise ValueError
    except ValueError:
        ui.send(chat_id, "❌ 需要 ≥300 的整数（最小 5 分钟），请重新输入：")
        return
    _update_cfg({"intervalSeconds": v})
    states.pop_state(chat_id)
    ui.send(chat_id, f"✅ 检查间隔已更新为 <code>{v}s</code>")
    send_new(chat_id)


def _refresh(chat_id: int, message_id: int, cb_id: str) -> None:
    ui.answer_cb(cb_id, "拉取中…")
    try:
        update_checker.force_refresh_sync()
    except Exception as exc:
        ui.send(chat_id, f"❌ 拉取失败: <code>{ui.escape_html(str(exc))}</code>")
        return
    show(chat_id, message_id)


def _ignore_version(chat_id: int, message_id: int, cb_id: str, version: str) -> None:
    if not version:
        ui.answer_cb(cb_id, "版本号为空")
        return
    update_checker.add_ignored(version)
    ui.answer_cb(cb_id, f"已忽略 {version}")
    show(chat_id, message_id)


def _unignore_version(chat_id: int, message_id: int, cb_id: str, version: str) -> None:
    if not version:
        ui.answer_cb(cb_id, "版本号为空")
        return
    update_checker.remove_ignored(version)
    ui.answer_cb(cb_id, f"已取消忽略 {version}")
    show(chat_id, message_id)


def _clear_ignored(chat_id: int, message_id: int, cb_id: str) -> None:
    update_checker.clear_ignored()
    ui.answer_cb(cb_id, "已清空")
    show(chat_id, message_id)


# ─── 路由 ─────────────────────────────────────────────────────


def handle_callback(chat_id: int, message_id: int, cb_id: str, data: str) -> bool:
    if data == "menu:update":
        show(chat_id, message_id, cb_id); return True
    if data == "upd:toggle_enabled":
        _toggle_enabled(chat_id, message_id, cb_id); return True
    if data == "upd:toggle_pre":
        _toggle_pre(chat_id, message_id, cb_id); return True
    if data == "upd:edit_interval":
        _edit_interval(chat_id, message_id, cb_id); return True
    if data == "upd:refresh":
        _refresh(chat_id, message_id, cb_id); return True
    if data.startswith("upd:ignore:"):
        _ignore_version(chat_id, message_id, cb_id, data.split(":", 2)[2]); return True
    if data.startswith("upd:unignore:"):
        _unignore_version(chat_id, message_id, cb_id, data.split(":", 2)[2]); return True
    if data == "upd:clear_ignored":
        _clear_ignored(chat_id, message_id, cb_id); return True
    return False


def handle_text_state(chat_id: int, action: str, text: str) -> bool:
    if action == "upd_interval":
        _on_interval_input(chat_id, text); return True
    return False
