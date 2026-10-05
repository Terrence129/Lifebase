"""只追加的 RAW 来源归档索引；首次入库时间供派生数据重建复用。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lifebase.vault.store import ObjectStore


@dataclass(frozen=True)
class ArchiveEntry:
    source: str
    content_hash: str
    original_name: str
    size_bytes: int
    collector_version: str
    ingested_at: datetime


class ArchiveManifest:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "manifest.sqlite"

    def archive(self, path: Path, source: str, collector_version: str) -> ArchiveEntry:
        if not source.strip():
            raise ValueError("source 不能为空")
        stored = ObjectStore(self.root).put_file(path)
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS archives ("
                "source TEXT NOT NULL, content_hash TEXT NOT NULL, original_name TEXT NOT NULL, "
                "size_bytes INTEGER NOT NULL, collector_version TEXT NOT NULL, "
                "ingested_at TEXT NOT NULL, PRIMARY KEY (source, content_hash))"
            )
            db.execute(
                "INSERT OR IGNORE INTO archives VALUES (?, ?, ?, ?, ?, ?)",
                (source, stored.content_hash, path.name, stored.size_bytes, collector_version,
                 datetime.now(UTC).isoformat()),
            )
            row = db.execute(
                "SELECT source, content_hash, original_name, size_bytes, collector_version, "
                "ingested_at FROM archives WHERE source = ? AND content_hash = ?",
                (source, stored.content_hash),
            ).fetchone()
        assert row is not None
        if row[3] != stored.size_bytes:
            raise ValueError("RAW 归档索引中的文件长度与对象不一致")
        return ArchiveEntry(*row[:5], ingested_at=datetime.fromisoformat(row[5]))
