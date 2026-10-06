"""合成新版导出验收：分片、仅 parent 的节点、混合文本与逐成员证据。"""

from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lifebase.cli import run
from lifebase.core.hashing import sha256_bytes, sha256_file
from lifebase.core.records import identity_hash, record_id, source_record_id
from lifebase.sync.collectors.chatgpt import ChatGPTCollector, ExportError
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.quality import quality
from lifebase.sync.rebuild import rebuild
from lifebase.sync.registry import SourceRegistry
from lifebase.sync.verification import verify
from lifebase.vault.query import query
from lifebase.vault.store import ObjectStore

FIXTURES = Path(__file__).parents[1] / "fixtures" / "chatgpt"
SOURCE = "chatgpt:synthetic-sharded"
MEMBERS = ["conversations-000.json", "conversations-001.json"]


def sharded_members() -> dict[str, bytes]:
    """只从已有合成样例派生，不读取本机真实导出。"""
    records = json.loads((FIXTURES / "export-a" / "conversations.json").read_bytes())
    for conversation in records:
        for node in conversation["mapping"].values():
            node.pop("children")
            if node["message"] is not None:
                node["message"].pop("update_time")
    records[0]["mapping"]["node-1-user"]["message"]["content"] = {
        "content_type": "multimodal_text",
        "parts": ["  synthetic before\n", {"image": "synthetic-only"}, "synthetic after  "],
    }
    return {name: json.dumps([conversation], ensure_ascii=False).encode("utf-8")
            for name, conversation in zip(MEMBERS, records, strict=True)}


def manifest_for(members: dict[str, bytes]) -> dict[str, Any]:
    return {
        "version": 1,
        "logical_files": {"conversations.json": {
            "files": list(members), "sharded": True, "shard_count": len(members),
        }},
        "export_files": [{"path": name, "size_bytes": len(data)}
                         for name, data in members.items()],
    }


