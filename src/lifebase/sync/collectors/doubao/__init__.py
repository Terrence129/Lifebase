"""doubao-helper JSON collector：保留导出字节和来源身份，规范化已有文本。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any

from lifebase.core.envelope import Envelope
from lifebase.core.hashing import sha256_bytes
from lifebase.core.records import (
    SCHEMA_VERSION,
    Artifact,
    Event,
    Evidence,
    NormalizedRecords,
    RecordKind,
    identity_hash,
    record_id,
    revision_id,
    source_record_id,
)

COLLECTOR_VERSION = "doubao@0.1.0"
PARSER_VERSION = "doubao@0.1.0"
MAX_JSON_BYTES = 128 * 1024 * 1024


class ExportError(ValueError):
    """豆包导出结构错误，归档输入仍保留。"""


@dataclass(frozen=True)
class RawExport:
    content_hash: str
    document: dict[str, Any]


def _string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExportError(f"{location} 必须是非空字符串")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExportError("JSON 含重复 key，不能确定记录结构")
        result[key] = value
    return result


def read_export(path: Path) -> RawExport:
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ExportError("豆包 JSON 超过 128 MiB 处理上限；RAW 已保留")
    with path.open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ExportError("豆包 JSON 超过处理上限；RAW 已保留")
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ExportError(f"无法读取豆包 JSON：{type(error).__name__}") from error
    if not isinstance(document, dict) or document.get("source") != "doubao":
        raise ExportError("JSON 必须是 source=doubao 的 doubao-helper 导出")
    messages = document.get("messages")
    if not isinstance(messages, list) or not all(isinstance(msg, dict) for msg in messages):
        raise ExportError("messages 必须是消息对象数组")
    if "meta" in document and not isinstance(document["meta"], dict):
        raise ExportError("meta 必须是对象")
    return RawExport(sha256_bytes(data), document)


def conversation_id(document: dict[str, Any]) -> str:
    """API conversationId 优先；URL chatId 可能指向不同路由。"""
    meta = document.get("meta", {})
    cid = meta.get("conversationId")
    raw_ids: set[str] = set()
    for msg in document["messages"]:
        raw = msg.get("raw")
        if isinstance(raw, dict) and raw.get("conversation_id") is not None:
            raw_ids.add(_string(raw["conversation_id"], "raw.conversation_id"))
    if cid is not None:
        cid = _string(cid, "meta.conversationId")
    elif len(raw_ids) == 1:
        cid = next(iter(raw_ids))
    else:
        cid = _string(document.get("chatId"), "chatId")
    if raw_ids and raw_ids != {cid}:
        raise ExportError("raw.conversation_id 与会话身份不一致")
    return cid


def message_id(message: dict[str, Any]) -> str:
    raw = message.get("raw")
    if raw is not None and not isinstance(raw, dict):
        raise ExportError("message.raw 必须是对象或 null")
    raw = raw or {}
    rid = next((raw[key] for key in ("message_id", "id", "server_message_id")
                if raw.get(key) is not None), None)
    mid = _string(message.get("messageId", rid), "messageId")
    if rid is not None and _string(rid, "raw.message_id") != mid:
        raise ExportError("messageId 与 raw 消息身份不一致")
    return mid


class DoubaoCollector:
    def __init__(self, source: str, ingested_at: datetime | None = None) -> None:
        self.source = _string(source, "source")
        self.ingested_at = ingested_at

    def detect(self, path: str) -> bool:
        try:
            read_export(Path(path))
            return True
        except (ExportError, OSError):
            return False

    def validate(self, path: str) -> list[str]:
        try:
            self.normalize(self.ingest(path))
            return []
        except (ExportError, OSError) as error:
            return [str(error)]

    def ingest(self, path: str) -> RawExport:
        return read_export(Path(path))

    def normalize(self, raw: RawExport) -> NormalizedRecords:
        document = raw.document
        cid = conversation_id(document)
        title = document.get("title")
        if title is not None and not isinstance(title, str):
            raise ExportError("title 必须是字符串或 null")
        issues = ["doubao:conversation_times_missing", "doubao:parent_links_unmapped",
                  "doubao:coverage_unverified", "doubao:exported_text_only"]
        meta = document.get("meta", {})
        raw_count = meta.get("rawCount")
        if raw_count is not None and (type(raw_count) is not int
                                      or raw_count != len(document["messages"])):
            issues.append("doubao:rawCount_differs_from_exported_messages")
        if meta.get("sourceMode") != "api" or meta.get("stopReason") not in {"no-more", "complete"}:
            issues.append("doubao:coverage_collection_may_be_partial")
        evidence: list[Evidence] = []

        def add_evidence(kind: RecordKind, sid: str, rid: str, revision: str,
                         occurred: datetime | None, known: datetime | None, pointer: str) -> None:
            envelope = Envelope(
                source=self.source, source_record_id=sid, content_hash=raw.content_hash,
                collector_version=COLLECTOR_VERSION, parser_version=PARSER_VERSION,
                occurred_at=occurred, known_at=known, ingested_at=self.ingested_at,
            )
            # 空成员定位整个 JSON；成员哈希与 RAW 文件哈希相同。
            eid = identity_hash([rid, revision, raw.content_hash, "", pointer,
                                 COLLECTOR_VERSION, PARSER_VERSION])
            evidence.append(Evidence(eid, kind, rid, revision, envelope, "", raw.content_hash, pointer))

        def timestamp(value: Any, location: str) -> datetime | None:
            if value is None:
                return None
            try:
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    raise TypeError
                seconds = Decimal(str(value))
                if not seconds.is_finite():
                    raise ValueError
                microseconds = int(seconds * 1_000_000)
                return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=microseconds)
            except (DecimalException, ValueError, TypeError, OverflowError):
                issues.append(f"{location}:invalid_unix_seconds")
                return None

        sid = source_record_id("event", cid)
        context = record_id(self.source, sid)
        payload = {"event_type": "conversation", "title": title,
                   "occurred_at": None, "known_at": None}
        revision = revision_id("event", payload)
        event = Event(context, revision, SCHEMA_VERSION, **payload)
        add_evidence("event", sid, context, revision, None, None, "")
        artifacts: list[Artifact] = []
        seen: set[str] = set()
        for index, message in enumerate(document["messages"]):
            pointer = f"/messages/{index}"
            mid = message_id(message)
            if mid in seen:
                raise ExportError(f"{pointer}:重复消息 ID")
            seen.add(mid)
            role = _string(message.get("role"), pointer + "/role")
            text = message.get("text")
            if not isinstance(text, str):
                raise ExportError(f"{pointer}/text 必须是字符串")
            source_raw = message.get("raw") or {}
            occurred = timestamp(source_raw.get("create_time"), pointer + "/raw/create_time")
            known = timestamp(source_raw.get("update_time"), pointer + "/raw/update_time")
            if known is None:
                issues.append(f"{pointer}:known_at_missing")
            elif occurred is not None and known < occurred:
                issues.append(f"{pointer}:update_before_create")
                known = None
            sid = source_record_id("artifact", cid, mid)
            rid = record_id(self.source, sid)
            payload = {"artifact_type": "message", "context_record_id": context,
                       "parent_record_id": None, "role": role, "content_format": "text",
                       "text_parts": (text,), "occurred_at": occurred, "known_at": known}
            revision = revision_id("artifact", payload)
            artifacts.append(Artifact(rid, revision, SCHEMA_VERSION, **payload))
            add_evidence("artifact", sid, rid, revision, occurred, known, pointer)
        return NormalizedRecords((event,), tuple(artifacts), tuple(evidence), tuple(issues))

    def checkpoint(self) -> dict[str, Any]:
        return {"method": "content_hash"}

    def metadata(self) -> dict[str, Any]:
        return {"name": "doubao", "source_type": "doubao", "sync_method": "export",
                "collector_version": COLLECTOR_VERSION, "parser_version": PARSER_VERSION,
                "egress_policy": "cloud_ok"}
