"""渠道并发限制 + FIFO 排队。

每个渠道一个"在途计数器 (in_flight)"，上限由 Channel.max_concurrent 决定
（0 = 不限）。满了时候调用方可以走 `acquire_from_candidates(...)` 在一组
候选渠道上排队等任一位置空出，超时返回 None。

设计要点：
  - 单进程 async：用 asyncio.Lock + 手写 FIFO waiter 列表
  - 每个渠道一份 `ChannelSlot`，按需懒构造
  - max 值动态从 registry 读（config 热加载可能改）；in_flight 不随 reload 重置
  - acquire/release 必须配对，`try/finally` 保证 release 被调用
  - 非持久化：重启清零（"在途"概念本身重启就没了）
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from . import config


@dataclass
class ChannelSlot:
    """单渠道的并发槽位。"""

    key: str
    max_concurrent: int
    in_flight: int = 0
    # FIFO waiter 队列：每个 waiter 是一个 asyncio.Future。
    # 释放时只唤醒队头；唤醒方设置 future.set_result(None)，等待方被唤醒后
    # 用原子路径 (set_result 前 slot.in_flight += 1) 拿到位置。
    waiters: list[asyncio.Future] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def is_unlimited(self) -> bool:
        return self.max_concurrent <= 0

    def is_saturated(self) -> bool:
        if self.is_unlimited():
            return False
        return self.in_flight >= self.max_concurrent


# 全局 slot 表。key = channel.key（"api:xxx" 或 "oauth:provider:email"）。
_slots: dict[str, ChannelSlot] = {}
_slots_lock = asyncio.Lock()

# 全局"释放事件"：任一渠道 release 时 set 一次，用来唤醒"跨候选"排队方
# （acquire_from_candidates 会注册到多个 slot 的 waiter 队列里，任一 slot 释放都要醒）。
# 严格 FIFO 通过 waiter 队列保证，_release_event 只是兜底 / 轮询唤醒源。
_release_event: asyncio.Event = asyncio.Event()


def _get_channel_max(ch_key: str) -> int:
    """从 registry 查当前渠道的 max_concurrent。缺失/未知渠道返回 defaultMaxConcurrent。"""
    from .channel import registry  # 延迟 import 避免循环

    cfg = config.get()
    cc_cfg = cfg.get("concurrency") or {}
    default_max = int(cc_cfg.get("defaultMaxConcurrent", 0))
    ch = registry.get_channel(ch_key)
    if ch is None:
        return default_max
    mc = getattr(ch, "max_concurrent", 0)
    try:
        mc = int(mc or 0)
    except Exception:
        mc = 0
    # 0 / 负数 → 用全局默认（仍为 0 则不限）
    return mc if mc > 0 else default_max


async def _get_or_create_slot(ch_key: str) -> ChannelSlot:
    async with _slots_lock:
        slot = _slots.get(ch_key)
        if slot is None:
            slot = ChannelSlot(key=ch_key, max_concurrent=_get_channel_max(ch_key))
            _slots[ch_key] = slot
        else:
            # 热加载可能改了 max_concurrent；只更新 max，不动 in_flight
            slot.max_concurrent = _get_channel_max(ch_key)
        return slot


def _enabled() -> bool:
    cfg = config.get()
    cc_cfg = cfg.get("concurrency") or {}
    return bool(cc_cfg.get("enabled", True))


async def try_acquire(ch_key: str) -> bool:
    """非阻塞尝试占一个位置。成功 in_flight+=1，返回 True；满了返回 False。

    禁用并发限制或渠道不限（max=0）时永远返回 True。
    """
    if not _enabled():
        return True
    slot = await _get_or_create_slot(ch_key)
    if slot.is_unlimited():
        slot.in_flight += 1
        return True
    async with slot.lock:
        if slot.in_flight < slot.max_concurrent:
            slot.in_flight += 1
            return True
    return False


def release(ch_key: str) -> None:
    """释放一个位置，唤醒该 slot 的 FIFO 队头（若有）。

    同步函数，可在 try/finally 里直接调用。
    """
    slot = _slots.get(ch_key)
    if slot is None:
        return
    if slot.is_unlimited():
        # 不限制的渠道仅做 in_flight 计数回减，无需唤醒
        if slot.in_flight > 0:
            slot.in_flight -= 1
        return
    if slot.in_flight > 0:
        slot.in_flight -= 1
    # 唤醒队头 waiter（只唤醒一个；FIFO 语义）
    # 注意：即使没 waiter，也要 set 一次 _release_event，唤醒 acquire_from_candidates
    # 里跨 slot 轮询的等待方。
    while slot.waiters:
        fut = slot.waiters.pop(0)
        if not fut.done():
            fut.set_result(None)
            break
        # done 的是被别处取消 / 已超时的，继续找下一个
    try:
        _release_event.set()
    except Exception:
        pass


async def acquire_from_candidates(
    candidates: list[tuple[str, object]],  # [(ch_key, resolved_model_or_whatever)]
    timeout_seconds: float,
) -> Optional[tuple[str, object]]:
    """在一组候选渠道上排队等位。

    行为：
      1. 先挨个 try_acquire；命中则返回 (ch_key, payload)。
      2. 全满 → 在**每个**候选 slot 末尾注册一个 waiter future；
         同时 asyncio.wait 各 future + 全局 _release_event + timeout。
      3. 任一 future 就绪（被 release 精确唤醒）→ 对应候选 try_acquire
         抢不到就循环回 step 2（避免被别的 ch_key 抢走）。
      4. 全局 _release_event 唤醒只表示"可能"有位置，轮询所有候选再 try。
      5. 超过 timeout → 返回 None。

    candidates 保持原顺序 → 优先级语义和调度器的排序一致。
    超时返回 None 后上层应给客户端 429。
    """
    if not candidates:
        return None
    # step 1: 快速路径
    for ch_key, payload in candidates:
        if await try_acquire(ch_key):
            return (ch_key, payload)

    deadline = time.monotonic() + max(0.0, timeout_seconds)

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None

        # step 2: 为每个 slot 注册 waiter
        futures: list[tuple[ChannelSlot, asyncio.Future]] = []
        for ch_key, _ in candidates:
            slot = await _get_or_create_slot(ch_key)
            if slot.is_unlimited():
                # 不限制的渠道几乎不会到这里（前面 try_acquire 已成），
                # 兜底再试一次
                if await try_acquire(ch_key):
                    for s, fut in futures:
                        _drop_waiter(s, fut)
                    for _, payload in candidates:
                        if _ == ch_key:
                            return (ch_key, payload)
                    return (ch_key, candidates[0][1])
                continue
            fut: asyncio.Future = asyncio.get_event_loop().create_future()
            slot.waiters.append(fut)
            futures.append((slot, fut))

        # 同时等 _release_event 作为兜底唤醒源（覆盖 slot 被重建等极端情况）
        _release_event.clear()
        global_wake = asyncio.create_task(_release_event.wait())
        wait_futs = [fut for _, fut in futures] + [global_wake]

        try:
            done, _pending = await asyncio.wait(
                wait_futs,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            # 不管怎么样都要把自己从所有 slot 的 waiter 队列里摘掉，避免泄漏
            for slot, fut in futures:
                _drop_waiter(slot, fut)
            if not global_wake.done():
                global_wake.cancel()

        if not done:
            # 超时
            return None

        # step 3: 被唤醒，挨个候选再试一次
        # （优先按原顺序 try_acquire，保证候选优先级语义）
        for ch_key, payload in candidates:
            if await try_acquire(ch_key):
                return (ch_key, payload)
        # 没抢到 → 回 step 2 继续等


def _drop_waiter(slot: ChannelSlot, fut: asyncio.Future) -> None:
    try:
        slot.waiters.remove(fut)
    except ValueError:
        pass
    if not fut.done():
        try:
            fut.cancel()
        except Exception:
            pass


def is_saturated(ch_key: str) -> bool:
    """同步查询是否饱和（用于 scheduler filter 的快速路径）。"""
    if not _enabled():
        return False
    slot = _slots.get(ch_key)
    if slot is None:
        # 未构造过 → 必然空闲（除非 max=0 也算空闲）
        return False
    slot.max_concurrent = _get_channel_max(ch_key)
    return slot.is_saturated()


def snapshot() -> list[dict]:
    """供 TG Bot 展示：[{ch_key, in_flight, max, waiting}]。"""
    out = []
    for key, slot in _slots.items():
        slot.max_concurrent = _get_channel_max(key)
        out.append({
            "channel_key": key,
            "in_flight": slot.in_flight,
            "max_concurrent": slot.max_concurrent,
            "waiting": len(slot.waiters),
            "unlimited": slot.is_unlimited(),
        })
    out.sort(key=lambda x: x["channel_key"])
    return out


def totals() -> dict:
    """汇总：{in_flight, waiting, tracked_channels}。"""
    in_flight = sum(s.in_flight for s in _slots.values())
    waiting = sum(len(s.waiters) for s in _slots.values())
    return {
        "in_flight": in_flight,
        "waiting": waiting,
        "tracked_channels": len(_slots),
    }


def forget_channel(ch_key: str) -> None:
    """渠道删除 / 改名时清理。必须确保 in_flight=0、waiters 空，否则忽略。"""
    slot = _slots.get(ch_key)
    if slot is None:
        return
    if slot.in_flight > 0 or slot.waiters:
        # 还有在途请求或排队方 → 不清，等它们自行完成
        return
    _slots.pop(ch_key, None)


def rename_channel(old_key: str, new_key: str) -> None:
    """渠道改名：把 slot 搬到新 key 下（保留 in_flight / waiters）。"""
    if old_key == new_key:
        return
    slot = _slots.pop(old_key, None)
    if slot is None:
        return
    slot.key = new_key
    slot.max_concurrent = _get_channel_max(new_key)
    _slots[new_key] = slot
