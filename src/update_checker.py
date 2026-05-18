"""GitHub Release 版本更新检查。

设计：
- 默认 1 小时拉一次 `https://api.github.com/repos/<repo>/releases`，
  按 `prerelease + draft` 标志过滤，挑最高 semver 当 latest。
- 与本地 `__version__` 比对：latest > local 才算"有新版"。
- 持久化：state.db 单行 `app_update_state` 记录最新一次结果；
  `notified_for` 字段记录"已经推过通知的版本号"，避免重复推。
- 忽略列表：`config.updateChecker.ignoredVersions`（TG 操作时写入），
  存在该版本时不 banner / 不推。
- 推送：notifier.notify_event("app_update", text)；走总通知开关。
- Banner：A 方案——只要 latest > local 且未被忽略，主菜单底部一直显示。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from typing import Callable, Optional

from packaging.version import InvalidVersion, Version

from . import __version__, config, network, notifier, state_db


# ─── 配置 ────────────────────────────────────────────────────────


def _cfg() -> dict:
    uc = config.get().get("updateChecker") or {}
    return {
        "enabled": bool(uc.get("enabled", True)),
        "intervalSeconds": int(uc.get("intervalSeconds", 3600) or 3600),
        "includePrerelease": bool(uc.get("includePrerelease", True)),
        "repo": str(uc.get("repo") or "danger-dream/Parrot").strip(),
        "ignoredVersions": list(uc.get("ignoredVersions") or []),
        "updateCommand": str(uc.get("updateCommand") or "docker compose pull && docker compose up -d").strip(),
        "workingDirectory": str(uc.get("workingDirectory") or "").strip(),
    }


def get_update_command_config() -> dict:
    """Return the command/cwd used by the Telegram manual update action."""
    cfg = _cfg()
    cwd = cfg["workingDirectory"] or os.getcwd()
    return {
        "command": cfg["updateCommand"],
        "workingDirectory": cwd,
    }


def _set_ignored(versions: list[str]) -> None:
    def _mut(c):
        c.setdefault("updateChecker", {})["ignoredVersions"] = list(versions)
    config.update(_mut)


def add_ignored(version: str) -> None:
    cfg = _cfg()
    s = set(cfg["ignoredVersions"])
    s.add(version)
    _set_ignored(sorted(s))


def remove_ignored(version: str) -> None:
    cfg = _cfg()
    s = set(cfg["ignoredVersions"])
    s.discard(version)
    _set_ignored(sorted(s))


def clear_ignored() -> None:
    _set_ignored([])


# ─── state.db schema ─────────────────────────────────────────────


def _ensure_schema() -> None:
    sql = """
    CREATE TABLE IF NOT EXISTS app_update_state (
      repo                 TEXT PRIMARY KEY,
      latest_version       TEXT,
      latest_name          TEXT,
      latest_url           TEXT,
      latest_body          TEXT,
      latest_published_at  TEXT,
      latest_prerelease    INTEGER DEFAULT 0,
      notified_for         TEXT,
      checked_at           INTEGER
    );
    """
    conn = state_db._get_conn()
    with state_db._write_lock:
        conn.executescript(sql)
        conn.commit()


def _load_state(repo: str) -> Optional[dict]:
    conn = state_db._get_conn()
    row = conn.execute(
        "SELECT repo, latest_version, latest_name, latest_url, latest_body, "
        "latest_published_at, latest_prerelease, notified_for, checked_at "
        "FROM app_update_state WHERE repo=?",
        (repo,),
    ).fetchone()
    if not row:
        return None
    return {
        "repo": row[0],
        "latest_version": row[1],
        "latest_name": row[2],
        "latest_url": row[3],
        "latest_body": row[4],
        "latest_published_at": row[5],
        "latest_prerelease": bool(row[6]),
        "notified_for": row[7],
        "checked_at": row[8],
    }


def _save_state(repo: str, *, latest_version: Optional[str], latest_name: Optional[str],
                latest_url: Optional[str], latest_body: Optional[str],
                latest_published_at: Optional[str], latest_prerelease: bool,
                notified_for: Optional[str]) -> None:
    conn = state_db._get_conn()
    with state_db._write_lock:
        conn.execute(
            "INSERT OR REPLACE INTO app_update_state(repo, latest_version, latest_name, "
            "latest_url, latest_body, latest_published_at, latest_prerelease, "
            "notified_for, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (repo, latest_version, latest_name, latest_url, latest_body,
             latest_published_at, 1 if latest_prerelease else 0,
             notified_for, int(time.time())),
        )
        conn.commit()


# ─── 内存缓存（供 banner / 菜单读）────────────────────────────────

_state_lock = threading.Lock()
_latest_cache: Optional[dict] = None


def _set_cache(state: Optional[dict]) -> None:
    global _latest_cache
    with _state_lock:
        _latest_cache = state


def get_cached() -> Optional[dict]:
    with _state_lock:
        return dict(_latest_cache) if _latest_cache else None


# ─── version 比较 ────────────────────────────────────────────────


def _strip_v(tag: str) -> str:
    return tag.lstrip("vV").strip()


def _parse(tag: str) -> Optional[Version]:
    try:
        return Version(_strip_v(tag))
    except InvalidVersion:
        return None


def _has_newer(latest_tag: Optional[str]) -> bool:
    if not latest_tag:
        return False
    cur = _parse(__version__)
    lat = _parse(latest_tag)
    if cur is None or lat is None:
        # 解析失败 → 仅在字符串不同且 latest 不为空时算"有新版"
        return latest_tag.lstrip("vV") != __version__.lstrip("vV")
    return lat > cur


# ─── banner 生成 ─────────────────────────────────────────────────


def get_update_banner() -> Optional[str]:
    """主菜单底部 banner：仅在 latest>local 且未被忽略时返回字符串，否则 None。"""
    st = get_cached()
    if not st:
        return None
    latest = st.get("latest_version")
    if not latest or not _has_newer(latest):
        return None
    ignored = set(_cfg().get("ignoredVersions") or [])
    if latest in ignored:
        return None
    return (
        f"🆕 <b>Parrot 新版本可用</b>: <code>v{__version__}</code> → "
        f"<code>{notifier.escape_html(latest)}</code> — "
        "进入「⚙ 系统设置 → 🆕 版本更新」查看详情"
    )


# ─── 手动升级执行器 ───────────────────────────────────────────────

_manual_update_lock = threading.Lock()
_manual_update_running = False


def is_manual_update_running() -> bool:
    with _manual_update_lock:
        return _manual_update_running


def _set_manual_update_running(value: bool) -> None:
    global _manual_update_running
    with _manual_update_lock:
        _manual_update_running = value


def _clip_output(text: str, limit: int = 2600) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[-limit:].lstrip() + "\n…（仅显示最后部分日志）"


def _format_manual_update_result(returncode: int, output: str) -> str:
    clipped = _clip_output(output)
    if returncode == 0:
        head = "✅ <b>Parrot 更新命令执行完成</b>"
    else:
        head = f"❌ <b>Parrot 更新命令失败</b>（退出码 <code>{returncode}</code>）"
    if not clipped:
        return head
    return f"{head}\n\n<pre>{notifier.escape_html(clipped)}</pre>"


def _run_manual_update(command: str, cwd: str, notify: Callable[[str], None]) -> None:
    try:
        notify(
            "⬆️ <b>开始执行 Parrot 更新命令</b>\n\n"
            f"目录: <code>{notifier.escape_html(cwd)}</code>\n"
            f"命令: <code>{notifier.escape_html(command)}</code>"
        )
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=900,
        )
        notify(_format_manual_update_result(proc.returncode, proc.stdout or ""))
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        notify(
            "❌ <b>Parrot 更新命令超时</b>（900s）\n\n"
            f"<pre>{notifier.escape_html(_clip_output(output))}</pre>"
        )
    except Exception as exc:
        notify(f"❌ <b>Parrot 更新命令启动失败</b>: <code>{notifier.escape_html(str(exc))}</code>")
    finally:
        _set_manual_update_running(False)


def start_manual_update(notify: Callable[[str], None]) -> tuple[bool, str]:
    """Start the configured update command in a background thread.

    Returns (started, message). The caller is responsible for checking that a
    non-ignored newer release exists before invoking this function.
    """
    with _manual_update_lock:
        global _manual_update_running
        if _manual_update_running:
            return False, "已有更新任务正在执行"
        _manual_update_running = True

    cmd_cfg = get_update_command_config()
    command = cmd_cfg["command"]
    cwd = cmd_cfg["workingDirectory"]
    if not command:
        _set_manual_update_running(False)
        return False, "未配置 updateChecker.updateCommand"
    if not os.path.isdir(cwd):
        _set_manual_update_running(False)
        return False, f"工作目录不存在: {cwd}"

    t = threading.Thread(
        target=_run_manual_update,
        args=(command, cwd, notify),
        name="parrot-manual-update",
        daemon=True,
    )
    t.start()
    return True, "更新任务已在后台启动"


# ─── HTTP 抓取 ───────────────────────────────────────────────────


def _http_get_json(url: str, timeout: int = 15):
    try:
        resp = network.get_sync(url, timeout=timeout, headers={
            "User-Agent": "parrot-update-checker/0.1",
            "Accept": "application/vnd.github+json",
        })
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[update_checker] fetch failed: {url} -> {exc}")
        return None


def _pick_latest(releases: list, *, include_prerelease: bool) -> Optional[dict]:
    """从 releases 列表里挑出 semver 最高的，过滤 draft 与（按需）prerelease。"""
    candidates: list[tuple[Version, dict]] = []
    fallback: Optional[dict] = None
    for r in releases or []:
        if r.get("draft"):
            continue
        if r.get("prerelease") and not include_prerelease:
            continue
        tag = r.get("tag_name") or ""
        ver = _parse(tag)
        if ver is None:
            fallback = fallback or r
            continue
        candidates.append((ver, r))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return fallback


def _check_once(*, push: bool = True) -> None:
    """单次检查并视情况推送 + 写状态。"""
    cfg = _cfg()
    if not cfg["enabled"] or not cfg["repo"]:
        return
    url = f"https://api.github.com/repos/{cfg['repo']}/releases?per_page=20"
    releases = _http_get_json(url)
    if releases is None:
        return
    if not isinstance(releases, list):
        return
    latest = _pick_latest(releases, include_prerelease=cfg["includePrerelease"])
    if not latest:
        # 没有任何符合条件的 release：清掉缓存即可
        _save_state(
            cfg["repo"],
            latest_version=None, latest_name=None, latest_url=None,
            latest_body=None, latest_published_at=None, latest_prerelease=False,
            notified_for=(_load_state(cfg["repo"]) or {}).get("notified_for"),
        )
        _set_cache(_load_state(cfg["repo"]))
        return

    tag = latest.get("tag_name") or ""
    prev = _load_state(cfg["repo"]) or {}
    notified_for = prev.get("notified_for")

    is_newer = _has_newer(tag)
    ignored = set(cfg["ignoredVersions"])
    should_push = (
        push
        and is_newer
        and tag not in ignored
        and tag != notified_for      # 同一版本不重复推
    )

    if should_push:
        try:
            notifier.notify_event("app_update", _format_release(tag, latest))
            notified_for = tag
        except Exception as exc:
            print(f"[update_checker] notify failed: {exc}")

    _save_state(
        cfg["repo"],
        latest_version=tag,
        latest_name=latest.get("name"),
        latest_url=latest.get("html_url"),
        latest_body=latest.get("body"),
        latest_published_at=latest.get("published_at"),
        latest_prerelease=bool(latest.get("prerelease")),
        notified_for=notified_for,
    )
    _set_cache(_load_state(cfg["repo"]))


def _format_release(tag: str, release: dict) -> str:
    name = (release.get("name") or "").strip()
    body = (release.get("body") or "").strip()
    if len(body) > 600:
        body = body[:600].rstrip() + "…"
    url = release.get("html_url") or ""
    published = release.get("published_at") or ""
    pre = " (pre-release)" if release.get("prerelease") else ""
    head = f"🆕 <b>Parrot 新版本可用{notifier.escape_html(pre)}</b>\n"
    head += f"当前: <code>v{__version__}</code> → 最新: <code>{notifier.escape_html(tag)}</code>\n"
    if name:
        head += f"标题: {notifier.escape_html(name)}\n"
    if published:
        head += f"发布: <code>{notifier.escape_html(published)}</code>\n"
    if body:
        head += f"\n{notifier.escape_html(body)}\n"
    if url:
        head += f"\n🔗 {notifier.escape_html(url)}"
    return head


# ─── 外部入口 ────────────────────────────────────────────────────


def force_refresh_sync() -> None:
    """供 TG「立即检查」按钮调用，同步阻塞拉一次。"""
    try:
        _ensure_schema()
    except Exception:
        pass
    _check_once(push=True)


async def update_loop() -> None:
    try:
        _ensure_schema()
        # 启动时把上次的状态恢复到内存
        cfg = _cfg()
        st = _load_state(cfg["repo"]) if cfg["repo"] else None
        if st:
            _set_cache(st)
    except Exception as exc:
        print(f"[update_checker] init failed: {exc}")

    # 首次延迟 30s，避免和其他 startup 抢
    await asyncio.sleep(30)
    while True:
        try:
            cfg = _cfg()
            if not cfg["enabled"]:
                await asyncio.sleep(max(300, cfg["intervalSeconds"]))
                continue
            await asyncio.to_thread(_check_once, push=True)
            await asyncio.sleep(max(300, cfg["intervalSeconds"]))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[update_checker] loop iteration failed: {exc}")
            await asyncio.sleep(60)
