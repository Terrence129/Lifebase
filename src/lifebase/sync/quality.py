"""导入与逻辑数据集质量统计；只报告数量，不输出消息正文。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lifebase.core.paths import data_path
from lifebase.core.records import NormalizedRecords
from lifebase.sync.registry import SourceRegistry
from lifebase.vault.query import query


@dataclass(frozen=True)
class RecordQuality:
    identities: int
    versions: int
    missing_occurred_at_versions: int
    missing_known_at_versions: int


@dataclass(frozen=True)
class MessageQuality(RecordQuality):
    text_versions: int
    empty_text_versions: int
    unsupported_content_versions: int
    unsupported_content_types: dict[str, int]


@dataclass(frozen=True)
class QualityReport:
    status: str
    conversations: RecordQuality
    messages: MessageQuality
    evidence: int


@dataclass(frozen=True)
class DatasetQuality:
    selected_partitions: int
    filters: dict[str, str | int | None]
    quality: QualityReport


def _report(conversations: RecordQuality, messages: MessageQuality, evidence: int) -> QualityReport:
    has_gaps = (conversations.missing_occurred_at_versions
                or conversations.missing_known_at_versions or messages.missing_occurred_at_versions
                or messages.missing_known_at_versions or messages.unsupported_content_versions
                or messages.empty_text_versions)
    status = "empty" if not conversations.versions and not messages.versions else (
        "warning" if has_gaps else "ok"
    )
    return QualityReport(status, conversations, messages, evidence)


def quality_from_records(records: NormalizedRecords) -> QualityReport:
    """单次规范化结果，按身份/版本去重；不把 NULL 时间当作可靠时间。"""
    conversations = {(item.record_id, item.revision_id): item for item in records.events
                     if item.event_type == "conversation"}
    messages = {(item.record_id, item.revision_id): item for item in records.artifacts
                if item.artifact_type == "message"}
    conversation_quality = RecordQuality(
        len({item.record_id for item in conversations.values()}), len(conversations),
        sum(item.occurred_at is None for item in conversations.values()),
        sum(item.known_at is None for item in conversations.values()),
    )
    unsupported = Counter(item.content_format for item in messages.values()
                          if item.content_format != "text" or item.text_parts is None)
    message_quality = MessageQuality(
        len({item.record_id for item in messages.values()}), len(messages),
        sum(item.occurred_at is None for item in messages.values()),
        sum(item.known_at is None for item in messages.values()),
        sum(item.content_format == "text" and item.text_parts is not None
            for item in messages.values()),
        sum(item.content_format == "text" and item.text_parts is not None
            and not "".join(item.text_parts) for item in messages.values()),
        sum(unsupported.values()), dict(sorted(unsupported.items())),
    )
    return _report(conversation_quality, message_quality,
                   len({item.evidence_id for item in records.evidence}))


QUALITY_SQL = """
WITH conversations AS (SELECT * FROM events WHERE event_type='conversation'),
messages AS (SELECT * FROM artifacts WHERE artifact_type='message'),
unsupported AS (
    SELECT content_format, count(*) AS versions FROM messages
    WHERE content_format <> 'text' OR text_parts IS NULL GROUP BY content_format
)
SELECT * FROM (
    SELECT count(DISTINCT record_id) AS conversation_identities,
           count(*) AS conversation_versions,
           count(*) FILTER (WHERE occurred_at IS NULL) AS conversation_missing_occurred,
           count(*) FILTER (WHERE known_at IS NULL) AS conversation_missing_known
    FROM conversations
) c CROSS JOIN (
    SELECT count(DISTINCT record_id) AS message_identities, count(*) AS message_versions,
           count(*) FILTER (WHERE occurred_at IS NULL) AS message_missing_occurred,
           count(*) FILTER (WHERE known_at IS NULL) AS message_missing_known,
           count(*) FILTER (WHERE content_format='text' AND text_parts IS NOT NULL) AS text_versions,
           count(*) FILTER (WHERE content_format='text' AND text_parts IS NOT NULL
                           AND coalesce(array_to_string(text_parts, ''), '')='') AS empty_text,
           count(*) FILTER (WHERE content_format <> 'text' OR text_parts IS NULL) AS unsupported_count
    FROM messages
) m CROSS JOIN (SELECT count(*) AS evidence_count FROM evidence) e CROSS JOIN (
    SELECT list(struct_pack(format := content_format, versions := versions)
                ORDER BY content_format) AS unsupported_types FROM unsupported
) u
"""


def quality(data_dir: Path, *, source: str | None = None, collector_version: str | None = None,
            parser_version: str | None = None, schema_version: int | None = None) -> DatasetQuality:
    """通过已有只读查询，汇总选中分区的逻辑版本；不会创建数据目录。"""
    root = data_path(data_dir)
    filters = {"source": source, "collector_version": collector_version,
               "parser_version": parser_version, "schema_version": schema_version}
    partitions = SourceRegistry(root).partitions(
        source=source, collector_version=collector_version,
        parser_version=parser_version, schema_version=schema_version,
    )
    result = query(root / "vault" / "silver", partitions, QUALITY_SQL)
    row = dict(zip(result.columns, result.rows[0], strict=True))
    conversations = RecordQuality(row["conversation_identities"], row["conversation_versions"],
                                  row["conversation_missing_occurred"], row["conversation_missing_known"])
    messages = MessageQuality(
        row["message_identities"], row["message_versions"], row["message_missing_occurred"],
        row["message_missing_known"], row["text_versions"], row["empty_text"], row["unsupported_count"],
        {item["format"]: item["versions"] for item in row["unsupported_types"] or []},
    )
    return DatasetQuality(len(partitions), filters,
                          _report(conversations, messages, row["evidence_count"]))
