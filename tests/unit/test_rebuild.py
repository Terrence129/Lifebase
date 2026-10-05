"""RAW 重放验收；输入、派生文件和故障均为一次性合成数据。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from lifebase.cli import run
from lifebase.core.hashing import sha256_file
from lifebase.core.records import NormalizedRecords, identity_hash, revision_id
from lifebase.sync.collectors.chatgpt import ChatGPTCollector, RawExport
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.rebuild import rebuild
from lifebase.sync.registry import SourceRegistry
from lifebase.sync.verification import verify
from lifebase.vault.manifest import ArchiveManifest
from lifebase.vault.query import query
from lifebase.vault.store import ObjectStore

FIXTURES = Path(__file__).parents[1] / "fixtures" / "chatgpt"
SOURCE = "chatgpt:synthetic-account"


def snapshot(root: Path) -> dict[str, tuple[int, int, str | None]]:
    return {str(path.relative_to(root)): (
        path.stat().st_mode, path.stat().st_mtime_ns,
        sha256_file(path) if path.is_file() else None,
    ) for path in [root, *root.rglob("*")]}


def bronze(root: Path) -> dict[str, tuple[int, int, str | None]]:
    return {name: value for name, value in snapshot(root).items()
            if name.startswith("vault/objects") or name == "vault/manifest.sqlite"}


def rows(root: Path, table: str) -> tuple:
    return query(root / "vault" / "silver", SourceRegistry(root).partitions(),
                 f"SELECT * FROM {table} ORDER BY ALL").rows


def sample(root: Path) -> None:
    ingest_file(FIXTURES / "export-a.zip", root, SOURCE)


def changed_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    original = ChatGPTCollector.normalize

    def normalize(self: ChatGPTCollector, raw: RawExport) -> NormalizedRecords:
        records = original(self, raw)
        event = records.events[0]
        payload = {key: value for key, value in asdict(event).items()
                   if key not in {"record_id", "revision_id", "schema_version"}}
        payload["title"] = "synthetic parser correction"
        revision = revision_id("event", payload)
        updated = replace(event, title=payload["title"], revision_id=revision)
        evidence = []
        for item in records.evidence:
            if item.record_kind == "event" and item.record_id == event.record_id:
                eid = identity_hash([item.record_id, revision, item.envelope.content_hash,
                                     item.raw_member, item.raw_pointer,
                                     item.envelope.collector_version, item.envelope.parser_version])
                item = replace(item, revision_id=revision, evidence_id=eid)
            evidence.append(item)
        return replace(records, events=(updated, *records.events[1:]), evidence=tuple(evidence))

    monkeypatch.setattr(ChatGPTCollector, "normalize", normalize)


def test_rebuild_without_inbox_recovers_silver_and_registry_from_raw(tmp_path: Path) -> None:
    root = tmp_path / "data"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    for label in ("export-a", "export-b"):
        source = inbox / f"{label}.zip"
        source.write_bytes((FIXTURES / f"{label}.zip").read_bytes())
        ingest_file(source, root, SOURCE)
    expected = {name: rows(root, name) for name in ("events", "artifacts", "evidence")}
    archived = ArchiveManifest(root / "vault").entries()
    saved = bronze(root)
    # 暂存合成输入和派生产物，模拟只有 RAW 与 manifest 留存；不删除归档数据。
    inbox.rename(tmp_path / "held-inbox")
    (root / "vault" / "silver").rename(tmp_path / "held-silver")
    (root / "registry.sqlite").rename(tmp_path / "held-registry.sqlite")
    report = rebuild(root)
    assert report.status == "ok" and len(report.rebuilds) == 2
    assert all(item.status == "rebuilt" for item in report.rebuilds)
    assert not inbox.exists()
    assert {name: rows(root, name) for name in expected} == expected
    assert bronze(root) == saved
    assert ArchiveManifest(root / "vault").entries() == archived
    assert verify(root).status == "ok"


def test_ten_rebuilds_reuse_every_persisted_file(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sample(root)
    before = snapshot(root)
    for _ in range(10):
        report = rebuild(root)
        assert report.status == "ok" and report.rebuilds[0].status == "unchanged"
    assert snapshot(root) == before


def test_source_filter_preserves_account_identity_and_ingested_times(tmp_path: Path) -> None:
    root = tmp_path / "data"
    for account in ("account-a", "account-b"):
        ingest_file(FIXTURES / "export-a.zip", root, account)
    original = rows(root, "evidence")
    saved = bronze(root)
    (root / "vault" / "silver").rename(tmp_path / "held-silver")
    (root / "registry.sqlite").rename(tmp_path / "held-registry.sqlite")
    report = rebuild(root, "account-a")
    assert len(report.rebuilds) == 1 and report.rebuilds[0].source == "account-a"
    assert len(rows(root, "artifacts")) == 5 and len(rows(root, "evidence")) == 7
    assert all(row in original for row in rows(root, "evidence"))
    assert bronze(root) == saved
    assert verify(root).status == "ok"
    assert rebuild(root, "unknown-account").rebuilds == ()


def test_parser_upgrade_keeps_old_partitions_and_can_query_specific_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "data"
    sample(root)
    old_partition = SourceRegistry(root).partitions()[0]
    old_files = snapshot(root / "vault" / "silver" / old_partition)
    saved = bronze(root)
    monkeypatch.setattr("lifebase.sync.collectors.chatgpt.PARSER_VERSION", "chatgpt@0.1.1")
    changed_parser(monkeypatch)
    report = rebuild(root)
    assert report.parser_version == "chatgpt@0.1.1" and report.rebuilds[0].status == "rebuilt"
    registry = SourceRegistry(root)
    assert len(registry.partitions()) == 2
    assert registry.partitions(parser_version="chatgpt@0.1.0") == [old_partition]
    assert registry.partitions(schema_version=99) == []
    assert registry.partitions(source="unknown-account") == []
    assert snapshot(root / "vault" / "silver" / old_partition) == old_files
    assert bronze(root) == saved
    assert len(rows(root, "events")) == 3
    for version, count in (("chatgpt@0.1.0", 0), ("chatgpt@0.1.1", 1)):
        assert run(["query", "--data-dir", str(root), "--source", SOURCE,
                    "--collector-version", "chatgpt@0.1.0", "--parser-version", version,
                    "--schema-version", "1", ("SELECT count(*) FROM events "
                    "WHERE title='synthetic parser correction'")]) == 0
        assert json.loads(capsys.readouterr().out)["rows"] == [[count]]
    assert verify(root).status == "ok"


def test_changed_results_without_version_bump_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    sample(root)
    saved = bronze(root)
    silver = snapshot(root / "vault" / "silver")
    changed_parser(monkeypatch)
    report = rebuild(root)
    assert report.status == "error"
    assert "不同逻辑结果" in report.rebuilds[0].error
    assert bronze(root) == saved and snapshot(root / "vault" / "silver") == silver


@pytest.mark.parametrize("kind", ["missing_raw", "corrupt_raw", "corrupt_silver"])
def test_bad_archive_does_not_overwrite_evidence_or_block_other_archives(
    tmp_path: Path, kind: str,
) -> None:
    root = tmp_path / "data"
    a = ingest_file(FIXTURES / "export-a.zip", root, SOURCE)
    ingest_file(FIXTURES / "export-b.zip", root, SOURCE)
    raw = ObjectStore(root / "vault").object_path(a.content_hash)
    if kind == "missing_raw":
        raw.rename(tmp_path / "held-synthetic-raw")
    elif kind == "corrupt_raw":
        raw.chmod(0o600)
        raw.write_bytes(b"synthetic RAW damage")
    else:
        (root / "vault" / "silver" / a.partition / "artifacts.parquet").write_bytes(
            b"synthetic derived damage")
    saved = bronze(root)
    silver = snapshot(root / "vault" / "silver")
    report = rebuild(root)
    assert report.status == "partial"
    assert sorted(item.status for item in report.rebuilds) == ["error", "unchanged"]
    assert bronze(root) == saved and snapshot(root / "vault" / "silver") == silver
    assert len(rows(root, "artifacts")) == 6


def test_retry_recovers_a_previous_normalization_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    original = ChatGPTCollector.normalize

    def fail(self: ChatGPTCollector, raw: RawExport) -> NormalizedRecords:
        raise ValueError("synthetic parser failure")

    monkeypatch.setattr(ChatGPTCollector, "normalize", fail)
    with pytest.raises(ValueError, match="synthetic parser failure"):
        sample(root)
    saved = bronze(root)
    monkeypatch.setattr(ChatGPTCollector, "normalize", original)
    assert rebuild(root).status == "ok"
    assert bronze(root) == saved and len(rows(root, "artifacts")) == 5
    assert SourceRegistry(root).list_sources()[0]["status"] == "ok"


def test_cli_empty_rebuild_and_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "absent"
    assert run(["rebuild", "--data-dir", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok" and report["rebuilds"] == [] and not root.exists()
    sample(root)
    assert run(["--data-dir", str(root), "rebuild", "--source", SOURCE]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["schema_version"] == 1 and report["rebuilds"][0]["status"] == "unchanged"
    raw = ObjectStore(root / "vault").object_path(report["rebuilds"][0]["content_hash"])
    raw.rename(tmp_path / "held-synthetic-raw")
    assert run(["rebuild", "--data-dir", str(root)]) == 1
    assert json.loads(capsys.readouterr().out)["rebuilds"][0]["status"] == "error"


def test_missing_manifest_cannot_invent_source_or_ingested_time(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sample(root)
    (root / "vault" / "manifest.sqlite").rename(tmp_path / "held-manifest.sqlite")
    before = snapshot(root)
    with pytest.raises(ValueError, match="归档索引缺失"):
        rebuild(root)
    assert snapshot(root) == before


def test_manifest_wal_and_corrupt_index_stop_before_writing(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sample(root)
    path = root / "vault" / "manifest.sqlite"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE archives SET original_name='synthetic-renamed.zip'")
        db.commit()
        before = snapshot(root)
        with pytest.raises(ValueError, match="WAL"):
            rebuild(root)
        assert snapshot(root) == before
    finally:
        db.close()
    path.write_bytes(b"synthetic database corruption")
    before = snapshot(root)
    with pytest.raises(sqlite3.Error):
        rebuild(root)
    assert snapshot(root) == before


def test_symlink_registry_is_not_written(tmp_path: Path) -> None:
    root = tmp_path / "data"
    sample(root)
    registry = root / "registry.sqlite"
    target = tmp_path / "held-registry.sqlite"
    registry.rename(target)
    registry.symlink_to(target)
    before = sha256_file(target)
    report = rebuild(root)
    assert report.status == "error" and "符号链接" in report.rebuilds[0].error
    assert sha256_file(target) == before


@pytest.mark.parametrize("kind", ["partition_metadata", "registry_journal"])
def test_symlink_metadata_and_database_auxiliary_paths_are_rejected(
    tmp_path: Path, kind: str,
) -> None:
    root = tmp_path / "data"
    sample(root)
    target = tmp_path / "synthetic-outside"
    if kind == "partition_metadata":
        key = SourceRegistry(root).partitions()[0]
        path = root / "vault" / "silver" / key / "partition.json"
        path.rename(target)
    else:
        path = root / "registry.sqlite-journal"
        target.write_bytes(b"synthetic unrelated bytes")
    path.symlink_to(target)
    before = sha256_file(target)
    saved = bronze(root)
    report = rebuild(root)
    assert report.status == "error" and "符号链接" in report.rebuilds[0].error
    assert sha256_file(target) == before and bronze(root) == saved
