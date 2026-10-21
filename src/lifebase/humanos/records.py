"""HumanOS api_version=1：固定查询输出，不包含模型生成内容。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

Destination = Literal["local", "cloud"]


@dataclass(frozen=True)
class Warning:
    code: str
    message: str
    count: int = 0


@dataclass(frozen=True)
class EvidenceLocator:
    evidence_id: str
    record_kind: str
    record_id: str
    revision_id: str
    source: str
    source_record_id: str
    content_hash: str
    raw_member: str
    raw_member_hash: str
    raw_pointer: str
    collector_version: str
    parser_version: str


@dataclass(frozen=True)
class GraphPath:
    source_node_id: str
    conversation_node_id: str
    message_node_id: str
    topic_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class MessageMatch:
    record_id: str
    revision_id: str
    conversation_id: str
    parent_record_id: str | None
    source: str
    role: str
    occurred_at: datetime | None
    known_at: datetime | None
    excerpt: str
    truncated: bool
    score: float
    matched_topics: tuple[str, ...]
    graph_path: GraphPath
    evidence: tuple[EvidenceLocator, ...]
    version_conflict: bool


@dataclass(frozen=True)
class ConversationSummary:
    """会话元数据与标题；不含消息正文。消息数按身份计，不按内容版本计。
    只给 evidence_id，完整定位经 evidence 工具读取，以控制列表体积。"""
    conversation_id: str
    source: str
    title: str | None
    title_truncated: bool
    first_message_at: datetime | None
    last_message_at: datetime | None
    messages: int
    user_messages: int
    top_topics: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    version_conflict: bool


@dataclass(frozen=True)
class ToolResult:
    tool: str
    status: str
    snapshot_id: str | None
    data: dict[str, Any]
    warnings: tuple[Warning, ...] = ()
    api_version: int = 1


class ToolError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
