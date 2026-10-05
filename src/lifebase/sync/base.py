"""Collector 适配器契约 —— 全项目最重要的接口。

方法名固定（docs/context.md §23），每个新 collector 必须实现。
Collector 实例统一以 `(source_id, ingested_at=None)` 构造；`metadata()["source_type"]`
必须等于 `collector_version` 的 `@` 前缀（如 `chatgpt@0.1.0` → `chatgpt`），
来源路由与登记见 `sync/collectors/__init__.py` 注册表。
Collector 只负责：识别来源、校验、提取 RAW、规范化。
Collector 不直接写应用数据库 —— 数据流：
    Collector → RAW → Normalizer → Canonical records

幂等性要求（docs/context.md §24）：同一份导出导入 10 次只产生 1 份数据。
"""

from __future__ import annotations

from typing import Any, Protocol


class Collector(Protocol):
    def detect(self, path: str) -> bool:
        """识别该文件/目录是否属于此来源。"""
        ...

    def validate(self, path: str) -> list[str]:
        """校验导出内容，返回问题列表（空列表 = 通过）。"""
        ...

    def ingest(self, path: str) -> Any:
        """提取 RAW 内容，返回待归档的原始记录。"""
        ...

    def normalize(self, raw: Any) -> Any:
        """将 RAW 规范化为此来源的 canonical 记录（确定性，不用 LLM）。"""
        ...

    def checkpoint(self) -> dict[str, Any]:
        """返回增量同步所需的检查点（cursor / last_sync）。"""
        ...

    def metadata(self) -> dict[str, Any]:
        """返回 collector 元信息（名称、版本、来源类型）。"""
        ...
