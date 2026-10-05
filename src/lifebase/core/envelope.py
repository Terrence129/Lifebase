"""统一数据封装（Envelope）—— 每个进入系统的记录都带这些字段。

时间语义（docs/context.md §14）：
    occurred_at / known_at 的区分是 Past Me 正确性的根基：
    检索 Past Me @ 2022 必须按 known_at 过滤，而不是 occurred_at。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Envelope:
    source: str  # 数据源 ID（Source Registry 中的 source_id）
    source_record_id: str  # 源系统中的记录 ID（幂等去重的依据）
    content_hash: str  # RAW 字节的 sha256（内容寻址引用）
    collector_version: str  # 采集器版本，如 chatgpt@0.1.0
    parser_version: str  # 解析器版本，如 chatgpt@0.1.0
    occurred_at: datetime | None = None  # 事件发生时间
    known_at: datetime | None = None  # 信息被知晓/记录的时间
    ingested_at: datetime | None = None  # 进入系统的时间（由 vault 写入）
    valid_from: datetime | None = None
    valid_to: datetime | None = None
