"""垂直切片编排：先保存 RAW，再解析、发布 Silver、记录来源状态。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lifebase.core.hashing import sha256_bytes
from lifebase.core.paths import data_path
from lifebase.core.records import SCHEMA_VERSION, canonical_json
from lifebase.sync.collectors.chatgpt import ChatGPTCollector
from lifebase.sync.registry import SourceRegistry
from lifebase.vault.manifest import ArchiveManifest
from lifebase.vault.silver import SilverStore
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
    registry = SourceRegistry(data_dir)
    pipeline = {"source": source, "content_hash": entry.content_hash,
                "collector_version": metadata["collector_version"],
                "parser_version": metadata["parser_version"], "schema_version": SCHEMA_VERSION}
    key = sha256_bytes(canonical_json(pipeline))
    try:
        raw_path = ObjectStore(vault).verify(entry.content_hash)
        collector = ChatGPTCollector(source, entry.ingested_at)
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
