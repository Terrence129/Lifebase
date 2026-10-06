"""只读仓库审计：对象、归档索引、Silver 分区与证据引用。"""

from __future__ import annotations

import json
import re
import sqlite3
import zipfile
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from lifebase.core.hashing import sha256_bytes, sha256_file
from lifebase.core.paths import data_path
from lifebase.core.records import (
    SCHEMA_VERSION,
    canonical_json,
    identity_hash,
    record_id,
    revision_id,
)
from lifebase.sync.collectors.chatgpt import MAX_JSON_BYTES
from lifebase.sync.collectors.doubao import conversation_id as doubao_conversation_id
from lifebase.sync.collectors.doubao import message_id as doubao_message_id
from lifebase.sync.collectors.doubao import read_export as read_doubao_export
from lifebase.vault.silver import SCHEMAS

DATABASE_COLUMNS = {
    "archives": {"source", "content_hash", "original_name", "size_bytes",
                 "collector_version", "ingested_at"},
    "imports": {"source", "content_hash", "collector_version", "parser_version",
                "schema_version", "source_type", "sync_method", "ingested_at", "partition",
                "error", "issues", "earliest", "latest"},
}


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    path: str
    message: str
    severity: str = "error"
    evidence_id: str | None = None


@dataclass
class VerificationReport:
    status: str = "ok"
    counts: dict[str, int] = field(default_factory=lambda: {
        "raw_objects": 0, "archive_entries": 0, "silver_partitions": 0, "evidence": 0,
    })
    issues: list[VerificationIssue] = field(default_factory=list)


