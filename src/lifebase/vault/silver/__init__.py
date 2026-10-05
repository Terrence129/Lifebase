"""Canonical v1 Parquet 分区：完整快照原子发布，查询时按身份与版本去重。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from lifebase.core.hashing import sha256_file
from lifebase.core.records import NormalizedRecords, canonical_json

UTC_TIME = pa.timestamp("us", tz="UTC")
COMMON = [pa.field("record_id", pa.string(), nullable=False),
          pa.field("revision_id", pa.string(), nullable=False),
          pa.field("schema_version", pa.int32(), nullable=False)]
SCHEMAS = {
    "events": pa.schema(COMMON + [
        pa.field("event_type", pa.string(), nullable=False), pa.field("title", pa.string()),
        pa.field("occurred_at", UTC_TIME), pa.field("known_at", UTC_TIME),
    ]),
    "artifacts": pa.schema(COMMON + [
        pa.field("artifact_type", pa.string(), nullable=False),
        pa.field("context_record_id", pa.string(), nullable=False),
        pa.field("parent_record_id", pa.string()), pa.field("role", pa.string(), nullable=False),
        pa.field("content_format", pa.string(), nullable=False),
        pa.field("text_parts", pa.list_(pa.field("element", pa.string(), nullable=False))),
        pa.field("occurred_at", UTC_TIME), pa.field("known_at", UTC_TIME),
    ]),
    "evidence": pa.schema([
        pa.field(name, pa.string(), nullable=False) for name in (
            "evidence_id", "record_kind", "record_id", "revision_id", "source", "source_record_id",
            "content_hash", "collector_version", "parser_version",
        )
    ] + [pa.field(name, UTC_TIME) for name in (
        "occurred_at", "known_at", "ingested_at", "valid_from", "valid_to",
    )] + [pa.field(name, pa.string(), nullable=False) for name in (
        "raw_member", "raw_member_hash", "raw_pointer",
    )]),
}


class SilverError(ValueError):
    """派生分区缺失、不完整或被修改，不能静默查询部分数据。"""


class SilverStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def partition_path(self, key: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", key) is None:
            raise SilverError("非法 Silver 分区 ID")
        return self.root / key

    def verify(self, key: str) -> dict[str, Any]:
        folder = self.partition_path(key)
        try:
            if folder.is_symlink():
                raise SilverError("Silver 分区不能是符号链接")
            metadata = json.loads((folder / "partition.json").read_text(encoding="utf-8"))
            for name in SCHEMAS:
                file = folder / f"{name}.parquet"
                if file.is_symlink() or sha256_file(file) != metadata["files"][name]:
                    raise SilverError(f"Silver 分区哈希不一致：{key}/{name}")
            return metadata
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise SilverError(f"Silver 分区缺失或不完整：{key}") from error

    def _tables(self, records: NormalizedRecords) -> dict[str, pa.Table]:
        rows = {"events": [asdict(record) for record in records.events],
                "artifacts": [asdict(record) for record in records.artifacts],
                "evidence": [record.row() for record in records.evidence]}
        tables: dict[str, pa.Table] = {}
        for name, schema in SCHEMAS.items():
            values = sorted(rows[name], key=lambda row: (row["record_id"], row.get("revision_id"),
                                                        row.get("evidence_id", "")))
            table = pa.Table.from_pylist(values, schema=schema)
            table.validate(full=True)
            tables[name] = table
        return tables

    def _reuse(self, key: str, tables: dict[str, pa.Table], pipeline: dict[str, Any]) -> None:
        if self.verify(key)["pipeline"] != pipeline:
            raise SilverError("分区处理版本与请求不一致")
        try:
            for name, expected in tables.items():
                actual = pq.ParquetFile(self.partition_path(key) / f"{name}.parquet").read()
                if actual.schema != expected.schema or not actual.equals(expected):
                    raise SilverError("相同处理版本生成了不同逻辑结果；请核对并升级 parser 版本")
        except pa.ArrowException as error:
            raise SilverError("已有分区无法读取，未替换产物") from error

    def write(self, key: str, records: NormalizedRecords, pipeline: dict[str, Any]) -> bool:
        folder = self.partition_path(key)
        tables = self._tables(records)
        if folder.exists():
            self._reuse(key, tables, pipeline)
            return False
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.root))
        try:
            hashes: dict[str, str] = {}
            counts: dict[str, int] = {}
            for name, table in tables.items():
                file = staging / f"{name}.parquet"
                pq.write_table(table, file, compression="zstd")
                hashes[name] = sha256_file(file)
                counts[name] = table.num_rows
            (staging / "partition.json").write_bytes(canonical_json(
                {"pipeline": pipeline, "files": hashes, "counts": counts}
            ))
            try:
                staging.rename(folder)
            except OSError:
                # 另一个进程先发布同一分区时复用完整产物；不替换任何已发布分区。
                if not folder.exists():
                    raise
                self._reuse(key, tables, pipeline)
                return False
            self.verify(key)
            return True
        finally:
            if staging.exists():
                shutil.rmtree(staging)  # 只清理本次创建、尚未发布的临时派生目录。

    def load(self, keys: list[str]) -> dict[str, pa.Table]:
        tables: dict[str, list[pa.Table]] = {name: [] for name in SCHEMAS}
        for key in keys:
            self.verify(key)
            folder = self.partition_path(key)
            for name, schema in SCHEMAS.items():
                table = pq.ParquetFile(folder / f"{name}.parquet").read()
                if table.schema != schema:
                    raise SilverError(f"Silver schema 不一致：{key}/{name}")
                tables[name].append(table)
        return {name: pa.concat_tables(values) if values else pa.Table.from_pylist([], schema=SCHEMAS[name])
                for name, values in tables.items()}
