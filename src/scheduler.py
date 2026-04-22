"""主调度：筛选 → 亲和 → 评分排序。

返回一个按尝试顺序排好的候选列表 [(Channel, resolved_model), ...]。
调用方（failover）顺序尝试，直到成功发首包或全部失败。
"""

from __future__ import annotations

from typing import Optional

from . import affinity, concurrency, config, cooldown, fingerprint, scorer
from .channel import registry
from .channel.base import Channel


class ScheduleResult:
    """调度结果，包含候选序列与亲和相关元数据。"""

    def __init__(self, candidates: list[tuple[Channel, str]],
                 fp_query: Optional[str], affinity_hit: bool,
                 client_key: Optional[str] = None,
                 saturated: Optional[list[tuple[Channel, str]]] = None):
        self.candidates = candidates
        self.fp_query = fp_query         # 本次请求计算得到的查询指纹（可用于后续事件记录）
        self.affinity_hit = affinity_hit
        self.client_key = client_key     # client-level affinity key（failover 写入用）
        # 并发饱和（in_flight >= max）的候选：正常 candidates 全部失败后，
        # failover 会把 saturated 作为"可排队等位"的备选集。
        self.saturated: list[tuple[Channel, str]] = saturated or []

    def __bool__(self) -> bool:
        return bool(self.candidates) or bool(self.saturated)


# ─── 筛选 ─────────────────────────────────────────────────────────

def _family(proto: str) -> str:
    """协议到家族的映射。跨家族互转不做，scheduler 用这个过滤候选。"""
    return "anthropic" if proto == "anthropic" else "openai"


def _filter_candidates(requested_model: str,
                       ingress_protocol: str = "anthropic",
                       ) -> tuple[list[tuple[Channel, str]], list[tuple[Channel, str]]]:
    """返回 (available, saturated)：
       available = 可立即尝试的候选；
       saturated = 其它条件 OK 但当前并发满的候选（作为排队备选）。
    """
    ingress_family = _family(ingress_protocol)
    available: list[tuple[Channel, str]] = []
    saturated: list[tuple[Channel, str]] = []
    for ch in registry.all_channels():
        if not ch.enabled:
            continue
        if ch.disabled_reason:
            continue
        ch_protocol = getattr(ch, "protocol", "anthropic")
        if _family(ch_protocol) != ingress_family:
            continue
        resolved = ch.supports_model(requested_model)
        if resolved is None:
            continue
        if cooldown.is_blocked(ch.key, resolved):
            continue
        if concurrency.is_saturated(ch.key):
            saturated.append((ch, resolved))
            continue
        available.append((ch, resolved))
    return available, saturated


# ─── 亲和匹配 ─────────────────────────────────────────────────────

def _apply_affinity(candidates: list[tuple[Channel, str]],
                    fp_query: Optional[str],
                    cfg: dict,
                    client_key: Optional[str] = None,
                    ) -> tuple[list[tuple[Channel, str]], bool]:
    """尝试把亲和绑定的渠道顶到首位，必要时打破绑定。

    优先使用 fingerprint 亲和（精确会话级别）。
    若 fp_query 为 None 或未命中，回退到 client-level soft affinity。

    返回 (新 candidates, 是否亲和命中)。
    """
    if len(candidates) <= 1:
        return candidates, False

    # 1. 尝试 fingerprint 亲和
    bound = affinity.get(fp_query) if fp_query else None
    source = "fp"  # 记录命中来源

    # 2. 回退到 client-level soft affinity
    if not bound and client_key:
        bound = affinity.client_get(client_key)
        source = "client"

    if not bound:
        return candidates, False

    # 在当前候选列表中找到绑定目标
    bound_idx: Optional[int] = None
    for i, (ch, model) in enumerate(candidates):
        if ch.key == bound["channel_key"] and model == bound["model"]:
            bound_idx = i
            break

    if bound_idx is None:
        # 绑定目标当前不在候选（禁用/冷却/删除），保留绑定让下次恢复时命中
        return candidates, False

    # 打破检查：绑定 vs 最优 分数（最优 = 候选集中最低分）
    threshold = float(cfg.get("affinity", {}).get("threshold", 3.0))
    best_score = _best_score(candidates)
    bound_score = scorer.get_score(bound["channel_key"], bound["model"])

    # baseline 兜底：best_score=0 是边缘场景（默认分通常 3000，不会归零）；
    # 给 1.0 的下限避免乘 0 导致永远不打破。
    baseline = max(best_score, 1.0)
    if bound_score > baseline * threshold:
        if source == "fp" and fp_query:
            affinity.delete(fp_query)
        elif source == "client" and client_key:
            affinity.client_delete(client_key)
        return candidates, False

    # 命中：把绑定目标顶到首位
    if bound_idx != 0:
        candidates = list(candidates)
        candidates.insert(0, candidates.pop(bound_idx))
    if source == "fp" and fp_query:
        affinity.touch(fp_query)
    return candidates, True


def _best_score(candidates: list[tuple[Channel, str]]) -> float:
    """评分越低越好；返回候选集中最低分（最优）。"""
    scores = [scorer.get_score(ch.key, m) for ch, m in candidates]
    return min(scores) if scores else 0.0


# ─── 主入口 ───────────────────────────────────────────────────────

def schedule(body: dict, api_key_name: str, client_ip: str,
             ingress_protocol: str = "anthropic",
             fp_query: Optional[str] = None) -> ScheduleResult:
    """对下游请求做调度，返回候选尝试顺序。

    `ingress_protocol`（anthropic/chat/responses）决定筛候选时的家族过滤。
    `fp_query` 允许调用方提供已算好的亲和查询指纹；未提供时对 anthropic 入口
    按原逻辑用 messages 列表计算；其他入口本版本不算（MS-7 接入）。
    """
    requested_model = body.get("model")
    if not requested_model:
        return ScheduleResult([], None, False)

    candidates, saturated = _filter_candidates(requested_model, ingress_protocol)
    if not candidates and not saturated:
        return ScheduleResult([], None, False)

    if fp_query is None and ingress_protocol == "anthropic":
        fp_query = fingerprint.fingerprint_query(
            api_key_name, client_ip, body.get("messages") or []
        )

    # 构造 client-level affinity key
    client_key = affinity.make_client_key(api_key_name, client_ip, requested_model)

    cfg = config.get()
    mode = (cfg.get("channelSelection") or "smart").lower()

    if mode == "smart":
        candidates = scorer.sort_by_score(candidates)
        saturated = scorer.sort_by_score(saturated)
    # "order" 模式：按注册表原始顺序（config 中定义的顺序）

    candidates, affinity_hit = _apply_affinity(candidates, fp_query, cfg,
                                               client_key=client_key)

    return ScheduleResult(candidates, fp_query, affinity_hit,
                          client_key=client_key, saturated=saturated)
