"""豆包文件输入的合成验收，不读取真实导出或账户。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lifebase.cli import run
from lifebase.core.hashing import sha256_file
from lifebase.core.records import identity_hash
from lifebase.sync.collectors import detect_collector, make_collector
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.quality import quality
from lifebase.sync.rebuild import rebuild
from lifebase.sync.registry import SourceRegistry
from lifebase.sync.verification import verify
from lifebase.vault.manifest import ArchiveManifest
from lifebase.vault.query import query
from lifebase.vault.store import ObjectStore

FIXTURE = Path(__file__).parents[1] / "fixtures" / "doubao" / "export-a.json"
CHATGPT = Path(__file__).parents[1] / "fixtures" / "chatgpt" / "export-a.zip"
SOURCE = "doubao:synthetic-account"


def document() -> dict[str, Any]:
    return json.loads(FIXTURE.read_bytes())


def export(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def rows(root: Path, sql: str, source: str | None = None) -> list[tuple[Any, ...]]:
    return list(query(root / "vault" / "silver", SourceRegistry(root).partitions(source=source), sql).rows)


def fingerprint(root: Path) -> dict[str, tuple[str, int, int]]:
    return {str(p.relative_to(root)): (sha256_file(p), p.stat().st_mode, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


def test_import_preserves_exported_text_source_times_and_json_root_evidence(tmp_path: Path) -> None:
    result = ingest_file(FIXTURE, tmp_path, SOURCE)
    assert (result.events, result.artifacts, result.evidence) == (1, 3, 4)
    assert rows(tmp_path, "SELECT text_parts FROM artifacts WHERE role='user'") == [
        (["  合成问题：野餐带什么？\n"],)]
    assert rows(tmp_path, "SELECT occurred_at, known_at FROM artifacts WHERE text_parts=['合成回复：带水和野餐垫。']") == [
        (datetime(2026, 1, 1, 0, 1, 0, 123456, tzinfo=UTC),
         datetime(2026, 1, 1, 0, 1, 1, tzinfo=UTC))]
    assert rows(tmp_path, "SELECT occurred_at, known_at FROM events") == [(None, None)]
    assert rows(tmp_path, "SELECT count(*) FROM artifacts WHERE parent_record_id IS NOT NULL") == [(0,)]
    assert rows(tmp_path, "SELECT raw_member, raw_pointer FROM evidence WHERE record_kind='event'") == [("", "")]
    assert rows(tmp_path, "SELECT raw_pointer FROM evidence WHERE record_kind='artifact' ORDER BY raw_pointer") == [
        ("/messages/0",), ("/messages/1",), ("/messages/2",)]
    assert rows(tmp_path, "SELECT DISTINCT raw_member_hash FROM evidence") == [(sha256_file(FIXTURE),)]
    assert ObjectStore(tmp_path / "vault").read(result.content_hash) == FIXTURE.read_bytes()
    assert result.quality == quality(tmp_path, source=SOURCE).quality
    assert result.quality.messages.text_versions == 3
    assert result.quality.messages.missing_known_at_versions == 0
    before = fingerprint(tmp_path)
    assert verify(tmp_path).status == "ok"
    assert fingerprint(tmp_path) == before


def test_ten_imports_and_rebuilds_keep_original_times_and_all_files(tmp_path: Path) -> None:
    first = ingest_file(FIXTURE, tmp_path, SOURCE)
    before = fingerprint(tmp_path)
    for _ in range(9):
        result = ingest_file(FIXTURE, tmp_path, SOURCE)
        assert not result.created and result.partition == first.partition
        report = rebuild(tmp_path, SOURCE)
        assert report.status == "ok" and report.rebuilds[0].status == "unchanged"
    assert fingerprint(tmp_path) == before


def test_rebuild_recovers_derived_data_from_plain_json_raw_only(tmp_path: Path) -> None:
    root = tmp_path / "data"
    source = export(tmp_path / "synthetic.json", document())
    ingest_file(source, root, SOURCE)
    expected = {name: rows(root, f"SELECT * FROM {name} ORDER BY ALL")
                for name in ("events", "artifacts", "evidence")}
    bronze = {name: data for name, data in fingerprint(root).items()
              if name.startswith("vault/objects/") or name == "vault/manifest.sqlite"}
    source.rename(tmp_path / "held-synthetic-input")
    (root / "vault" / "silver").rename(tmp_path / "held-synthetic-silver")
    (root / "registry.sqlite").rename(tmp_path / "held-synthetic-registry")
    assert rebuild(root).status == "ok"
    for name, records in expected.items():
        assert rows(root, f"SELECT * FROM {name} ORDER BY ALL") == records
    assert {name: data for name, data in fingerprint(root).items()
            if name in bronze} == bronze
    assert verify(root).status == "ok"


def test_overlap_and_import_order_preserve_versions_and_evidence(tmp_path: Path) -> None:
    revised = document()
    revised["exportedAt"] = "2026-10-07T00:00:00Z"
    revised["messages"].reverse()
    revised["messages"][1]["text"] = "合成修订回复。"
    revised["messages"][1]["raw"]["update_time"] = "1767312000"
    source = export(tmp_path / "synthetic-revised.json", revised)
    roots = [tmp_path / "ab", tmp_path / "ba"]
    for root, paths in zip(roots, [(FIXTURE, source), (source, FIXTURE)], strict=True):
        for path in paths:
            ingest_file(path, root, SOURCE)
        assert rows(root, "SELECT count(DISTINCT record_id), count(*) FROM artifacts") == [(3, 4)]
        assert rows(root, "SELECT count(*) FROM events") == [(1,)]
        assert rows(root, "SELECT count(*) FROM evidence") == [(8,)]
        assert verify(root).status == "ok"
    for table in ("events", "artifacts", "evidence"):
        cols = "* EXCLUDE (ingested_at)" if table == "evidence" else "*"
        assert rows(roots[0], f"SELECT {cols} FROM {table} ORDER BY ALL") == rows(
            roots[1], f"SELECT {cols} FROM {table} ORDER BY ALL")


@pytest.mark.parametrize("timestamp", [None, "", "NaN", "Infinity", True, "1e1000", "1e1000000", "not-a-time"])
def test_bad_message_timestamps_are_null_without_export_time_fallback(
    tmp_path: Path, timestamp: Any,
) -> None:
    data = document()
    data["messages"][0]["raw"]["create_time"] = timestamp
    data["messages"][0]["raw"]["update_time"] = timestamp
    result = ingest_file(export(tmp_path / "synthetic.json", data), tmp_path / "data", SOURCE)
    assert result.artifacts == 3 and result.issues
    assert rows(tmp_path / "data", "SELECT occurred_at, known_at FROM artifacts WHERE role='user'") == [(None, None)]


def test_update_before_creation_stays_unknown(tmp_path: Path) -> None:
    data = document()
    data["messages"][0]["raw"]["update_time"] = "1"
    ingest_file(export(tmp_path / "synthetic.json", data), tmp_path / "data", SOURCE)
    assert rows(tmp_path / "data", "SELECT known_at FROM artifacts WHERE role='user'") == [(None,)]


@pytest.mark.parametrize("problem", [
    "wrong_source", "missing_conversation", "missing_message_id", "duplicate_id",
    "raw_id_mismatch", "raw_conversation_mismatch", "bad_messages", "bad_text", "bad_raw",
])
def test_invalid_structure_is_archived_without_silver(tmp_path: Path, problem: str) -> None:
    data = document()
    if problem == "wrong_source":
        data["source"] = "synthetic-other"
    elif problem == "missing_conversation":
        data["chatId"] = ""
        data["meta"].pop("conversationId")
        for msg in data["messages"]:
            msg["raw"].pop("conversation_id")
    elif problem == "missing_message_id":
        data["messages"][0].pop("messageId")
        data["messages"][0]["raw"].pop("message_id")
    elif problem == "duplicate_id":
        data["messages"].append(data["messages"][0])
    elif problem == "raw_id_mismatch":
        data["messages"][0]["raw"]["message_id"] = "synthetic-other"
    elif problem == "raw_conversation_mismatch":
        data["messages"][0]["raw"]["conversation_id"] = "synthetic-other"
    elif problem == "bad_messages":
        data["messages"] = {}
    elif problem == "bad_text":
        data["messages"][0]["text"] = {"synthetic": "object"}
    else:
        data["messages"][0]["raw"] = "synthetic-not-an-object"
    source = export(tmp_path / "synthetic-invalid.json", data)
    root = tmp_path / "data"
    with pytest.raises(ValueError):
        ingest_file(source, root, SOURCE)
    assert SourceRegistry(root).partitions() == []
    assert ObjectStore(root / "vault").read(sha256_file(source)) == source.read_bytes()
    assert verify(root).status == "ok"


def test_json_input_limit_and_duplicate_keys_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with monkeypatch.context() as patch:
        patch.setattr("lifebase.sync.collectors.doubao.MAX_JSON_BYTES", 2)
        with pytest.raises(ValueError, match="上限"):
            make_collector(SOURCE).ingest(str(FIXTURE))
    bad = tmp_path / "synthetic-duplicate.json"
    bad.write_text('{"source":"doubao","source":"other"}')
    with pytest.raises(ValueError, match="重复"):
        make_collector(SOURCE).ingest(str(bad))


def test_partial_export_diagnostics_do_not_claim_coverage(tmp_path: Path) -> None:
    data = document()
    data["meta"].update(rawCount=10, stopReason="max-api-pages")
    result = ingest_file(export(tmp_path / "synthetic-partial.json", data), tmp_path / "data", SOURCE)
    assert any("coverage" in item for item in result.issues)
    assert any("rawCount" in item for item in result.issues)
    assert SourceRegistry(tmp_path / "data").list_sources()[0]["coverage"] is None


def test_empty_export_and_missing_raw_times_are_preserved(tmp_path: Path) -> None:
    empty = document()
    empty["messages"] = []
    result = ingest_file(export(tmp_path / "synthetic-empty.json", empty), tmp_path / "empty", SOURCE)
    assert (result.events, result.artifacts) == (1, 0)
    data = document()
    data["messages"][0].pop("raw")
    ingest_file(export(tmp_path / "synthetic-no-raw.json", data), tmp_path / "missing", SOURCE)
    assert rows(tmp_path / "missing", "SELECT occurred_at, known_at FROM artifacts WHERE role='user'") == [(None, None)]
    assert verify(tmp_path / "missing").status == "ok"


def test_cli_directory_and_inbox_use_selected_collector_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "data"
    folder = tmp_path / "synthetic-exports"
    folder.mkdir()
    export(folder / "a.json", document())
    export(folder / "b.json", document())
    (folder / "chatgpt.zip").write_bytes(CHATGPT.read_bytes())
    assert run(["ingest", str(folder), "--data-dir", str(root), "--source", SOURCE]) == 0
    report = json.loads(capsys.readouterr().out)
    assert len(report["imports"]) == 2 and report["skipped"] == ["chatgpt.zip"]
    assert [item["status"] for item in report["imports"]] == ["imported", "unchanged"]
    assert run(["query", "--data-dir", str(root), "--source", SOURCE,
                "SELECT count(*) FROM artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == [[3]]
    inbox = root / "inbox"
    inbox.mkdir()
    export(inbox / "doubao.json", document())
    assert run(["ingest", "--data-dir", str(root), "--source", SOURCE]) == 0
    assert json.loads(capsys.readouterr().out)["imports"][0]["status"] == "unchanged"
    assert detect_collector(str(FIXTURE)) == "doubao"


def test_mixed_source_rebuild_restores_each_source_and_reports_its_version(tmp_path: Path) -> None:
    ingest_file(CHATGPT, tmp_path, "chatgpt:synthetic-account")
    ingest_file(FIXTURE, tmp_path, SOURCE)
    report = rebuild(tmp_path)
    assert report.status == "ok" and len(report.rebuilds) == 2
    assert report.collector_version is None and report.parser_version is None
    assert {item.collector_version for item in report.rebuilds} == {"chatgpt@0.2.0", "doubao@0.1.0"}
    assert all(item.status == "unchanged" for item in report.rebuilds)
    assert rows(tmp_path, "SELECT count(*) FROM artifacts", SOURCE) == [(3,)]
    assert rows(tmp_path, "SELECT count(*) FROM artifacts", "chatgpt:synthetic-account") == [(5,)]
    assert verify(tmp_path).status == "ok"


def test_legacy_unprefixed_chatgpt_archive_rebuild_uses_saved_collector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lifebase.sync.collectors import COLLECTORS

    with monkeypatch.context() as patch:
        patch.delitem(COLLECTORS, "doubao")
        ingest_file(CHATGPT, tmp_path, "legacy-synthetic-account")
    assert rebuild(tmp_path).status == "ok"
    assert rows(tmp_path, "SELECT count(*) FROM artifacts") == [(5,)]


@pytest.mark.parametrize("field, value, code", [
    ("raw_member", "synthetic.json", "evidence_locator_invalid"),
    ("raw_pointer", "/messages/99", "evidence_locator_invalid"),
    ("raw_pointer", "/messages/01", "evidence_locator_invalid"),
    ("raw_member_hash", "0" * 64, "evidence_member_hash_mismatch"),
])
def test_plain_json_evidence_tampering_is_detected(
    tmp_path: Path, field: str, value: str, code: str,
) -> None:
    result = ingest_file(FIXTURE, tmp_path, SOURCE)
    folder = tmp_path / "vault" / "silver" / result.partition
    path = folder / "evidence.parquet"
    table = pq.read_table(path)
    records = table.to_pylist()
    row = next(item for item in records if item["record_kind"] == "artifact")
    row[field] = value
    row["evidence_id"] = identity_hash([
        row["record_id"], row["revision_id"], row["content_hash"], row["raw_member"],
        row["raw_pointer"], row["collector_version"], row["parser_version"],
    ])
    pq.write_table(pa.Table.from_pylist(records, schema=table.schema), path)
    meta = folder / "partition.json"
    metadata = json.loads(meta.read_bytes())
    metadata["files"]["evidence"] = sha256_file(path)
    meta.write_text(json.dumps(metadata))
    before = fingerprint(tmp_path)
    report = verify(tmp_path)
    assert code in {issue.code for issue in report.issues}
    assert fingerprint(tmp_path) == before


def test_account_isolation_and_export_capture_time_do_not_change_revisions(tmp_path: Path) -> None:
    for account in (SOURCE, "doubao:synthetic-other"):
        ingest_file(FIXTURE, tmp_path, account)
    assert rows(tmp_path, "SELECT count(DISTINCT record_id) FROM artifacts") == [(6,)]
    data = document()
    data["exportedAt"] = "2026-10-08T00:00:00Z"
    ingest_file(export(tmp_path / "synthetic-later.json", data), tmp_path, SOURCE)
    assert rows(tmp_path, "SELECT count(*) FROM artifacts", SOURCE) == [(3,)]
    assert rows(tmp_path, "SELECT count(*) FROM evidence", SOURCE) == [(8,)]
    assert len(ArchiveManifest(tmp_path / "vault").entries()) == 3
    assert asdict(verify(tmp_path))["status"] == "ok"
    with sqlite3.connect(tmp_path / "registry.sqlite") as db:
        assert db.execute("SELECT count(*) FROM imports").fetchone() == (3,)
