"""只追加的 RAW 来源归档索引；首次入库时间供派生数据重建复用。"""

from __future__ import annotations

import re
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

    def entries(self, source: str | None = None) -> list[ArchiveEntry]:
        """只读已归档来源；不创建索引、不改变首次入库时间。"""
        if self.root.is_symlink() or self.path.is_symlink():
            raise ValueError("归档索引路径不能是符号链接")
        if not self.path.exists():
            return []
        logs = [Path(str(self.path) + suffix) for suffix in ("-wal", "-journal")]
        if any(log.exists() or log.is_symlink() for log in logs):
            raise ValueError("归档索引存在 WAL/恢复日志，请停止写入后重试")
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro&immutable=1",
                                     uri=True)) as db:
            if [row[0] for row in db.execute("PRAGMA quick_check")] != ["ok"]:
                raise ValueError("归档索引完整性检查失败")
            sql = ("SELECT source, content_hash, original_name, size_bytes, collector_version, "
                   "ingested_at FROM archives")
            params: tuple[str, ...] = ()
            if source is not None:
                sql += " WHERE source = ?"
                params = (source,)
            rows = db.execute(sql + " ORDER BY source, content_hash", params).fetchall()
        entries: list[ArchiveEntry] = []
        for row in rows:
            if (not all(isinstance(row[index], str) and row[index].strip() for index in (0, 1, 4))
                    or re.fullmatch(r"[0-9a-f]{64}", row[1]) is None
                    or not isinstance(row[2], str) or not isinstance(row[3], int) or row[3] < 0):
                raise ValueError("归档索引含非法条目，未开始重建")
            try:
                instant = datetime.fromisoformat(row[5])
                if instant.utcoffset() is None:
                    raise ValueError
            except (TypeError, ValueError) as error:
                raise ValueError("归档索引入库时间非法，未开始重建") from error
            entries.append(ArchiveEntry(*row[:5], ingested_at=instant))
        return entries

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
