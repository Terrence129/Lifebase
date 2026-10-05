"""垂直切片编排：先保存 RAW，再解析、发布 Silver、记录来源状态。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lifebase.core.hashing import sha256_bytes
from lifebase.core.paths import data_path, require_plain_path
from lifebase.core.records import SCHEMA_VERSION, canonical_json
from lifebase.sync.collectors.chatgpt import ChatGPTCollector
from lifebase.sync.registry import SourceRegistry
from lifebase.vault.manifest import ArchiveEntry, ArchiveManifest
from lifebase.vault.silver import SCHEMAS, SilverStore
from lifebase.vault.store import ObjectStore


@dataclass(frozen=True)
class ImportResult:
    content_hash: str
    partition: str
    created: bool
    events: int
    artifacts: int
    evidence: int
    issues: tuple[str, ...]


def ingest_file(path: Path, data_dir: Path, source: str) -> ImportResult:
    data_dir = data_path(data_dir)
    collector = ChatGPTCollector(source)
    data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata: dict[str, Any] = collector.metadata() | {"schema_version": SCHEMA_VERSION}
    vault = data_dir / "vault"
    entry = ArchiveManifest(vault).archive(path, source, metadata["collector_version"])
    return _process_archive(entry, data_dir, metadata)


def reprocess_archive(entry: ArchiveEntry, data_dir: Path) -> ImportResult:
    """重用已有 RAW 与首次入库时间；不重新归档 inbox 文件。"""
    data_dir = data_path(data_dir)
    if not entry.collector_version.startswith("chatgpt@"):
        raise ValueError("本版只支持重建由 ChatGPT collector 归档的来源")
    metadata = ChatGPTCollector(entry.source).metadata() | {"schema_version": SCHEMA_VERSION}
    return _process_archive(entry, data_dir, metadata)


def _process_archive(entry: ArchiveEntry, data_dir: Path,
                     metadata: dict[str, Any]) -> ImportResult:
    vault = data_dir / "vault"
    for path in (vault / "silver", data_dir / "registry.sqlite"):
        require_plain_path(path, data_dir)
    for suffix in ("-wal", "-shm", "-journal"):
        require_plain_path(data_dir / ("registry.sqlite" + suffix), data_dir)
    registry = SourceRegistry(data_dir)
    pipeline = {"source": entry.source, "content_hash": entry.content_hash,
                "collector_version": metadata["collector_version"],
                "parser_version": metadata["parser_version"], "schema_version": SCHEMA_VERSION}
    key = sha256_bytes(canonical_json(pipeline))
    try:
        require_plain_path(ObjectStore(vault).object_path(entry.content_hash), data_dir)
        require_plain_path(vault / "silver" / key, data_dir)
        for name in ("partition.json", *(f"{table}.parquet" for table in SCHEMAS)):
            require_plain_path(vault / "silver" / key / name, data_dir)
        raw_path = ObjectStore(vault).verify(entry.content_hash)
        if raw_path.stat().st_size != entry.size_bytes:
            raise ValueError("RAW 长度与归档索引不一致")
        collector = ChatGPTCollector(entry.source, entry.ingested_at)
        # 解析归档对象，不重新读取可能在归档后发生变化的 inbox 文件。
        raw = collector.ingest(str(raw_path))
        if raw.content_hash != entry.content_hash:
            raise ValueError("解析时 RAW 对象发生变化")
        records = collector.normalize(raw)
        created = SilverStore(vault / "silver").write(key, records, pipeline)
        times = [record.occurred_at for record in (*records.events, *records.artifacts)
                 if record.occurred_at is not None]
        registry.record(entry, metadata, partition=key, issues=records.issues,
                        earliest=min(times).isoformat() if times else None,
                        latest=max(times).isoformat() if times else None)
        return ImportResult(entry.content_hash, key, created, len(records.events),
                            len(records.artifacts), len(records.evidence), records.issues)
    except (ValueError, OSError) as error:
        registry.record(entry, metadata, partition=None, error=str(error))
        raise