def write_zip(path: Path, members: dict[str, bytes],
              manifest: dict[str, Any] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        # ZIP 顺序与编号相反，验证来源关系不依赖物理成员顺序。
        for name, data in reversed(list(members.items())):
            archive.writestr(name, data)
        if manifest is not None:
            archive.writestr("export_manifest.json", json.dumps(manifest))
        archive.writestr("user.json", b'{"email":"synthetic@example.invalid"}')
        archive.writestr("file_synthetic.dat", b"synthetic media bytes")
    return path


def sample_zip(path: Path) -> Path:
    members = sharded_members()
    return write_zip(path, members, manifest_for(members))


def rows(root: Path, sql: str) -> list[tuple[Any, ...]]:
    return list(query(root / "vault" / "silver", SourceRegistry(root).partitions(), sql).rows)


def fingerprint(root: Path) -> dict[str, tuple[str, int, int]]:
    return {str(path.relative_to(root)): (
        sha256_file(path), path.stat().st_mode, path.stat().st_mtime_ns,
    ) for path in root.rglob("*") if path.is_file()}


def test_sharded_import_preserves_branches_text_times_and_exact_evidence(tmp_path: Path) -> None:
    source = sample_zip(tmp_path / "synthetic-sharded.zip")
    root = tmp_path / "data"
    original_hash = sha256_file(source)
    result = ingest_file(source, root, SOURCE)
    assert (result.events, result.artifacts, result.evidence) == (2, 5, 7)
    assert result.content_hash == original_hash and sha256_file(source) == original_hash
    parent = record_id(SOURCE, source_record_id("artifact", "synthetic-conversation-1",
                                               "synthetic-message-1"))
    assert rows(root, f"SELECT count(*) FROM artifacts WHERE parent_record_id='{parent}'") == [(2,)]
    assert rows(root, "SELECT text_parts FROM artifacts WHERE content_format='multimodal_text'") == [
        (["  synthetic before\n", "synthetic after  "],)]
    assert rows(root, f"SELECT occurred_at, known_at FROM artifacts WHERE record_id='{parent}'") == [
        (datetime(2026, 1, 1, tzinfo=UTC), None)]
    assert rows(root, "SELECT count(*) FROM artifacts WHERE known_at IS NOT NULL") == [(0,)]
    assert rows(root, "SELECT raw_member, raw_pointer FROM evidence WHERE record_kind='event' "
                "ORDER BY raw_member") == [(MEMBERS[0], "/0"), (MEMBERS[1], "/0")]
    store = ObjectStore(root / "vault")
    evidence = rows(root, "SELECT content_hash, raw_member, raw_member_hash, raw_pointer, "
                    "source_record_id FROM evidence")
    for content_hash, member, member_hash, pointer, sid in evidence:
        with zipfile.ZipFile(store.object_path(content_hash)) as archive:
            data = archive.read(member)
        assert sha256_bytes(data) == member_hash
        value = json.loads(data)
        for token in pointer.lstrip("/").split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
        assert value["id"] == json.loads(sid)[-1]
    assert quality(root).quality == result.quality
    assert result.quality.messages.text_versions == 4
    assert result.quality.messages.unsupported_content_types == {"multimodal_text": 1}
    assert result.quality.messages.missing_known_at_versions == 5
    before = fingerprint(root)
    assert verify(root).status == "ok"
    assert fingerprint(root) == before


def test_sharded_ten_imports_and_rebuilds_preserve_every_persisted_file(tmp_path: Path) -> None:
    source = sample_zip(tmp_path / "synthetic.zip")
    root = tmp_path / "data"
    first = ingest_file(source, root, SOURCE)
    before = fingerprint(root)
    for _ in range(9):
        again = ingest_file(source, root, SOURCE)
        assert again.partition == first.partition and not again.created
        report = rebuild(root, SOURCE)
        assert report.status == "ok" and report.rebuilds[0].status == "unchanged"
    assert fingerprint(root) == before


def test_sharded_rebuild_restores_missing_derived_data_from_raw_alone(tmp_path: Path) -> None:
    source = sample_zip(tmp_path / "synthetic.zip")
    root = tmp_path / "data"
    ingest_file(source, root, SOURCE)
    tables = {name: rows(root, f"SELECT * FROM {name} ORDER BY ALL")
              for name in ("events", "artifacts", "evidence")}
    bronze = fingerprint(root / "vault")
    bronze = {name: value for name, value in bronze.items() if not name.startswith("silver/")}
    source.rename(tmp_path / "held-synthetic-inbox.zip")
    (root / "vault" / "silver").rename(tmp_path / "held-synthetic-silver")
    (root / "registry.sqlite").rename(tmp_path / "held-synthetic-registry.sqlite")
    assert rebuild(root, SOURCE).status == "ok"
    for name, expected in tables.items():
        assert rows(root, f"SELECT * FROM {name} ORDER BY ALL") == expected
    assert {name: value for name, value in fingerprint(root / "vault").items()
            if not name.startswith("silver/")} == bronze
    assert verify(root).status == "ok"


def test_numeric_fallback_without_manifest_is_deterministic(tmp_path: Path) -> None:
    members = sharded_members()
    source = write_zip(tmp_path / "synthetic.zip", members)
    result = ingest_file(source, tmp_path / "data", SOURCE)
    assert (result.events, result.artifacts) == (2, 5)
    assert any("manifest" in issue for issue in result.issues)
    assert verify(tmp_path / "data").status == "ok"


def test_legacy_single_member_with_manifest_remains_supported(tmp_path: Path) -> None:
    members = {"conversations.json": (FIXTURES / "export-a" / "conversations.json").read_bytes()}
    manifest = manifest_for(members)
    manifest["logical_files"]["conversations.json"]["sharded"] = False
    source = write_zip(tmp_path / "synthetic-legacy.zip", members, manifest)
    result = ingest_file(source, tmp_path / "data", SOURCE)
    assert (result.events, result.artifacts, result.evidence) == (2, 5, 7)
    assert verify(tmp_path / "data").status == "ok"


def test_manifest_order_preserves_member_local_pointers(tmp_path: Path) -> None:
    members = sharded_members()
    manifest = manifest_for(members)
    manifest["logical_files"]["conversations.json"]["files"].reverse()
    source = write_zip(tmp_path / "synthetic-reordered.zip", members, manifest)
    root = tmp_path / "data"
    ingest_file(source, root, SOURCE)
    assert rows(root, "SELECT raw_member, raw_pointer FROM evidence WHERE record_kind='event' "
                "ORDER BY raw_member") == [(MEMBERS[0], "/0"), (MEMBERS[1], "/0")]
    assert verify(root).status == "ok"


@pytest.mark.parametrize("problem", [
    "missing_shard", "wrong_count", "duplicate_reference", "extra_shard", "wrong_size",
    "unsafe_reference", "wrong_sharded_flag", "duplicate_inventory", "bad_inventory_size",
    "bad_manifest_shape", "mixed_layout", "duplicate_conversation", "numeric_gap",
    "duplicate_index", "malformed_json", "duplicate_json_key",
])
def test_invalid_sharded_input_keeps_raw_and_publishes_no_partition(
    tmp_path: Path, problem: str,
) -> None:
    members = sharded_members()
    manifest = manifest_for(members)
    entry = manifest["logical_files"]["conversations.json"]
    if problem == "missing_shard":
        members.pop(MEMBERS[1])
    elif problem == "wrong_count":
        entry["shard_count"] = 3
    elif problem == "duplicate_reference":
        entry["files"] = [MEMBERS[0], MEMBERS[0]]
    elif problem == "extra_shard":
        members["conversations-002.json"] = b"[]"
    elif problem == "wrong_size":
        manifest["export_files"][0]["size_bytes"] = 1
    elif problem == "unsafe_reference":
        entry["files"][1] = "../conversations-001.json"
    elif problem == "wrong_sharded_flag":
        entry["sharded"] = False
    elif problem == "duplicate_inventory":
        manifest["export_files"].append(manifest["export_files"][0])
    elif problem == "bad_inventory_size":
        manifest["export_files"][0]["size_bytes"] = True
    elif problem == "bad_manifest_shape":
        manifest["logical_files"] = []
    elif problem == "mixed_layout":
        members["conversations.json"] = b"[]"
    elif problem == "duplicate_conversation":
        members[MEMBERS[1]] = members[MEMBERS[0]]
        manifest = manifest_for(members)
    elif problem == "numeric_gap":
        members["conversations-002.json"] = members.pop(MEMBERS[1])
        manifest = None
    elif problem == "duplicate_index":
        members["conversations-0.json"] = b"[]"
        manifest = None
    elif problem == "malformed_json":
        members[MEMBERS[1]] = b"["
        manifest = manifest_for(members)
    elif problem == "duplicate_json_key":
        members[MEMBERS[1]] = b'[{"id":"synthetic-a","id":"synthetic-b"}]'
        manifest = manifest_for(members)
    source = write_zip(tmp_path / "synthetic-invalid.zip", members, manifest)
    root = tmp_path / "data"
    with pytest.raises(ExportError):
        ingest_file(source, root, SOURCE)
    assert ObjectStore(root / "vault").read(sha256_file(source)) == source.read_bytes()
    assert SourceRegistry(root).partitions() == []
    assert verify(root).status == "ok"


@pytest.mark.parametrize("member", [MEMBERS[0], "export_manifest.json"])
def test_duplicate_selected_zip_member_is_rejected(tmp_path: Path, member: str) -> None:
    source = sample_zip(tmp_path / "synthetic.zip")
    with zipfile.ZipFile(source, "a") as archive, pytest.warns(UserWarning, match="Duplicate name"):
        archive.writestr(member, b"[]")
    with pytest.raises(ExportError, match="唯一"):
        ChatGPTCollector(SOURCE).ingest(str(source))


@pytest.mark.parametrize("problem", ["cycle", "missing_parent", "contradictory_children"])
def test_parent_only_tree_still_rejects_broken_relationships(tmp_path: Path, problem: str) -> None:
    members = sharded_members()
    records = json.loads(members[MEMBERS[0]])
    mapping = records[0]["mapping"]
    if problem == "cycle":
        mapping["node-1-user"]["parent"] = "node-1-assistant-a"
    elif problem == "missing_parent":
        mapping["node-1-user"]["parent"] = "synthetic-missing"
    else:
        mapping["node-1-user"]["children"] = ["node-1-assistant-a"]
    members[MEMBERS[0]] = json.dumps(records).encode("utf-8")
    source = write_zip(tmp_path / "synthetic.zip", members, manifest_for(members))
    with pytest.raises(ExportError):
        ingest_file(source, tmp_path / "data", SOURCE)


@pytest.mark.parametrize("parts, expected", [
    ([{"synthetic_image": "placeholder"}], None),
    (["", "  "], ("", "  ")),
    (["before", {"synthetic_audio": "placeholder"}, "after"], ("before", "after")),
])
def test_multimodal_strings_are_preserved_without_serializing_objects(
    tmp_path: Path, parts: list[Any], expected: tuple[str, ...] | None,
) -> None:
    members = sharded_members()
    records = json.loads(members[MEMBERS[0]])
    records[0]["mapping"]["node-1-user"]["message"]["content"]["parts"] = parts
    members[MEMBERS[0]] = json.dumps(records).encode("utf-8")
    source = write_zip(tmp_path / "synthetic.zip", members, manifest_for(members))
    collector = ChatGPTCollector(SOURCE)
    records = collector.normalize(collector.ingest(str(source)))
    mixed = next(a for a in records.artifacts if a.content_format == "multimodal_text")
    assert mixed.text_parts == expected


@pytest.mark.parametrize("parts", [None, "synthetic text", [123], [True]])
def test_malformed_multimodal_parts_are_not_silently_coerced(tmp_path: Path, parts: Any) -> None:
    members = sharded_members()
    records = json.loads(members[MEMBERS[0]])
    records[0]["mapping"]["node-1-user"]["message"]["content"]["parts"] = parts
    members[MEMBERS[0]] = json.dumps(records).encode("utf-8")
    source = write_zip(tmp_path / "synthetic.zip", members, manifest_for(members))
    root = tmp_path / "data"
    with pytest.raises(ExportError, match="parts"):
        ingest_file(source, root, SOURCE)
    assert SourceRegistry(root).partitions() == []
    assert ObjectStore(root / "vault").read(sha256_file(source)) == source.read_bytes()


@pytest.mark.parametrize("problem", ["member", "combined", "manifest"])
def test_json_limits_cannot_be_bypassed_by_sharding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str,
) -> None:
    members = sharded_members()
    source = write_zip(tmp_path / "synthetic.zip", members, manifest_for(members))
    if problem == "manifest":
        monkeypatch.setattr("lifebase.sync.collectors.chatgpt.export.MAX_MANIFEST_BYTES", 2)
    else:
        limit = 2 if problem == "member" else max(map(len, members.values()))
        monkeypatch.setattr("lifebase.sync.collectors.chatgpt.export.MAX_JSON_BYTES", limit)
    with pytest.raises(ExportError, match="上限"):
        ChatGPTCollector(SOURCE).ingest(str(source))


