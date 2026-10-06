"""捕获成功 Silver 输入与规范化记录；只读且兼容历史来源 ID。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa

from lifebase.core.hashing import sha256_file
from lifebase.core.paths import require_plain_path
from lifebase.sync.registry import SourceRegistry
from lifebase.vault.silver import SCHEMAS, SilverStore


class GraphError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class InputSelection:
    partitions: tuple[str, ...]
    sources: dict[str, str]
    fingerprints: tuple[dict[str, Any], ...]

    def descriptor(self) -> dict[str, Any]:
        return {"partitions": list(self.fingerprints), "sources": self.sources}

    def load(self, data_dir: Path) -> dict[str, pa.Table]:
        return SilverStore(data_dir / "vault" / "silver").load(list(self.partitions))


def capture_inputs(data_dir: Path) -> InputSelection:
    require_plain_path(data_dir / "registry.sqlite", data_dir)
    imports = SourceRegistry(data_dir).successful_imports()
    sources: dict[str, str] = {}
    partitions: dict[str, dict[str, Any]] = {}
    store = SilverStore(data_dir / "vault" / "silver")
    for row in imports:
        source, source_type = row["source"], row["source_type"]
        if source in sources and sources[source] != source_type:
            raise GraphError("INPUT_INVALID", "同一来源登记了不同类型")
        sources[source] = source_type
        key = row["partition"]
        folder = store.partition_path(key)
        for filename in ("partition.json", *(f"{name}.parquet" for name in SCHEMAS)):
            require_plain_path(folder / filename, data_dir)
        metadata = store.verify(key)
        expected = {name: row[name] for name in (
            "source", "content_hash", "collector_version", "parser_version", "schema_version")}
        if metadata.get("pipeline") != expected:
            raise GraphError("INPUT_INVALID", "Silver 分区与登记的处理身份不一致")
        partitions[key] = {"partition": key, "metadata_hash": sha256_file(folder / "partition.json"),
                           "files": metadata["files"]}
    return InputSelection(tuple(sorted(partitions)), dict(sorted(sources.items())),
                          tuple(partitions[key] for key in sorted(partitions)))


def unique_rows(table: pa.Table, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    rows: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in table.to_pylist():
        key = tuple(row[name] for name in keys)
        if key in rows and rows[key] != row:
            raise GraphError("INPUT_INVALID", "同一规范化身份与版本出现不同内容")
        rows[key] = row
    return [rows[key] for key in sorted(rows)]


@dataclass
class CanonicalData:
    events: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    evidence: dict[str, dict[str, Any]]
    references: dict[tuple[str, str, str], tuple[str, ...]]
    sources: dict[tuple[str, str, str], str]

    @classmethod
    def from_tables(cls, tables: dict[str, pa.Table], selection: InputSelection) -> CanonicalData:
        events = unique_rows(tables["events"], ("record_id", "revision_id"))
        messages = unique_rows(tables["artifacts"], ("record_id", "revision_id"))
        evidence = {row["evidence_id"]: row
                    for row in unique_rows(tables["evidence"], ("evidence_id",))}
        refs: dict[tuple[str, str, str], list[str]] = {}
        sources: dict[tuple[str, str, str], str] = {}
        for eid, row in evidence.items():
            key = (row["record_kind"], row["record_id"], row["revision_id"])
            if row["source"] not in selection.sources:
                raise GraphError("INPUT_INVALID", "Evidence 指向未登记来源")
            if key in sources and sources[key] != row["source"]:
                raise GraphError("INPUT_INVALID", "规范化身份跨来源混合")
            sources[key] = row["source"]
            refs.setdefault(key, []).append(eid)
        identities: dict[str, str] = {}
        for kind, rows in (("event", events), ("artifact", messages)):
            for row in rows:
                key = (kind, row["record_id"], row["revision_id"])
                if key not in refs:
                    raise GraphError("INPUT_INVALID", "规范化记录缺少 Evidence")
                source = sources[key]
                if row["record_id"] in identities and identities[row["record_id"]] != source:
                    raise GraphError("INPUT_INVALID", "记录身份跨来源混合")
                identities[row["record_id"]] = source
        conversations = {row["record_id"] for row in events}
        for row in messages:
            source = sources[("artifact", row["record_id"], row["revision_id"])]
            if (row["context_record_id"] not in conversations
                    or identities[row["context_record_id"]] != source):
                raise GraphError("INPUT_INVALID", "消息所属会话缺失或来源不同")
        known = {("event", row["record_id"], row["revision_id"]) for row in events}
        known.update(("artifact", row["record_id"], row["revision_id"]) for row in messages)
        if set(refs) != known:
            raise GraphError("INPUT_INVALID", "Evidence 引用了缺失记录")
        return cls(events, messages, evidence,
                   {key: tuple(sorted(values)) for key, values in refs.items()}, sources)
