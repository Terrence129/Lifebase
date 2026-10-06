"""ChatGPT ZIP collector：保留全部分支，确定性映射到 canonical v1。"""

from __future__ import annotations

import json
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lifebase.core.envelope import Envelope
from lifebase.core.hashing import sha256_bytes, sha256_file
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

COLLECTOR_VERSION = "chatgpt@0.1.0"
PARSER_VERSION = "chatgpt@0.1.0"
MAX_JSON_BYTES = 128 * 1024 * 1024


class ExportError(ValueError):
    """来源格式错误；RAW 仍保留供核查或后续重新解析。"""


@dataclass(frozen=True)
class RawExport:
    content_hash: str
    member: str
    member_hash: str
    conversations: tuple[dict[str, Any], ...]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExportError("JSON 含重复 key，不能无损确定记录结构")
        result[key] = value
    return result


def _required_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExportError(f"{location} 必须是非空字符串")
    return value


def _pointer_key(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


class ChatGPTCollector:
    def __init__(self, source: str, ingested_at: datetime | None = None) -> None:
        self.source = _required_string(source, "source")
        self.ingested_at = ingested_at

    def detect(self, path: str) -> bool:
        try:
            with zipfile.ZipFile(path) as archive:
                return any(
                    name == "conversations.json" or re.fullmatch(r"conversations-\d+\.json", name)
                    for name in archive.namelist()
                )
        except (OSError, zipfile.BadZipFile):
            return False

    def validate(self, path: str) -> list[str]:
        try:
            # 结构错误属于失败；时间缺失等诊断随 normalize 输出，不判为非法归档。
            self.normalize(self.ingest(path))
            return []
        except (ExportError, OSError) as error:
            return [str(error)]

    def ingest(self, path: str) -> RawExport:
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if any(re.fullmatch(r"conversations-\d+\.json", name) for name in names):
                    raise ExportError("本版暂不支持编号会话文件；RAW 已保留")
                if names.count("conversations.json") != 1:
                    raise ExportError("ZIP 必须包含唯一的 conversations.json")
                info = archive.getinfo("conversations.json")
                if info.file_size > MAX_JSON_BYTES:
                    raise ExportError("conversations.json 超过本版 128 MiB 处理上限；RAW 已保留")
                if info.flag_bits & 1:
                    raise ExportError("本版不支持加密 ZIP；RAW 已保留")
                # 不解压到文件系统，避免 ZIP 路径穿越，也不读取其他账户文件或媒体。
                with archive.open(info) as stream:
                    data = stream.read(MAX_JSON_BYTES + 1)
                if len(data) > MAX_JSON_BYTES:
                    raise ExportError("conversations.json 解压大小超过处理上限")
            parsed = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
        except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError,
                NotImplementedError, RecursionError) as error:
            raise ExportError(f"无法读取会话 JSON：{type(error).__name__}") from error
        if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
            raise ExportError("conversations.json 顶层必须是会话对象数组")
        return RawExport(sha256_file(Path(path)), "conversations.json", sha256_bytes(data), tuple(parsed))

    def normalize(self, raw: RawExport) -> NormalizedRecords:
        events: list[Event] = []
        artifacts: list[Artifact] = []
        evidence: list[Evidence] = []
        issues: list[str] = []
        conversation_ids: set[str] = set()

        def timestamp(value: Any, location: str) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                issues.append(f"{location} 不是合法 Unix seconds，保持 null")
                return None
            try:
                if not math.isfinite(value):
                    raise ValueError
                return datetime.fromtimestamp(value, UTC)
            except (ValueError, OverflowError, OSError):
                issues.append(f"{location} 超出可表示时间范围，保持 null")
                return None

        def times(obj: dict[str, Any], location: str) -> tuple[datetime | None, datetime | None]:
            occurred = timestamp(obj.get("create_time"), location + "/create_time")
            known = timestamp(obj.get("update_time"), location + "/update_time")
            if known is None:
                issues.append(f"{location} 缺少可靠 update_time，known_at 保持 null")
            elif occurred is not None and known < occurred:
                issues.append(f"{location} update_time 早于 create_time，known_at 保持 null")
                known = None
            return occurred, known

        def add_evidence(kind: RecordKind, sid: str, rid: str, revision: str,
                         payload: dict[str, Any], pointer: str) -> None:
            envelope = Envelope(
                source=self.source, source_record_id=sid, content_hash=raw.content_hash,
                collector_version=COLLECTOR_VERSION, parser_version=PARSER_VERSION,
                occurred_at=payload["occurred_at"], known_at=payload["known_at"],
                ingested_at=self.ingested_at,
            )
            eid = identity_hash([rid, revision, raw.content_hash, raw.member, pointer,
                                 COLLECTOR_VERSION, PARSER_VERSION])
            evidence.append(Evidence(eid, kind, rid, revision, envelope, raw.member,
                                     raw.member_hash, pointer))

        for index, conv in enumerate(raw.conversations):
            location = f"/{index}"
            cid = _required_string(conv.get("id"), location + "/id")
            if cid in conversation_ids:
                raise ExportError(f"{location} 重复会话 ID")
            conversation_ids.add(cid)
            mapping = conv.get("mapping")
            if not isinstance(mapping, dict) or not mapping:
                raise ExportError(f"{location}/mapping 必须是非空节点对象")
            current = conv.get("current_node")
            if current is not None and (not isinstance(current, str) or current not in mapping):
                raise ExportError(f"{location}/current_node 指向缺失节点")
            title = conv.get("title")
            if title is not None and not isinstance(title, str):
                raise ExportError(f"{location}/title 必须是字符串或 null")
            occurred, known = times(conv, location)
            sid = source_record_id("event", cid)
            context_id = record_id(self.source, sid)
            payload = {"event_type": "conversation", "title": title,
                       "occurred_at": occurred, "known_at": known}
            revision = revision_id("event", payload)
            events.append(Event(context_id, revision, SCHEMA_VERSION, **payload))
            add_evidence("event", sid, context_id, revision, payload, location)

            message_ids: set[str] = set()
            node_records: dict[str, str | None] = {}
            for key, node in mapping.items():
                nloc = f"{location}/mapping/{_pointer_key(key)}"
                if (not isinstance(node, dict) or node.get("id") != key
                        or not {"parent", "children", "message"} <= node.keys()):
                    raise ExportError(f"{nloc} 节点 ID 与 mapping key 不一致")
                parent = node.get("parent")
                children = node.get("children")
                if parent is not None and (not isinstance(parent, str) or parent not in mapping):
                    raise ExportError(f"{nloc}/parent 指向缺失节点")
                if (not isinstance(children, list) or not all(isinstance(c, str) for c in children)
                        or len(set(children)) != len(children)):
                    raise ExportError(f"{nloc}/children 必须是无重复的节点 ID 数组")
                msg = node.get("message")
                if msg is None:
                    node_records[key] = None
                elif isinstance(msg, dict):
                    mid = _required_string(msg.get("id"), nloc + "/message/id")
                    if mid in message_ids:
                        raise ExportError(f"{nloc} 同一会话含重复消息 ID")
                    message_ids.add(mid)
                    node_records[key] = record_id(self.source, source_record_id("artifact", cid, mid))
                else:
                    raise ExportError(f"{nloc}/message 必须是对象或 null")

            # 三色遍历保证无环，缓存最近消息祖先；避免长对话的 O(n²) 回溯。
            nearest: dict[str, str | None] = {}
            for key in mapping:
                chain: list[str] = []
                seen: set[str] = set()
                cursor: str | None = key
                while cursor is not None and cursor not in nearest:
                    if cursor in seen:
                        raise ExportError(f"{location}/mapping 含父节点循环")
                    seen.add(cursor)
                    chain.append(cursor)
                    cursor = mapping[cursor]["parent"]
                ancestor = nearest[cursor] if cursor is not None else None
                for item in reversed(chain):
                    ancestor = node_records[item] or ancestor
                    nearest[item] = ancestor
            for key, node in mapping.items():
                nloc = f"{location}/mapping/{_pointer_key(key)}"
                parent = node.get("parent")
                if parent is not None and key not in mapping[parent]["children"]:
                    raise ExportError(f"{nloc} parent / children 不一致")
                for child in node["children"]:
                    if child not in mapping or mapping[child]["parent"] != key:
                        raise ExportError(f"{nloc} children / parent 不一致")
                msg = node.get("message")
                if msg is None:
                    continue
                author = msg.get("author")
                if not isinstance(author, dict):
                    raise ExportError(f"{nloc}/message/author 缺失")
                role = _required_string(author.get("role"), nloc + "/message/author/role")
                content = msg.get("content")
                if not isinstance(content, dict):
                    raise ExportError(f"{nloc}/message/content 缺失")
                fmt = _required_string(content.get("content_type"), nloc + "/message/content_type")
                parts: tuple[str, ...] | None = None
                if fmt == "text":
                    values = content.get("parts")
                    if not isinstance(values, list) or not all(isinstance(p, str) for p in values):
                        raise ExportError(f"{nloc}/message/content/parts 必须是字符串数组")
                    parts = tuple(values)
                else:
                    issues.append(f"{nloc} 不支持内容类型 {fmt}，保留 RAW 和元数据")
                occurred, known = times(msg, nloc + "/message")
                sid = source_record_id("artifact", cid, msg["id"])
                rid = record_id(self.source, sid)
                payload = {"artifact_type": "message", "context_record_id": context_id,
                           "parent_record_id": nearest[parent] if parent is not None else None,
                           "role": role, "content_format": fmt, "text_parts": parts,
                           "occurred_at": occurred, "known_at": known}
                revision = revision_id("artifact", payload)
                artifacts.append(Artifact(rid, revision, SCHEMA_VERSION, **payload))
                add_evidence("artifact", sid, rid, revision, payload, nloc + "/message")
        return NormalizedRecords(tuple(events), tuple(artifacts), tuple(evidence), tuple(issues))

    def checkpoint(self) -> dict[str, Any]:
        return {"method": "content_hash"}

    def metadata(self) -> dict[str, Any]:
        return {"name": "chatgpt", "source_type": "chatgpt", "sync_method": "export",
                "collector_version": COLLECTOR_VERSION, "parser_version": PARSER_VERSION,
                "egress_policy": "local_only"}
