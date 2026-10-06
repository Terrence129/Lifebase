"""Gold 快照原子发布与只读加载；不更新 RAW、Silver 或来源索引。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from lifebase.core.hashing import sha256_bytes, sha256_file
from lifebase.core.paths import data_path, require_plain_path
from lifebase.core.records import canonical_json
from lifebase.graph.build import build_tables, counts, validate_references
from lifebase.graph.inputs import CanonicalData, GraphError, InputSelection, capture_inputs
from lifebase.graph.keywords import extractor_metadata
from lifebase.graph.records import GRAPH_SCHEMA_VERSION, SCHEMAS, GraphReport


def _pipeline(inputs: InputSelection, keyword_count: int) -> dict[str, Any]:
    return {"graph_schema_version": GRAPH_SCHEMA_VERSION, "inputs": inputs.descriptor(),
            "keywords_per_message": keyword_count, "extractor": extractor_metadata()}


def _snapshot_id(pipeline: dict[str, Any]) -> str:
    return sha256_bytes(canonical_json(pipeline))


@dataclass(frozen=True)
class GraphSnapshot:
    snapshot_id: str
    pipeline: dict[str, Any]
    tables: dict[str, pa.Table]
    silver: dict[str, pa.Table]
    inputs: InputSelection


class GraphStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_path(data_dir)
        self.root = self.data_dir / "vault" / "gold"

    def _path(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        require_plain_path(path, self.data_dir)
        return path

    def _folder(self, key: str) -> Path:
        if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{64}", key) is None:
            raise GraphError("GRAPH_INVALID", "非法 Gold 快照身份")
        return self._path(key)

    def current(self) -> str:
        path = self._path("current.json")
        if not path.exists():
            raise GraphError("GRAPH_MISSING", "尚未构图；请运行 lifebase graph build")
        try:
            if path.stat().st_size > 4096:
                raise ValueError("pointer size")
            value = json.loads(path.read_text(encoding="utf-8"))
            key = value["snapshot_id"]
            self._folder(key)
            return key
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise GraphError("GRAPH_INVALID", "Gold 当前快照指针损坏") from error

    def verify(self, key: str) -> tuple[dict[str, Any], dict[str, pa.Table]]:
        self._folder(key)
        try:
            metadata_path = self._path(key, "snapshot.json")
            if metadata_path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("metadata size")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            pipeline = metadata["pipeline"]
            if (metadata["snapshot_id"] != key or _snapshot_id(pipeline) != key
                    or pipeline["graph_schema_version"] != GRAPH_SCHEMA_VERSION):
                raise ValueError("identity mismatch")
            tables: dict[str, pa.Table] = {}
            for name, schema in SCHEMAS.items():
                path = self._path(key, f"{name}.parquet")
                if sha256_file(path) != metadata["files"][name]:
                    raise ValueError("hash mismatch")
                table = pq.ParquetFile(path).read()
                table.validate(full=True)
                if table.schema != schema or table.num_rows != metadata["counts"][name]:
                    raise ValueError("schema or count mismatch")
                tables[name] = table
            if counts(tables) != metadata["counts"]:
                raise ValueError("counts mismatch")
            return metadata, tables
        except (OSError, ValueError, KeyError, TypeError, pa.ArrowException) as error:
            raise GraphError("GRAPH_INVALID", "Gold 快照缺失、损坏或身份不一致") from error

    def _activate(self, key: str) -> None:
        path = self._path("current.json")
        payload = canonical_json({"snapshot_id": key})
        if path.exists() and path.read_bytes() == payload:
            return
        with tempfile.NamedTemporaryFile(prefix=".current-", dir=self.root, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def publish(self, pipeline: dict[str, Any], tables: dict[str, pa.Table],
                inputs: InputSelection) -> GraphReport:
        key = _snapshot_id(pipeline)
        folder = self._folder(key)
        self._path().mkdir(parents=True, exist_ok=True, mode=0o700)
        created = False
        if folder.exists():
            metadata, actual = self.verify(key)
            if (metadata["pipeline"] != pipeline
                    or any(not tables[name].equals(actual[name]) for name in SCHEMAS)):
                raise GraphError("GRAPH_INVALID", "同一处理身份产生不同图谱；请升级提取器版本")
        else:
            staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.root))
            try:
                hashes = {}
                for name, table in tables.items():
                    path = staging / f"{name}.parquet"
                    pq.write_table(table, path, compression="zstd")
                    hashes[name] = sha256_file(path)
                (staging / "snapshot.json").write_bytes(canonical_json(
                    {"snapshot_id": key, "pipeline": pipeline,
                     "files": hashes, "counts": counts(tables)}))
                if capture_inputs(self.data_dir).descriptor() != inputs.descriptor():
                    raise GraphError("GRAPH_STALE", "构图期间 Silver 输入改变；请重新构图")
                try:
                    staging.rename(folder)
                    created = True
                except OSError:
                    if not folder.exists():
                        raise
                    _, actual = self.verify(key)
                    if any(not tables[name].equals(actual[name]) for name in SCHEMAS):
                        raise GraphError("GRAPH_INVALID", "并发构图产物不同") from None
                self.verify(key)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        if capture_inputs(self.data_dir).descriptor() != inputs.descriptor():
            raise GraphError("GRAPH_STALE", "激活前 Silver 输入改变；请重新构图")
        self._activate(key)
        return GraphReport("ok", key, counts(tables), created)


def build_graph(data_dir: Path, keywords_per_message: int = 5) -> GraphReport:
    if type(keywords_per_message) is not int or not 1 <= keywords_per_message <= 50:
        raise GraphError("INVALID_REQUEST", "每条消息关键词数量必须为 1–50")
    store = GraphStore(data_dir)
    inputs = capture_inputs(store.data_dir)
    silver = inputs.load(store.data_dir)
    data = CanonicalData.from_tables(silver, inputs)
    pipeline = _pipeline(inputs, keywords_per_message)
    tables = build_tables(data, inputs, keywords_per_message)
    validate_references(tables, data, inputs, keywords_per_message)
    return store.publish(pipeline, tables, inputs)


def load_graph(data_dir: Path) -> GraphSnapshot:
    store = GraphStore(data_dir)
    key = store.current()
    metadata, tables = store.verify(key)
    inputs = capture_inputs(store.data_dir)
    pipeline = metadata["pipeline"]
    keyword_count = pipeline.get("keywords_per_message")
    if type(keyword_count) is not int or not 1 <= keyword_count <= 50:
        raise GraphError("GRAPH_INVALID", "Gold 提取参数损坏")
    if pipeline != _pipeline(inputs, keyword_count):
        raise GraphError("GRAPH_STALE", "Silver 输入或提取器已更新；请运行 lifebase graph build")
    silver = inputs.load(store.data_dir)
    data = CanonicalData.from_tables(silver, inputs)
    validate_references(tables, data, inputs, keyword_count)
    return GraphSnapshot(key, pipeline, tables, silver, inputs)


def graph_status(data_dir: Path) -> GraphReport:
    store = GraphStore(data_dir)
    key = None
    try:
        key = store.current()
        snapshot = load_graph(data_dir)
        return GraphReport("ok", key, counts(snapshot.tables))
    except (ValueError, OSError, pa.ArrowException) as error:
        code = error.code if isinstance(error, GraphError) else "INPUT_INVALID"
        status = {"GRAPH_MISSING": "missing", "GRAPH_STALE": "stale"}.get(code, "error")
        return GraphReport(status, key, {}, issues=({"code": code, "message": str(error)},))
