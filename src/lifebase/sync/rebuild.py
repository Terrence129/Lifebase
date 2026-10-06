"""从只读 RAW 归档索引重建 Silver 与 Source Registry。"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from lifebase.core.paths import data_path, require_plain_path
from lifebase.core.records import SCHEMA_VERSION
from lifebase.sync.collectors import COLLECTORS, make_collector, metadata_for
from lifebase.sync.pipeline import ImportResult, reprocess_archive
from lifebase.vault.manifest import ArchiveManifest


@dataclass(frozen=True)
class RebuildItem:
    source: str
    content_hash: str
    original_name: str
    status: str
    result: ImportResult | None = None
    error: str | None = None
    collector_version: str | None = None
    parser_version: str | None = None


@dataclass(frozen=True)
class RebuildReport:
    status: str
    collector_version: str | None
    parser_version: str | None
    schema_version: int
    rebuilds: tuple[RebuildItem, ...]


def rebuild(data_dir: Path, source: str | None = None) -> RebuildReport:
    """使用当前安装的处理版本逐条重放；缺失产物可生成，已有产物不覆盖。"""
    root = data_path(data_dir)
    if root.exists() and not root.is_dir():
        raise ValueError("数据路径不是目录")
    if source is not None and not source.strip():
        raise ValueError("source 不能为空")
    manifest = ArchiveManifest(root / "vault")
    require_plain_path(manifest.path, root)
    require_plain_path(root / "vault" / "objects", root)
    objects = root / "vault" / "objects"
    if not manifest.path.exists() and objects.exists() and any(objects.iterdir()):
        raise ValueError("RAW 存在但归档索引缺失，无法恢复来源和首次入库时间")
    entries = manifest.entries(source)
    versions: set[tuple[str, str]] = set()
    if not entries:
        if source is not None and source.partition(":")[0] in COLLECTORS:
            metadata = metadata_for(source)
            versions.add((metadata["collector_version"], metadata["parser_version"]))
        elif source is None and len(COLLECTORS) == 1:
            metadata = metadata_for(None)
            versions.add((metadata["collector_version"], metadata["parser_version"]))
    results: list[RebuildItem] = []
    for entry in entries:
        metadata = {}
        try:
            metadata = make_collector(entry.source,
                                      collector_version=entry.collector_version).metadata()
            versions.add((metadata["collector_version"], metadata["parser_version"]))
            result = reprocess_archive(entry, root)
            results.append(RebuildItem(entry.source, entry.content_hash, entry.original_name,
                                       "rebuilt" if result.created else "unchanged", result,
                                       collector_version=metadata["collector_version"],
                                       parser_version=metadata["parser_version"]))
        except (ValueError, OSError, sqlite3.Error) as error:
            results.append(RebuildItem(entry.source, entry.content_hash, entry.original_name,
                                       "error", error=str(error),
                                       collector_version=metadata.get("collector_version"),
                                       parser_version=metadata.get("parser_version")))
    failed = [item for item in results if item.status == "error"]
    status = "partial" if failed and len(failed) < len(results) else "error" if failed else "ok"
    collector_version, parser_version = next(iter(versions)) if len(versions) == 1 else (None, None)
    return RebuildReport(status, collector_version, parser_version, SCHEMA_VERSION, tuple(results))
