"""Canonical v1：平台无关的会话事件、消息内容与来源证据。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from lifebase.core.envelope import Envelope
from lifebase.core.hashing import sha256_bytes

SCHEMA_VERSION = 1
RecordKind = Literal["event", "artifact"]


def _json_default(value: object) -> str:
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    raise TypeError("canonical JSON 只支持 JSON 值与带时区的 datetime")


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=_json_default).encode("utf-8")


def identity_hash(value: object) -> str:
    return "sha256:" + sha256_bytes(canonical_json(value))


def source_record_id(kind: RecordKind, conversation_id: str, message_id: str | None = None) -> str:
    parts = [kind, conversation_id]
    if message_id is not None:
        parts.append(message_id)
    return canonical_json(parts).decode("utf-8")


def record_id(source: str, source_id: str) -> str:
    return identity_hash([source, source_id])


def revision_id(kind: RecordKind, payload: dict[str, Any]) -> str:
    return identity_hash([SCHEMA_VERSION, kind, payload])


@dataclass(frozen=True)
class Event:
    record_id: str
    revision_id: str
    schema_version: int
    event_type: str
    title: str | None
    occurred_at: datetime | None
    known_at: datetime | None


@dataclass(frozen=True)
class Artifact:
    record_id: str
    revision_id: str
    schema_version: int
    artifact_type: str
    context_record_id: str
    parent_record_id: str | None
    role: str
    content_format: str
    text_parts: tuple[str, ...] | None
    occurred_at: datetime | None
    known_at: datetime | None


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    record_kind: RecordKind
    record_id: str
    revision_id: str
    envelope: Envelope
    raw_member: str
    raw_member_hash: str
    raw_pointer: str

    def row(self) -> dict[str, Any]:
        value = asdict(self)
        envelope = value.pop("envelope")
        return value | envelope


@dataclass(frozen=True)
class NormalizedRecords:
    events: tuple[Event, ...]
    artifacts: tuple[Artifact, ...]
    evidence: tuple[Evidence, ...]
    issues: tuple[str, ...] = ()
