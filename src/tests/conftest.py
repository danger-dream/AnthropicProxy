from __future__ import annotations

import asyncio

import pytest

_ORIG_TO_THREAD = asyncio.to_thread


async def _test_inline_to_thread(func, /, *args, **kwargs):
    """测试环境里同步执行 to_thread 任务，避免解释器收尾卡在线程池关闭。"""
    return func(*args, **kwargs)


@pytest.fixture
def m(request):
    """返回测试模块的模块映射；具体状态初始化由测试显式调用。"""
    module = request.module
    importer = getattr(module, "_import_modules", None)
    if not callable(importer):
        raise RuntimeError(f"{module.__name__} is missing _import_modules()")
    return importer()


@pytest.fixture(autouse=True)
def _restore_telegram_ui_globals():
    """测试间恢复 telegram.ui 的猴补/全局状态，避免跨文件污染。"""
    try:
        from src.telegram import ui
    except Exception:
        ui = None

    if ui is None:
        yield
        return

    orig_api = ui.api
    orig_session = getattr(ui, "_session", None)
    orig_bot_token = getattr(ui, "_bot_token", "")
    orig_admin_ids = set(getattr(ui, "_admin_ids", set()))
    try:
        yield
    finally:
        try:
            ui.close_session()
        except Exception:
            pass
        ui.api = orig_api
        ui._session = orig_session
        ui._bot_token = orig_bot_token
        ui._admin_ids = set(orig_admin_ids)


def pytest_configure(config):
    """启用 async 测试自动模式，并规避 Python 3.13 默认线程池收尾卡死。"""
    config.option.asyncio_mode = "auto"
    asyncio.to_thread = _test_inline_to_thread


def pytest_unconfigure(config):
    asyncio.to_thread = _ORIG_TO_THREAD