def _hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _pointer(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError("JSON Pointer 必须以 / 开头")
    for token in pointer[1:].split("/"):
        if re.search(r"~(?![01])", token):
            raise ValueError("非法 JSON Pointer 转义")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(document, list):
            if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
                raise ValueError("非法数组索引")
            document = document[int(token)]
        elif isinstance(document, dict):
            document = document[token]
        else:
            raise TypeError("JSON Pointer 穿过非容器值")
    return document


class _Verifier:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.report = VerificationReport()

    def issue(self, code: str, path: Path, message: str, *, warning: bool = False,
              evidence_id: str | None = None) -> None:
        self.report.issues.append(VerificationIssue(
            code, str(path.relative_to(self.root)), message,
            "warning" if warning else "error", evidence_id,
        ))

    def safe(self, path: Path) -> bool:
        # 不沿目录或文件符号链接读到数据目录之外。
        if any(parent.is_symlink() for parent in (path, *path.parents)
               if parent == self.root or self.root in parent.parents):
            self.issue("symlink", path, "检查路径含符号链接，未读取目标")
            return False
        return True

    def children(self, path: Path) -> list[Path]:
        if not self.safe(path) or not path.exists():
            return []
        try:
            return sorted(path.iterdir())
        except OSError:
            self.issue("directory_unreadable", path, "无法读取目录")
            return []

    def rows(self, path: Path, table: str) -> list[dict[str, Any]]:
        if not self.safe(path) or not path.exists():
            return []
        logs = [Path(str(path) + suffix) for suffix in ("-wal", "-journal")]
        if any(log.exists() or log.is_symlink() for log in logs):
            self.issue("database_not_quiescent", path, "存在 WAL/恢复日志，请停止写入后重试")
            return []
        try:
            # immutable 防止 SQLite 创建 WAL/SHM 或进行恢复；只检查静止的主库。
            uri = path.as_uri() + "?mode=ro&immutable=1"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                db.row_factory = sqlite3.Row
                if [row[0] for row in db.execute("PRAGMA quick_check")] != ["ok"]:
                    raise sqlite3.DatabaseError("quick_check failed")
                columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if not DATABASE_COLUMNS[table] <= columns:
                    raise sqlite3.DatabaseError("missing columns")
                return [dict(row) for row in db.execute(f"SELECT * FROM {table}")]
        except (sqlite3.Error, OSError):
            self.issue("database_invalid", path, "数据库不可读、结构错误或完整性检查失败")
            return []

    def run(self) -> VerificationReport:
        if not self.root.exists():
            return self.report
        if not self.root.is_dir():
            self.issue("directory_unreadable", self.root, "数据路径不是目录")
            self.report.status = "error"
            return self.report
        vault = self.root / "vault"
        manifest_path = vault / "manifest.sqlite"
        registry_path = self.root / "registry.sqlite"
        archives = self.rows(manifest_path, "archives")
        imports = self.rows(registry_path, "imports")
        self.report.counts["archive_entries"] = len(archives)
        archived: dict[tuple[str, str], dict[str, Any]] = {}
        expected: set[str] = set()
        for row in archives:
            if (not isinstance(row.get("source"), str) or not row["source"].strip()
                    or not _hash(row.get("content_hash"))
                    or not isinstance(row.get("size_bytes"), int) or row["size_bytes"] < 0):
                self.issue("manifest_entry_invalid", manifest_path, "归档条目字段错误")
                continue
            try:
                if (not isinstance(row["original_name"], str)
                        or not isinstance(row["collector_version"], str)
                        or datetime.fromisoformat(row["ingested_at"]).utcoffset() is None):
                    raise ValueError
            except (TypeError, ValueError):
                self.issue("manifest_entry_invalid", manifest_path, "归档来源字段或入库时间错误")
                continue
            archived[row["source"], row["content_hash"]] = row
            expected.add(row["content_hash"])
        registered: dict[str, dict[str, Any]] = {}
        for row in imports:
            if (not isinstance(row.get("source"), str) or not _hash(row.get("content_hash"))
                    or not {"partition", "error", "collector_version", "parser_version",
                            "schema_version"} <= row.keys()):
                self.issue("registry_entry_invalid", registry_path, "导入条目字段错误")
                continue
            expected.add(row["content_hash"])
            if (row["source"], row["content_hash"]) not in archived:
                self.issue("archive_reference_missing", manifest_path,
                           f"导入缺少对应归档条目：{row['content_hash']}")
            if row["partition"] is not None:
                if not _hash(row["partition"]):
                    self.issue("registry_entry_invalid", registry_path, "分区 ID 非法")
                else:
                    registered[row["partition"]] = row
            elif row["error"] is None:
                self.issue("registry_entry_invalid", registry_path, "成功导入缺少分区")

        objects: dict[str, Path] = {}
        objects_root = vault / "objects"
        for shard in self.children(objects_root):
            if not self.safe(shard):
                continue
            if not shard.is_dir() or re.fullmatch(r"[0-9a-f]{2}", shard.name) is None:
                self.issue("raw_path_invalid", shard, "非标准 RAW 对象路径", warning=True)
                continue
            for path in self.children(shard):
                digest = shard.name + path.name
                if not self.safe(path):
                    continue
                if not _hash(digest) or not path.is_file():
                    self.issue("raw_path_invalid", path, "非标准 RAW 对象路径", warning=True)
                    continue
                objects[digest] = path
        self.report.counts["raw_objects"] = len(objects)
        valid_raw: dict[str, Path] = {}
        sizes: dict[str, set[int]] = {}
        for row in archived.values():
            sizes.setdefault(row["content_hash"], set()).add(row["size_bytes"])
        for digest, path in sorted(objects.items()):
            try:
                if sha256_file(path) != digest:
                    self.issue("raw_hash_mismatch", path, "RAW 字节与内容地址不一致")
                else:
                    valid_raw[digest] = path
                    if digest in sizes and sizes[digest] != {path.stat().st_size}:
                        self.issue("raw_size_mismatch", path, "RAW 长度与归档索引不一致")
            except OSError:
                self.issue("raw_unreadable", path, "RAW 对象无法读取")
            if digest not in sizes:
                self.issue("raw_unregistered", path, "RAW 对象没有归档条目", warning=True)
        for digest in sorted(expected - objects.keys()):
            self.issue("raw_missing", objects_root / digest[:2] / digest[2:], "引用的 RAW 对象缺失")
        if objects and not manifest_path.exists():
            self.issue("manifest_missing", manifest_path, "存在 RAW 对象但归档索引缺失")

        silver_root = vault / "silver"
        partitions: dict[str, Path] = {}
        for folder in self.children(silver_root):
            if not self.safe(folder):
                continue
            if not folder.is_dir() or not _hash(folder.name):
                self.issue("silver_path_invalid", folder, "非标准分区或未发布临时目录", warning=True)
                continue
            partitions[folder.name] = folder
        self.report.counts["silver_partitions"] = len(partitions)
        for key in sorted(registered.keys() - partitions.keys()):
            self.issue("silver_missing", silver_root / key, "登记的 Silver 分区缺失")
        for key, folder in sorted(partitions.items()):
            if key not in registered:
                self.issue("silver_unregistered", folder, "已发布分区没有导入登记", warning=True)
            self.partition(folder, registered.get(key), archived, valid_raw)
        if partitions and not registry_path.exists():
            self.issue("registry_missing", registry_path, "存在 Silver 分区但来源索引缺失")
        if self.report.issues:
            self.report.status = ("error" if any(issue.severity == "error"
                                                 for issue in self.report.issues) else "warning")
        return self.report

    def partition(self, folder: Path, imported: dict[str, Any] | None,
                  archived: dict[tuple[str, str], dict[str, Any]],
                  valid_raw: dict[str, Path]) -> None:
        metadata_path = folder / "partition.json"
        if not self.safe(metadata_path):
            return
        try:
            metadata = json.loads(metadata_path.read_bytes())
            pipeline = metadata["pipeline"]
            if (not isinstance(pipeline, dict) or not _hash(pipeline.get("content_hash"))
                    or not isinstance(pipeline.get("source"), str)
                    or pipeline.get("schema_version") != SCHEMA_VERSION
                    or not {"collector_version", "parser_version", "schema_version"} <= pipeline.keys()
                    or sha256_bytes(canonical_json(pipeline)) != folder.name):
                raise ValueError
            if imported is not None and any(pipeline.get(name) != imported.get(name)
                                             for name in pipeline):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            self.issue("silver_metadata_invalid", metadata_path, "分区元数据缺失或与处理身份不一致")
            return
        tables: dict[str, list[dict[str, Any]]] = {}
        for name, schema in SCHEMAS.items():
            path = folder / f"{name}.parquet"
            if not self.safe(path):
                continue
            try:
                if sha256_file(path) != metadata["files"][name]:
                    self.issue("silver_hash_mismatch", path, "Parquet 哈希与分区元数据不一致")
                    continue
                table = pq.ParquetFile(path).read()
                table.validate(full=True)
                if table.schema != schema or any(
                    table.column(item.name).null_count for item in schema if not item.nullable
                ):
                    raise ValueError
                if table.num_rows != metadata["counts"][name]:
                    raise ValueError
                tables[name] = table.to_pylist()
            except FileNotFoundError:
                self.issue("silver_file_missing", path, "分区文件缺失")
            except (OSError, ValueError, KeyError, TypeError, pa.ArrowException):
                self.issue("silver_file_invalid", path, "Parquet 不可读、schema 或行数不匹配")
        if len(tables) != len(SCHEMAS):
            return
        records = {(kind, row["record_id"], row["revision_id"]): row
                   for kind, name in (("event", "events"), ("artifact", "artifacts"))
                   for row in tables[name]}
        if len(records) != len(tables["events"]) + len(tables["artifacts"]):
            self.issue("record_duplicate", folder, "分区中有重复的规范化记录")
        for (kind, rid, revision), row in records.items():
            payload = {name: value for name, value in row.items()
                       if name not in {"record_id", "revision_id", "schema_version"}}
            if row["schema_version"] != SCHEMA_VERSION or revision_id(kind, payload) != revision:
                self.issue("record_revision_invalid", folder, f"记录版本哈希不一致：{rid}")
        event_ids = {row["record_id"] for row in tables["events"]}
        artifact_ids = {row["record_id"] for row in tables["artifacts"]}
        contexts = {row["record_id"]: row["context_record_id"] for row in tables["artifacts"]}
        for row in tables["artifacts"]:
            if (row["context_record_id"] not in event_ids or row["parent_record_id"] is not None
                    and (row["parent_record_id"] not in artifact_ids
                         or contexts[row["parent_record_id"]] != row["context_record_id"])):
                self.issue("record_link_missing", folder, f"消息的会话或父消息缺失：{row['record_id']}")
        referenced = set()
        documents: dict[str, tuple[str, Any, str | None]] = {}
        evidence_ids: set[str] = set()
        for evidence in tables["evidence"]:
            self.report.counts["evidence"] += 1
            if evidence["evidence_id"] in evidence_ids:
                self.issue("evidence_duplicate", folder, "分区中有重复的证据 ID",
                           evidence_id=evidence["evidence_id"])
            evidence_ids.add(evidence["evidence_id"])
            key = (evidence["record_kind"], evidence["record_id"], evidence["revision_id"])
            row = records.get(key)
            if row is None:
                self.issue("evidence_record_missing", folder, "证据指向不存在的规范化记录",
                           evidence_id=evidence["evidence_id"])
                continue
            referenced.add(key)
            try:
                if any(evidence[name] != pipeline[name] for name in (
                    "source", "content_hash", "collector_version", "parser_version",
                )):
                    raise ValueError
                expected_id = identity_hash([
                    evidence["record_id"], evidence["revision_id"], evidence["content_hash"],
                    evidence["raw_member"], evidence["raw_pointer"],
                    evidence["collector_version"], evidence["parser_version"],
                ])
                if evidence["evidence_id"] != expected_id:
                    raise ValueError
                entry = archived[evidence["source"], evidence["content_hash"]]
                if (evidence["ingested_at"] != datetime.fromisoformat(entry["ingested_at"])
                        or evidence["occurred_at"] != row["occurred_at"]
                        or evidence["known_at"] != row["known_at"]):
                    raise ValueError
                raw_path = valid_raw[evidence["content_hash"]]
            except (KeyError, ValueError, TypeError):
                self.issue("evidence_provenance_invalid", folder, "证据与处理版本、归档或时间不一致",
                           evidence_id=evidence["evidence_id"])
                continue
            self.evidence(folder, evidence, raw_path, documents)
        for key in records.keys() - referenced:
            self.issue("record_evidence_missing", folder, f"规范化记录没有证据：{key[1]}")

    def evidence(self, folder: Path, evidence: dict[str, Any], raw_path: Path,
                 documents: dict[str, tuple[str, Any, str | None]]) -> None:
        try:
            member = evidence["raw_member"]
            source_type = evidence["collector_version"].partition("@")[0]
            if source_type == "doubao" and member != "":
                raise ValueError("豆包 JSON 定位须使用文件根")
            if member not in documents:
                if source_type == "doubao":
                    raw = read_doubao_export(raw_path)
                    documents[member] = (raw.content_hash, raw.document,
                                         doubao_conversation_id(raw.document))
                else:
                    with zipfile.ZipFile(raw_path) as archive:
                        if archive.namelist().count(member) != 1:
                            raise ValueError
                        info = archive.getinfo(member)
                        if info.file_size > MAX_JSON_BYTES or info.flag_bits & 1:
                            raise ValueError
                        with archive.open(info) as stream:
                            data = stream.read(MAX_JSON_BYTES + 1)
                        if len(data) > MAX_JSON_BYTES:
                            raise ValueError
                    documents[member] = (sha256_bytes(data), json.loads(data), None)
            digest, document, cid = documents[member]
            if digest != evidence["raw_member_hash"]:
                self.issue("evidence_member_hash_mismatch", folder, "RAW 成员哈希与证据不一致",
                           evidence_id=evidence["evidence_id"])
                return
            value = _pointer(document, evidence["raw_pointer"])
            sid = json.loads(evidence["source_record_id"])
            kind = evidence["record_kind"]
            if (not isinstance(sid, list) or len(sid) != (2 if kind == "event" else 3)
                    or not all(isinstance(part, str) and part for part in sid)
                    or sid[0] != kind or not isinstance(value, dict)
                    or record_id(evidence["source"], evidence["source_record_id"])
                    != evidence["record_id"]):
                raise ValueError
            if source_type == "doubao":
                if sid[1] != cid:
                    raise ValueError
                if kind == "event":
                    if evidence["raw_pointer"] != "":
                        raise ValueError
                elif (re.fullmatch(r"/messages/(0|[1-9][0-9]*)", evidence["raw_pointer"]) is None
                      or doubao_message_id(value) != sid[-1]):
                    raise ValueError
            elif value.get("id") != sid[-1]:
                raise ValueError
            elif kind == "artifact":
                conversation = _pointer(document, "/" + evidence["raw_pointer"].split("/")[1])
                if not isinstance(conversation, dict) or conversation.get("id") != sid[1]:
                    raise ValueError
        except (OSError, ValueError, KeyError, IndexError, TypeError, RuntimeError,
                NotImplementedError, RecursionError, zipfile.BadZipFile):
            self.issue("evidence_locator_invalid", folder, "RAW 成员或 JSON Pointer 无法定位源记录",
                       evidence_id=evidence["evidence_id"])


def verify(data_dir: Path) -> VerificationReport:
    """读取静止的本地仓库；不创建目录、不修复对象、不修改数据库。"""
    return _Verifier(data_path(data_dir)).run()