@pytest.mark.parametrize("field", ["raw_member_hash", "raw_member"])
def test_verifier_detects_incorrect_cross_member_evidence(tmp_path: Path, field: str) -> None:
    root = tmp_path / "data"
    result = ingest_file(sample_zip(tmp_path / "synthetic.zip"), root, SOURCE)
    folder = root / "vault" / "silver" / result.partition
    path = folder / "evidence.parquet"
    table = pq.read_table(path)
    records = table.to_pylist()
    row = next(item for item in records if item["raw_member"] == MEMBERS[0])
    row[field] = "0" * 64 if field == "raw_member_hash" else MEMBERS[1]
    if field == "raw_member":
        row["raw_member_hash"] = sha256_bytes(sharded_members()[MEMBERS[1]])
    row["evidence_id"] = identity_hash([
        row["record_id"], row["revision_id"], row["content_hash"], row["raw_member"],
        row["raw_pointer"], row["collector_version"], row["parser_version"],
    ])
    pq.write_table(pa.Table.from_pylist(records, schema=table.schema), path)
    metadata_path = folder / "partition.json"
    metadata = json.loads(metadata_path.read_bytes())
    metadata["files"]["evidence"] = sha256_file(path)
    metadata_path.write_text(json.dumps(metadata))
    report = verify(root)
    expected = "evidence_member_hash_mismatch" if field == "raw_member_hash" else "evidence_locator_invalid"
    assert expected in {issue.code for issue in report.issues}


def test_cli_inbox_detects_shards_and_quality_keeps_partial_content_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "data"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    sample_zip(inbox / "synthetic.zip")
    assert run(["ingest", "--data-dir", str(root), "--source", SOURCE]) == 0
    result = json.loads(capsys.readouterr().out)["imports"][0]
    assert result["status"] == "imported"
    assert run(["quality", "--data-dir", str(root), "--source", SOURCE]) == 0
    report = json.loads(capsys.readouterr().out)["quality"]
    assert report == result["quality"] and report["status"] == "warning"
    assert "synthetic before" not in json.dumps(report)
    with sqlite3.connect(root / "registry.sqlite") as db:
        assert db.execute("SELECT count(*) FROM imports").fetchone() == (1,)
    assert asdict(verify(root))["status"] == "ok"
