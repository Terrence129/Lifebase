"""合成数据端到端验收：幂等、版本、证据、故障恢复与只读查询。"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow.parquet as pq
import pytest

from lifebase.cli import run
from lifebase.core.hashing import sha256_bytes, sha256_file
from lifebase.core.records import record_id, source_record_id
from lifebase.sync.collectors.chatgpt import ChatGPTCollector, ExportError
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.registry import SourceRegistry
from lifebase.vault.query import query
from lifebase.vault.store import ObjectStore

FIXTURES = Path(__file__).parents[1] / "fixtures" / "chatgpt"
SOURCE = "chatgpt:synthetic-account"
EXPECTED = json.loads((FIXTURES / "expectations.json").read_text(encoding="utf-8"))


def select(root: Path, sql: str) -> list[tuple[Any, ...]]:
    return list(query(root / "vault" / "silver", SourceRegistry(root).partitions(), sql).rows)


def fingerprint(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): sha256_file(path)
            for path in root.rglob("*") if path.is_file()}


def write_export(path: Path, records: list[dict[str, Any]]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(records, ensure_ascii=False))
    return path


def base_records() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "export-a" / "conversations.json").read_text(encoding="utf-8"))


def test_ten_imports_do_not_change_any_persisted_product(tmp_path: Path) -> None:
    root = tmp_path / "data"
    first = ingest_file(FIXTURES / "export-a.zip", root, SOURCE)
    before = fingerprint(root)
    for _ in range(9):
        result = ingest_file(FIXTURES / "export-a.zip", root, SOURCE)
        assert not result.created
        assert result.partition == first.partition
    assert fingerprint(root) == before
    expected = EXPECTED["scenarios"]["a_ten_times"]
    assert select(root, "SELECT count(*) FROM events") == [(expected["event_versions"],)]
    assert select(root, "SELECT count(*) FROM artifacts") == [(expected["artifact_versions"],)]
    assert select(root, "SELECT count(*) FROM evidence") == [(expected["evidence_rows"],)]
    assert len(SourceRegistry(root).partitions()) == 1


def test_overlap_versions_and_import_order(tmp_path: Path) -> None:
    roots = [tmp_path / "ab", tmp_path / "ba"]
    for root, labels in zip(roots, [("export-a", "export-b"), ("export-b", "export-a")], strict=True):
        for label in labels:
            ingest_file(FIXTURES / f"{label}.zip", root, SOURCE)
        expected = EXPECTED["scenarios"]["a_then_b"]
        assert select(root, "SELECT count(DISTINCT record_id), count(*) FROM events") == [
            (expected["event_identities"], expected["event_versions"])]
        assert select(root, "SELECT count(DISTINCT record_id), count(*) FROM artifacts") == [
            (expected["artifact_identities"], expected["artifact_versions"])]
        assert select(root, "SELECT count(*) FROM evidence") == [(expected["evidence_rows"],)]
        assert len([p for p in (root / "vault" / "objects").rglob("*") if p.is_file()]) == 2
    for table in ("events", "artifacts", "evidence"):
        columns = "* EXCLUDE (ingested_at)" if table == "evidence" else "*"
        assert select(roots[0], f"SELECT {columns} FROM {table} ORDER BY ALL") == select(
            roots[1], f"SELECT {columns} FROM {table} ORDER BY ALL")


def test_all_evidence_roundtrips_to_exact_raw_message(tmp_path: Path) -> None:
    for label in ("export-a", "export-b"):
        ingest_file(FIXTURES / f"{label}.zip", tmp_path, SOURCE)
    rows = select(tmp_path,
                  "SELECT e.content_hash, e.raw_member, e.raw_member_hash, e.raw_pointer, "
                  "e.source_record_id, a.text_parts FROM evidence e JOIN artifacts a "
                  "USING (record_id, revision_id) WHERE e.record_kind = 'artifact'")
    assert len(rows) == 11
    store = ObjectStore(tmp_path / "vault")
    for content_hash, member, member_hash, pointer, sid, parts in rows:
        path = store.verify(content_hash)
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(member)
        assert sha256_bytes(raw) == member_hash
        value = json.loads(raw)
        for token in pointer.lstrip("/").split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
        assert json.loads(sid)[-1] == value["id"]
        assert parts == value["content"]["parts"]
    assert select(tmp_path,
                  "SELECT count(*) FROM evidence e LEFT JOIN events v USING(record_id, revision_id) "
                  "WHERE e.record_kind='event' AND v.record_id IS NULL") == [(0,)]


def test_branch_relationships_and_conservative_times(tmp_path: Path) -> None:
    ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    parent = record_id(SOURCE, source_record_id("artifact", "synthetic-conversation-1",
                                               "synthetic-message-1"))
    assert select(tmp_path, f"SELECT count(*) FROM artifacts WHERE parent_record_id='{parent}'") == [(2,)]
    missing = record_id(SOURCE, source_record_id("artifact", "synthetic-conversation-2",
                                                "synthetic-message-5"))
    assert select(tmp_path, f"SELECT occurred_at, known_at FROM artifacts WHERE record_id='{missing}'") == [
        (None, None)]
    recall = record_id(SOURCE, source_record_id("artifact", "synthetic-conversation-2",
                                               "synthetic-message-4"))
    instant = datetime(2026, 1, 2, tzinfo=UTC)
    assert select(tmp_path, f"SELECT occurred_at, known_at FROM artifacts WHERE record_id='{recall}'") == [
        (instant, instant)]
    records = base_records()
    records[0]["mapping"]["node-1-user"]["message"]["update_time"] = None
    raw = write_export(tmp_path / "missing-update.zip", records)
    output = ChatGPTCollector(SOURCE).normalize(ChatGPTCollector(SOURCE).ingest(str(raw)))
    message = next(record for record in output.artifacts if record.record_id == parent)
    assert message.occurred_at is not None and message.known_at is None


@pytest.mark.parametrize("bad_time", [True, "yesterday", 10**1000, -10**1000])
def test_bad_timestamps_preserve_record_with_null(tmp_path: Path, bad_time: Any) -> None:
    records = base_records()
    msg = records[0]["mapping"]["node-1-user"]["message"]
    msg["create_time"] = bad_time
    msg["update_time"] = bad_time
    archive = write_export(tmp_path / "invalid-time.zip", records)
    result = ingest_file(archive, tmp_path / "data", SOURCE)
    assert result.artifacts == 5 and result.issues
    rid = record_id(SOURCE, source_record_id("artifact", "synthetic-conversation-1",
                                            "synthetic-message-1"))
    assert select(tmp_path / "data", f"SELECT occurred_at, known_at FROM artifacts WHERE record_id='{rid}'") == [
        (None, None)]


def test_non_text_is_metadata_not_fabricated_text(tmp_path: Path) -> None:
    records = base_records()
    records[0]["mapping"]["node-1-user"]["message"]["content"] = {
        "content_type": "multimodal_text", "parts": [{"synthetic_image": "placeholder"}]}
    archive = write_export(tmp_path / "media.zip", records)
    result = ingest_file(archive, tmp_path / "data", SOURCE)
    assert result.artifacts == 5 and result.issues
    assert select(tmp_path / "data", "SELECT text_parts FROM artifacts WHERE content_format='multimodal_text'") == [
        (None,)]


def test_bad_graph_remains_in_raw_and_registry_reports_failure(tmp_path: Path) -> None:
    records = base_records()
    mapping = records[0]["mapping"]
    mapping["node-1-user"]["parent"] = "node-1-assistant-a"
    mapping["node-1-assistant-a"]["children"] = ["node-1-user"]
    archive = write_export(tmp_path / "cycle.zip", records)
    data = tmp_path / "data"
    with pytest.raises(ExportError, match="循环"):
        ingest_file(archive, data, SOURCE)
    assert ObjectStore(data / "vault").read(sha256_file(archive)) == archive.read_bytes()
    assert SourceRegistry(data).partitions() == []
    assert SourceRegistry(data).list_sources()[0]["status"] == "error"
    ingest_file(FIXTURES / "export-a.zip", data, SOURCE)
    assert SourceRegistry(data).list_sources()[0]["status"] == "partial"


def test_atomic_partition_failure_can_be_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = pq.write_table
    calls = 0

    def fail_second(*args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic disk fault")
        original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(pq, "write_table", fail_second)
        with pytest.raises(OSError, match="synthetic disk fault"):
            ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    assert SourceRegistry(tmp_path).partitions() == []
    assert not list((tmp_path / "vault" / "silver").iterdir())
    ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    assert SourceRegistry(tmp_path).list_sources()[0]["status"] == "ok"
    assert select(tmp_path, "SELECT count(*) FROM artifacts") == [(5,)]


def test_two_accounts_share_raw_but_not_message_identity(tmp_path: Path) -> None:
    for source in ("chatgpt:account-a", "chatgpt:account-b"):
        ingest_file(FIXTURES / "export-a.zip", tmp_path, source)
    assert select(tmp_path, "SELECT count(*) FROM artifacts") == [(10,)]
    assert select(tmp_path, "SELECT count(DISTINCT content_hash), count(DISTINCT source) FROM evidence") == [(1, 2)]


def test_parser_upgrade_reuses_content_and_adds_processing_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    monkeypatch.setattr("lifebase.sync.collectors.chatgpt.PARSER_VERSION", "chatgpt@0.1.1")
    ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    assert select(tmp_path, "SELECT count(*) FROM artifacts") == [(5,)]
    assert select(tmp_path, "SELECT count(*) FROM evidence") == [(14,)]


def test_query_rejects_mutations_and_external_access(tmp_path: Path) -> None:
    ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    for sql in ("DELETE FROM artifacts", "SELECT 1; SELECT 2", "SET enable_external_access=true"):
        with pytest.raises(ValueError, match="仅允许"):
            select(tmp_path, sql)
    local = tmp_path / "synthetic-private.txt"
    local.write_text("synthetic-only")
    quoted = str(local).replace("'", "''")
    with pytest.raises(duckdb.Error):
        select(tmp_path, f"SELECT * FROM read_text('{quoted}')")
    assert select(tmp_path, "SELECT count(*) FROM artifacts") == [(5,)]


def test_cli_inbox_list_query_and_explicit_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "data"
    assert run(["list", "--data-dir", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert not root.exists()
    assert run(["query", "--data-dir", str(root), "SELECT count(*) FROM artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == [[0]]
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "export.zip").write_bytes((FIXTURES / "export-a.zip").read_bytes())
    (inbox / "unrelated.txt").write_text("synthetic unrelated input")
    assert run(["--data-dir", str(root), "ingest", "--source", SOURCE]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["imports"][0]["status"] == "imported"
    assert output["skipped"] == ["unrelated.txt"]
    assert run(["ingest", "--data-dir", str(root), str(FIXTURES / "export-a.zip"), "--source", SOURCE]) == 0
    assert json.loads(capsys.readouterr().out)["imports"][0]["status"] == "unchanged"
    assert run(["list", "--data-dir", str(root)]) == 0
    sources = json.loads(capsys.readouterr().out)
    assert sources[0]["source_id"] == SOURCE and sources[0]["status"] == "ok"
    assert run(["query", "--data-dir", str(root), "SELECT count(*) FROM artifacts"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == [[5]]
    assert run(["query", "--data-dir", str(root), "DROP TABLE artifacts"]) == 1
    assert "仅允许" in capsys.readouterr().err


def test_cli_reports_error_and_keeps_raw(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = tmp_path / "malformed.zip"
    raw.write_bytes(b"synthetic non-ZIP")
    data = tmp_path / "data"
    assert run(["ingest", "--data-dir", str(data), str(raw), "--source", SOURCE]) == 1
    assert json.loads(capsys.readouterr().out)["imports"][0]["status"] == "error"
    assert ObjectStore(data / "vault").read(sha256_file(raw)) == raw.read_bytes()


def test_same_text_different_ids_are_not_merged(tmp_path: Path) -> None:
    records = base_records()
    nodes = records[0]["mapping"]
    nodes["node-1-assistant-b"]["message"]["content"] = nodes["node-1-assistant-a"]["message"]["content"]
    archive = write_export(tmp_path / "same-text.zip", records)
    ingest_file(archive, tmp_path / "data", SOURCE)
    assert select(tmp_path / "data", "SELECT count(*) FROM artifacts") == [(5,)]
    assert select(tmp_path / "data", "SELECT count(*) FROM artifacts WHERE role='assistant' "
                  "AND text_parts=['可以准备水、点心和野餐垫。']") == [(2,)]


def test_pointer_escapes_source_node_keys(tmp_path: Path) -> None:
    records = base_records()
    nodes = records[0]["mapping"]
    old, new = "node-1-user", "node/1~user"
    node = nodes.pop(old)
    node["id"] = new
    nodes[new] = node
    for other in nodes.values():
        if other["parent"] == old:
            other["parent"] = new
        other["children"] = [new if child == old else child for child in other["children"]]
    archive = write_export(tmp_path / "pointer.zip", records)
    ingest_file(archive, tmp_path / "data", SOURCE)
    rid = record_id(SOURCE, source_record_id("artifact", "synthetic-conversation-1",
                                            "synthetic-message-1"))
    assert select(tmp_path / "data", f"SELECT raw_pointer FROM evidence WHERE record_id='{rid}'") == [
        ("/0/mapping/node~11~0user/message",)]


def test_cli_query_dates_and_duplicate_column_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    sql = "SELECT occurred_at AS t, occurred_at AS t FROM artifacts WHERE occurred_at IS NOT NULL LIMIT 1"
    assert run(["query", "--data-dir", str(tmp_path), sql]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["columns"] == ["t", "t"]
    assert len(result["rows"][0]) == 2
    assert result["rows"][0][0].endswith("+00:00")
    assert result["rows"][0][0] == result["rows"][0][1]


def test_corrupted_silver_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    from lifebase.vault.silver import SilverError

    result = ingest_file(FIXTURES / "export-a.zip", tmp_path, SOURCE)
    file = tmp_path / "vault" / "silver" / result.partition / "artifacts.parquet"
    file.write_bytes(b"synthetic derived corruption")
    with pytest.raises(SilverError, match="哈希不一致"):
        select(tmp_path, "SELECT count(*) FROM artifacts")


def test_data_directory_inside_git_worktree_is_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "synthetic-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    with pytest.raises(ValueError, match="Git 工作树"):
        ingest_file(FIXTURES / "export-a.zip", repo / "data", SOURCE)
    assert not (repo / "data").exists()


def test_ambiguous_versions_are_exposed_in_conflict_view(tmp_path: Path) -> None:
    ingest_file(FIXTURES / "export-a.zip", tmp_path / "data", SOURCE)
    records = base_records()
    message = records[0]["mapping"]["node-1-assistant-a"]["message"]
    message["content"]["parts"] = ["synthetic changed content without reliable modification time"]
    message["update_time"] = None
    archive = write_export(tmp_path / "ambiguous.zip", records)
    ingest_file(archive, tmp_path / "data", SOURCE)
    rid = record_id(SOURCE, source_record_id("artifact", "synthetic-conversation-1",
                                            "synthetic-message-2"))
    assert select(tmp_path / "data", "SELECT record_kind, record_id, revision_count "
                  "FROM record_conflicts") == [("artifact", rid, 2)]
    assert select(tmp_path / "data", "SELECT count(*) FROM artifacts") == [(6,)]
