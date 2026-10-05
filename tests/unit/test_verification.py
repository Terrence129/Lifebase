"""只读完整性审计；故障注入仅在一次性合成测试目录进行。"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lifebase.cli import run
from lifebase.core.hashing import sha256_file
from lifebase.core.records import identity_hash
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.verification import verify
from lifebase.vault.store import ObjectStore

FIXTURES = Path(__file__).parents[1] / "fixtures" / "chatgpt"
SOURCE = "chatgpt:synthetic-account"


def snapshot(root: Path) -> dict[str, tuple[int, int, str | None]]:
    """内容、mtime、权限及目录清单；文件读取可能由 OS 更新 atime。"""
    paths = [root, *root.rglob("*")]
    return {str(path.relative_to(root)): (
        path.stat().st_mode, path.stat().st_mtime_ns,
        sha256_file(path) if path.is_file() else None,
    ) for path in paths}


def sample(root: Path) -> tuple[Path, Path]:
    result = ingest_file(FIXTURES / "export-a.zip", root, SOURCE)
    return (ObjectStore(root / "vault").object_path(result.content_hash),
            root / "vault" / "silver" / result.partition)


def rewrite_table(folder: Path, name: str, rows: list[dict[str, Any]]) -> None:
    """同步更新校验元数据，用于检测哈希之外的关联错误。"""
    path = folder / f"{name}.parquet"
    schema = pq.ParquetFile(path).schema_arrow
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, compression="zstd")
    metadata = json.loads((folder / "partition.json").read_bytes())
    metadata["files"][name] = sha256_file(path)
    metadata["counts"][name] = len(rows)
    (folder / "partition.json").write_text(json.dumps(metadata))


def check_readonly(root: Path) -> dict[str, Any]:
    before = snapshot(root)
    report = asdict(verify(root))
    assert snapshot(root) == before
    return report


def codes(report: dict[str, Any]) -> set[str]:
    return {issue["code"] for issue in report["issues"]}


def test_healthy_overlapping_exports_are_verified_without_changes(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sample(root)
    ingest_file(FIXTURES / "export-b.zip", root, SOURCE)
    before = snapshot(root)
    for _ in range(3):
        report = asdict(verify(root))
        assert report == {"status": "ok", "counts": {
            "raw_objects": 2, "archive_entries": 2, "silver_partitions": 2, "evidence": 15,
        }, "issues": []}
    assert snapshot(root) == before


def test_empty_verify_does_not_create_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "absent"
    assert run(["verify", "--data-dir", str(root)]) == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {
        "raw_objects": 0, "archive_entries": 0, "silver_partitions": 0, "evidence": 0,
    }
    assert not root.exists()
    root.mkdir()
    assert check_readonly(root)["status"] == "ok"


@pytest.mark.parametrize("kind", ["raw_missing", "raw_hash_mismatch", "silver_file_missing",
                                  "silver_hash_mismatch", "silver_missing"])
def test_missing_and_corrupt_files_are_localized_without_repair(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "data"
    raw, folder = sample(root)
    if kind == "raw_missing":
        raw.rename(tmp_path / "held-synthetic-raw")
    elif kind == "raw_hash_mismatch":
        raw.chmod(0o600)
        raw.write_bytes(b"synthetic damage")
    elif kind == "silver_missing":
        folder.rename(tmp_path / "held-synthetic-partition")
    elif kind == "silver_file_missing":
        (folder / "artifacts.parquet").rename(tmp_path / "held-synthetic-parquet")
    else:
        (folder / "artifacts.parquet").write_bytes(b"synthetic damage")
    report = check_readonly(root)
    assert report["status"] == "error" and kind in codes(report)
    assert all(issue["path"] for issue in report["issues"])


@pytest.mark.parametrize("field,value,expected", [
    ("raw_pointer", "/100", "evidence_locator_invalid"),
    ("raw_pointer", "/01", "evidence_locator_invalid"),
    ("raw_member", "missing.json", "evidence_locator_invalid"),
    ("raw_member_hash", "0" * 64, "evidence_member_hash_mismatch"),
    ("revision_id", "sha256:" + "0" * 64, "evidence_record_missing"),
    ("source_record_id", '["event","wrong-synthetic-id"]', "evidence_locator_invalid"),
])
def test_invalid_evidence_with_valid_parquet_hash_is_detected(
    tmp_path: Path, field: str, value: str, expected: str,
) -> None:
    root = tmp_path / "data"
    _, folder = sample(root)
    rows = pq.ParquetFile(folder / "evidence.parquet").read().to_pylist()
    row = next(item for item in rows if item["record_kind"] == "event")
    row[field] = value
    row["evidence_id"] = identity_hash([
        row["record_id"], row["revision_id"], row["content_hash"], row["raw_member"],
        row["raw_pointer"], row["collector_version"], row["parser_version"],
    ])
    rewrite_table(folder, "evidence", rows)
    report = check_readonly(root)
    assert expected in codes(report)
    assert next(issue for issue in report["issues"] if issue["code"] == expected)["evidence_id"]


def test_records_without_evidence_and_broken_links_are_detected(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _, folder = sample(root)
    evidence = pq.ParquetFile(folder / "evidence.parquet").read().to_pylist()
    rewrite_table(folder, "evidence", evidence[1:])
    artifacts = pq.ParquetFile(folder / "artifacts.parquet").read().to_pylist()
    artifacts[0]["context_record_id"] = "sha256:" + "0" * 64
    rewrite_table(folder, "artifacts", artifacts)
    assert {"record_evidence_missing", "record_link_missing", "record_revision_invalid"} <= codes(
        check_readonly(root))


@pytest.mark.parametrize("kind", ["metadata", "schema", "counts", "manifest_size"])
def test_inconsistent_metadata_is_detected_even_when_file_hashes_match(
    tmp_path: Path, kind: str,
) -> None:
    root = tmp_path / "data"
    _, folder = sample(root)
    metadata_path = folder / "partition.json"
    metadata = json.loads(metadata_path.read_bytes())
    expected = "silver_file_invalid"
    if kind == "metadata":
        metadata["pipeline"]["parser_version"] = "synthetic-wrong-version"
        expected = "silver_metadata_invalid"
    elif kind == "counts":
        metadata["counts"]["artifacts"] += 1
    elif kind == "schema":
        path = folder / "artifacts.parquet"
        table = pq.ParquetFile(path).read().drop_columns(["role"])
        pq.write_table(table, path)
        metadata["files"]["artifacts"] = sha256_file(path)
    else:
        with sqlite3.connect(root / "vault" / "manifest.sqlite") as db:
            db.execute("UPDATE archives SET size_bytes=size_bytes+1")
        expected = "raw_size_mismatch"
    metadata_path.write_text(json.dumps(metadata))
    assert expected in codes(check_readonly(root))


def test_failed_parse_is_not_raw_corruption(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "data"
    invalid = tmp_path / "synthetic-invalid.zip"
    invalid.write_bytes(b"synthetic non-ZIP")
    assert run(["ingest", str(invalid), "--source", SOURCE, "--data-dir", str(root)]) == 1
    capsys.readouterr()
    report = check_readonly(root)
    assert report["status"] == "ok"
    assert report["counts"]["raw_objects"] == 1


def test_pointer_escaped_mapping_keys_are_verified(tmp_path: Path) -> None:
    records = json.loads((FIXTURES / "export-a" / "conversations.json").read_bytes())
    nodes = records[0]["mapping"]
    old, new = "node-1-user", "node/1~user"
    node = nodes.pop(old)
    node["id"] = new
    nodes[new] = node
    for other in nodes.values():
        if other["parent"] == old:
            other["parent"] = new
        other["children"] = [new if child == old else child for child in other["children"]]
    source = tmp_path / "synthetic-escaped.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("conversations.json", json.dumps(records))
    root = tmp_path / "data"
    ingest_file(source, root, SOURCE)
    assert check_readonly(root)["status"] == "ok"


def test_unregistered_objects_and_partitions_remain_untouched(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sample(root)
    loose = tmp_path / "synthetic-object"
    loose.write_bytes(b"synthetic orphan")
    ObjectStore(root / "vault").put_file(loose)
    with sqlite3.connect(root / "registry.sqlite") as db:
        db.execute("DELETE FROM imports")
    report = check_readonly(root)
    assert report["status"] == "warning"
    assert {"raw_unregistered", "silver_unregistered"} <= codes(report)


@pytest.mark.parametrize("database", ["registry.sqlite", "vault/manifest.sqlite"])
def test_corrupt_databases_do_not_abort_other_checks(tmp_path: Path, database: str) -> None:
    root = tmp_path / "data"
    raw, _ = sample(root)
    (root / database).write_bytes(b"synthetic database damage")
    raw.chmod(0o600)
    raw.write_bytes(b"synthetic RAW damage")
    assert {"database_invalid", "raw_hash_mismatch"} <= codes(check_readonly(root))


def test_empty_incompatible_database_is_not_mistaken_for_empty_vault(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    with sqlite3.connect(root / "registry.sqlite") as db:
        db.execute("CREATE TABLE imports (source TEXT)")
    assert "database_invalid" in codes(check_readonly(root))


def test_wal_database_is_refused_without_side_effects(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sample(root)
    with sqlite3.connect(root / "registry.sqlite") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE imports SET earliest=NULL")
        db.commit()
        assert Path(str(root / "registry.sqlite") + "-wal").exists()
        assert "database_not_quiescent" in codes(check_readonly(root))


def test_symlink_is_reported_without_reading_target(tmp_path: Path) -> None:
    root = tmp_path / "data"
    raw, _ = sample(root)
    raw.rename(tmp_path / "held-synthetic-raw")
    target = tmp_path / "synthetic-outside"
    target.write_bytes(b"synthetic unrelated bytes")
    raw.symlink_to(target)
    report = asdict(verify(root))
    assert "symlink" in codes(report)
    assert target.read_bytes() == b"synthetic unrelated bytes"


def test_cli_reports_json_and_nonzero_on_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "data"
    raw, _ = sample(root)
    assert run(["--data-dir", str(root), "verify"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    raw.chmod(0o600)
    raw.write_bytes(b"synthetic damage")
    before = snapshot(root)
    assert run(["verify", "--data-dir", str(root)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert "raw_hash_mismatch" in codes(report)
    assert snapshot(root) == before
    assert "synthetic damage" not in json.dumps(report)
