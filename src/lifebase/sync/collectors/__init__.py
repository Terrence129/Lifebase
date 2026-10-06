"""Collector 注册表：source_type → collector 类，供 pipeline / CLI / rebuild 复用。

新 collector 在此登记。约定：
- 构造签名统一为 `(source_id, ingested_at=None)`；
- `metadata()["source_type"]` 必须等于 `collector_version` 的 `@` 前缀
  （如 `chatgpt@0.1.0` → `chatgpt`），注册表据此路由来源。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from lifebase.sync.base import Collector
from lifebase.sync.collectors.chatgpt import ChatGPTCollector
from lifebase.sync.collectors.doubao import DoubaoCollector

COLLECTORS: dict[str, type[Collector]] = {"chatgpt": ChatGPTCollector, "doubao": DoubaoCollector}


def source_type(source_id: str) -> str:
    """提取来源类型前缀，如 `chatgpt:personal` → `chatgpt`。

    前缀未登记时，若只登记了一个 collector 则回退到它，保持旧数据与旧测试的
    无前缀来源 ID 可用；多个 collector 时未知前缀报错，避免路由歧义。
    """
    prefix = source_id.partition(":")[0]
    if prefix in COLLECTORS:
        return prefix
    if len(COLLECTORS) == 1:
        return next(iter(COLLECTORS))
    raise ValueError(f"未知来源类型：{prefix!r}（已登记：{', '.join(sorted(COLLECTORS))}）")


def make_collector(source_id: str, ingested_at: datetime | None = None, *,
                   collector_version: str | None = None) -> Collector:
    """按 source_type 实例化 collector，供 ingest / reprocess 使用。"""
    if collector_version is None:
        name = source_type(source_id)
    else:
        # 重放沿用归档来源类型，使历史无前缀 source 在多 collector 时仍可恢复。
        name = collector_version.partition("@")[0]
        prefix = source_id.partition(":")[0]
        if name not in COLLECTORS or prefix in COLLECTORS and prefix != name:
            raise ValueError("归档 collector 类型未登记或与来源前缀冲突")
    return COLLECTORS[name](source_id, ingested_at)


def metadata_for(source_id: str | None) -> dict[str, Any]:
    """取 collector 元信息；source_id 为 None 时要求恰有一个已登记 collector。"""
    if source_id is None:
        if len(COLLECTORS) != 1:
            raise ValueError("重建全部来源时需明确来源类型，但已登记多个 collector")
        name = next(iter(COLLECTORS))
        return COLLECTORS[name](f"{name}:metadata").metadata()
    return make_collector(source_id).metadata()


def detect_collector(path: str) -> str | None:
    """返回第一个识别该文件的 source_type；无匹配返回 None。"""
    for name in COLLECTORS:
        if make_collector(f"{name}:detect").detect(path):
            return name
    return None
