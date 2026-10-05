"""Source Registry：持久化导入结果，派生来源状态与成功分区索引。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from lifebase.vault.manifest import ArchiveEntry


class SourceRegistry:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "registry.sqlite"

    def record(self, entry: ArchiveEntry, metadata: dict[str, Any], *, partition: str | None,
               error: str | None = None, issues: tuple[str, ...] = (),
               earliest: str | None = None, latest: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS imports ("
                "source TEXT NOT NULL, content_hash TEXT NOT NULL, "
                "collector_version TEXT NOT NULL, parser_version TEXT NOT NULL, "
                "schema_version INTEGER NOT NULL, source_type TEXT NOT NULL, "
                "sync_method TEXT NOT NULL, ingested_at TEXT NOT NULL, partition TEXT, "
                "error TEXT, issues TEXT NOT NULL, earliest TEXT, latest TEXT, "
                "PRIMARY KEY (source, content_hash, collector_version, parser_version, schema_version))"
            )
            values = (entry.source, entry.content_hash, metadata["collector_version"],
                      metadata["parser_version"], metadata["schema_version"],
                      metadata["source_type"], metadata["sync_method"], entry.ingested_at.isoformat(),
                      partition, error, json.dumps(issues, ensure_ascii=False), earliest, latest)
            db.execute(
                "INSERT INTO imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (source, content_hash, collector_version, parser_version, "
                "schema_version) DO UPDATE SET partition=excluded.partition, error=excluded.error, "
                "issues=excluded.issues, earliest=excluded.earliest, latest=excluded.latest "
                "WHERE imports.partition IS NOT excluded.partition OR imports.error IS NOT "
                "excluded.error OR imports.issues IS NOT excluded.issues",
                values,
            )

    def _rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM imports ORDER BY source, ingested_at")]

    def partitions(self, *, source: str | None = None, collector_version: str | None = None,
                   parser_version: str | None = None, schema_version: int | None = None) -> list[str]:
        filters = {"source": source, "collector_version": collector_version,
                   "parser_version": parser_version, "schema_version": schema_version}
        return sorted({row["partition"] for row in self._rows()
                       if row["partition"] is not None and row["error"] is None
                       and all(value is None or row[name] == value
                               for name, value in filters.items())})

    def list_sources(self) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows():
            grouped.setdefault(row["source"], []).append(row)
        result: list[dict[str, Any]] = []
        for source, rows in grouped.items():
            successful = [row for row in rows if row["error"] is None and row["partition"] is not None]
            failures = [row for row in rows if row["error"] is not None]
            current = (successful or rows)[-1]
            earliest = [row["earliest"] for row in successful if row["earliest"] is not None]
            latest = [row["latest"] for row in successful if row["latest"] is not None]
            result.append({
                "source_id": source, "source_type": current["source_type"],
                "collector_version": current["collector_version"],
                "parser_version": current["parser_version"], "sync_method": current["sync_method"],
                "last_sync": max((row["ingested_at"] for row in successful), default=None),
                "earliest_record": min(earliest, default=None), "latest_record": max(latest, default=None),
                "coverage": None, "credentials_reference": None,
                "status": "partial" if failures and successful else "error" if failures else "ok",
                "errors": [row["error"] for row in failures],
                "diagnostics": sorted({issue for row in rows for issue in json.loads(row["issues"])}),
                "raw_archives": len({row["content_hash"] for row in rows}),
            })
        return result
