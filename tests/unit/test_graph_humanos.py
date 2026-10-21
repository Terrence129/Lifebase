"""双来源图谱、只读工具、策略与 JSON CLI 的合成端到端验收。"""

from __future__ import annotations

import json
import stat
import zipfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lifebase.cli import run
from lifebase.core.hashing import sha256_file
from lifebase.core.records import canonical_json
from lifebase.graph import GraphError, build_graph, graph_status, load_graph
from lifebase.graph.build import build_tables
from lifebase.graph.inputs import CanonicalData
from lifebase.humanos import HumanOS, ToolError, policy
from lifebase.humanos.policy import SYNTHETIC_RAW_HASHES, enforce_destination
from lifebase.humanos.service import parse_time
from lifebase.sync.collectors import COLLECTORS
from lifebase.sync.collectors.chatgpt import ChatGPTCollector
from lifebase.sync.collectors.doubao import DoubaoCollector
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.verification import verify
from lifebase.vault.store import ObjectStore

FIXTURES = Path(__file__).parents[1] / "fixtures"
CHATGPT = "chatgpt:synthetic-account"
DOUBAO = "doubao:synthetic-account"


def fingerprint(root: Path) -> dict[str, tuple[str, int, int]]:
    return {str(path.relative_to(root)): (sha256_file(path), path.stat().st_mtime_ns,
                                        stat.S_IMODE(path.stat().st_mode))
            for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def mixed(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    ingest_file(FIXTURES / "chatgpt/export-a.zip", root, CHATGPT)
    ingest_file(FIXTURES / "doubao/export-a.json", root, DOUBAO)
    return root


def variant(tmp_path: Path, change: Any) -> Path:
    value = json.loads((FIXTURES / "chatgpt/export-a/conversations.json").read_text())
    change(value)
    path = tmp_path / "synthetic-variant.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(value, ensure_ascii=False))
    return path


def test_graph_cross_source_paths_exact_evidence_and_idempotency(mixed: Path) -> None:
    original = fingerprint(mixed)
    first = build_graph(mixed)
    assert first.created and first.counts["sources"] == 2
    assert first.counts["conversations"] == 3 and first.counts["messages"] == 8
    assert first.counts["mentions"] <= 8 * 5
    for key, value in original.items():
        assert fingerprint(mixed)[key] == value
    before = fingerprint(mixed)
    second = build_graph(mixed)
    assert not second.created and second.snapshot_id == first.snapshot_id
    assert fingerprint(mixed) == before
    assert graph_status(mixed).status == "ok"
    with HumanOS(mixed) as service:
        assert "野餐" in {row["term"] for row in service.topics(limit=100).data["topics"]}
        result = service.search("野餐")
        assert {match["source"] for match in result.data["matches"]} == {CHATGPT, DOUBAO}
        for match in result.data["matches"]:
            assert match["graph_path"]["topic_node_ids"]
            for locator in match["evidence"]:
                assert service.evidence(locator["evidence_id"]).data["evidence"] == locator
                raw = ObjectStore(mixed / "vault").verify(locator["content_hash"])
                if locator["raw_member"]:
                    with zipfile.ZipFile(raw) as archive:
                        value = json.loads(archive.read(locator["raw_member"]))
                else:
                    value = json.loads(raw.read_bytes())
                for token in locator["raw_pointer"].lstrip("/").split("/"):
                    token = token.replace("~1", "/").replace("~0", "~")
                    value = value[int(token)] if isinstance(value, list) else value[token]
                assert match["excerpt"].strip() in "\n".join(
                    value["content"]["parts"] if locator["raw_member"] else [value["text"]]).strip()
    assert fingerprint(mixed) == before
    assert verify(mixed).status == "ok"


def test_input_iteration_does_not_change_graph_identity_or_weights(mixed: Path) -> None:
    build_graph(mixed)
    snapshot = load_graph(mixed)
    data = CanonicalData.from_tables(snapshot.silver, snapshot.inputs)
    data.events.reverse()
    data.messages.reverse()
    rebuilt = build_tables(data, snapshot.inputs, 5)
    assert all(rebuilt[name].equals(table) for name, table in snapshot.tables.items())


def test_missing_graph_and_empty_graph_queries_do_not_create_data(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    assert graph_status(root).status == "missing"
    with pytest.raises(GraphError, match="尚未构图"):
        HumanOS(root)
    assert not root.exists()
    assert build_graph(root).counts["messages"] == 0
    before = fingerprint(root)
    with HumanOS(root) as service:
        assert service.search("野餐").status == "empty"
        assert service.context("野餐").data["generated_answer"] is None
        assert service.topics().status == "empty"
    assert fingerprint(root) == before


def test_stale_graph_requires_explicit_build_and_preserves_old_snapshot(mixed: Path) -> None:
    first = build_graph(mixed)
    old = fingerprint(mixed / "vault/gold")
    ingest_file(FIXTURES / "chatgpt/export-b.zip", mixed, CHATGPT)
    assert graph_status(mixed).status == "stale"
    with pytest.raises(GraphError, match="重新|graph build"):
        HumanOS(mixed)
    assert fingerprint(mixed / "vault/gold") == old
    second = build_graph(mixed)
    assert second.snapshot_id != first.snapshot_id
    assert graph_status(mixed).status == "ok"
    for key, value in old.items():
        if key != "current.json":
            assert fingerprint(mixed / "vault/gold")[key] == value


def test_failed_build_keeps_current_snapshot(mixed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build_graph(mixed)
    before = fingerprint(mixed)
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
            build_graph(mixed, 6)
    assert fingerprint(mixed) == before
    assert graph_status(mixed).status == "ok"


@pytest.mark.parametrize("file", ["nodes.parquet", "edges.parquet", "snapshot.json"])
def test_corrupt_graph_is_rejected(mixed: Path, file: str) -> None:
    report = build_graph(mixed)
    path = mixed / "vault/gold" / report.snapshot_id / file
    path.write_bytes(b"synthetic-corruption")
    before = fingerprint(mixed)
    assert graph_status(mixed).status == "error"
    with pytest.raises(GraphError):
        HumanOS(mixed)
    assert fingerprint(mixed) == before


def test_evidence_reference_checked_even_with_updated_file_hash(mixed: Path) -> None:
    report = build_graph(mixed)
    folder = mixed / "vault/gold" / report.snapshot_id
    table = pq.ParquetFile(folder / "edges.parquet").read()
    rows = table.to_pylist()
    next(row for row in rows if row["kind"] == "mentions")["evidence_ids"] = ["synthetic-missing"]
    pq.write_table(pa.Table.from_pylist(rows, schema=table.schema), folder / "edges.parquet")
    path = folder / "snapshot.json"
    metadata = json.loads(path.read_text())
    metadata["files"]["edges"] = sha256_file(folder / "edges.parquet")
    path.write_bytes(canonical_json(metadata))
    assert graph_status(mixed).status == "error"


def test_symlinked_gold_or_silver_is_rejected(mixed: Path, tmp_path: Path) -> None:
    build_graph(mixed)
    path = mixed / "vault/gold/current.json"
    target = tmp_path / "synthetic-pointer.json"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    assert graph_status(mixed).status == "error"
    with pytest.raises(ValueError, match="符号链接"):
        HumanOS(mixed)


def test_context_balances_sources_and_enforces_content_bounds(mixed: Path) -> None:
    build_graph(mixed)
    before = fingerprint(mixed)
    with HumanOS(mixed) as service:
        context = service.context("我在两个平台讨论过野餐的哪些安排？", limit=2)
        assert len(context.data["matches"]) == 2
        assert {match["source"] for match in context.data["matches"]} == {CHATGPT, DOUBAO}
        assert context.data["generated_answer"] is None
        assert context.data["content_chars"] <= 600
        assert all(len(match["excerpt"]) <= 300 for match in context.data["matches"])
        assert "RESULTS_TRUNCATED" in {warning.code for warning in context.warnings}
        assert service.search("synthetic-unmatched-topic").status == "empty"
        assert service.evidence("synthetic-unmatched-evidence").status == "empty"
    assert fingerprint(mixed) == before


def test_unknown_times_and_half_open_utc_filters(mixed: Path) -> None:
    build_graph(mixed)
    with HumanOS(mixed) as service:
        conv = next(row["record_id"] for row in service._data.events
                    if row["title"] == "合成示例：回忆与时间缺失")
        all_messages = service.timeline(conv).data["matches"]
        assert len(all_messages) == 2 and all_messages[-1]["occurred_at"] is None
        result = service.timeline(conv, since=parse_time("2026-01-02"), until=parse_time("2026-01-03"))
        assert len(result.data["matches"]) == 1
        assert result.warnings[0].code == "UNKNOWN_TIME_EXCLUDED" and result.warnings[0].count == 1
        assert service.timeline(conv, until=parse_time("2026-01-02")).status == "empty"
        assert parse_time("2026-01-02T08:00:00+08:00") == datetime(2026, 1, 2, tzinfo=UTC)


def test_empty_text_assistant_only_and_excerpt_truncation(tmp_path: Path) -> None:
    def change(value: list[dict[str, Any]]) -> None:
        mapping = value[0]["mapping"]
        mapping["node-1-user"]["message"]["content"]["parts"] = []
        mapping["node-1-assistant-a"]["message"]["content"]["parts"] = ["野餐 " + "用品清单 " * 200]
    root = tmp_path / "data"
    ingest_file(variant(tmp_path, change), root, CHATGPT)
    report = build_graph(root)
    assert report.counts["messages"] == 5
    with HumanOS(root) as service:
        result = service.context("野餐")
        assert {match["role"] for match in result.data["matches"]} == {"assistant"}
        assert {warning.code for warning in result.warnings} >= {"NO_USER_STATEMENT", "EXCERPT_TRUNCATED"}
        assert all(len(match["excerpt"]) <= 300 for match in result.data["matches"])
        assert any(match["truncated"] for match in result.data["matches"])


def test_versions_and_conflicts_are_preserved(mixed: Path, tmp_path: Path) -> None:
    def change(value: list[dict[str, Any]]) -> None:
        message = value[0]["mapping"]["node-1-assistant-a"]["message"]
        message["content"]["parts"] = ["野餐也可以准备另一份合成清单。"]
        message["update_time"] = None
    ingest_file(variant(tmp_path, change), mixed, CHATGPT)
    build_graph(mixed)
    with HumanOS(mixed) as service:
        result = service.search("野餐", limit=100)
        conflicts = [match for match in result.data["matches"] if match["version_conflict"]]
        assert len(conflicts) == 2 and len({match["revision_id"] for match in conflicts}) == 2
        assert len({match["record_id"] for match in conflicts}) == 1
        assert any(match["known_at"] is None for match in conflicts)
        assert "VERSION_CONFLICT" in {warning.code for warning in result.warnings}


@pytest.mark.parametrize("limit", [0, 101, True])
def test_invalid_query_limits(mixed: Path, limit: int) -> None:
    build_graph(mixed)
    with HumanOS(mixed) as service, pytest.raises(ToolError, match="limit"):
        service.search("野餐", limit=limit)


def test_invalid_queries_and_literal_sql_input(mixed: Path) -> None:
    build_graph(mixed)
    with HumanOS(mixed) as service:
        for method, kwargs in ((service.context, {"limit": 11}),
                               (service.search, {"source": "synthetic-missing"}),
                               (service.search, {"since": datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)}),
                               (service.search, {"since": parse_time("2026-01-02"),
                                                 "until": parse_time("2026-01-01")})):
            with pytest.raises(ToolError):
                method("野餐", **kwargs)
        with pytest.raises(ToolError):
            service.search(" ")
        # 引号等字符是文本参数，不改变 SQL 结构或读取外部文件。
        service.search("野餐'; DROP TABLE artifacts; --")
        assert service.search("野餐").status == "ok"
        assert service.timeline("' OR TRUE --").status == "empty"
    with pytest.raises(ToolError):
        parse_time("2026-01-02T08:00:00")
    for keyword_count in (0, 51, True, 5.5):
        with pytest.raises(GraphError):
            build_graph(mixed, keyword_count)


def restrict(monkeypatch: pytest.MonkeyPatch, collector: Any, level: str = "local_only") -> None:
    original = collector.metadata
    monkeypatch.setattr(collector, "metadata", lambda self: original(self) | {"egress_policy": level})


def test_destination_policy_and_filtered_cloud_request(mixed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build_graph(mixed)
    monkeypatch.setattr(policy, "SYNTHETIC_RAW_HASHES", {})
    # ADR-021：聊天来源默认 cloud_ok，云端目的地直接可用。
    with HumanOS(mixed, "cloud") as service:
        assert service.context("野餐", source=CHATGPT).status == "ok"
    # 任一来源降为 local_only，整份快照即拒绝云端；来源筛选不能绕过。
    with monkeypatch.context() as patch:
        restrict(patch, ChatGPTCollector)
        with pytest.raises(ToolError, match="受限来源"):
            HumanOS(mixed, "cloud")
    original_doubao = DoubaoCollector.metadata
    monkeypatch.setattr(DoubaoCollector, "metadata", lambda self: original_doubao(self) | {"egress_policy": "redact_before_cloud"})
    with pytest.raises(ToolError):
        HumanOS(mixed, "cloud")
    with pytest.raises(ToolError):
        enforce_destination({"synthetic": "unknown"}, "local")
    with pytest.raises(ToolError):
        enforce_destination({}, "unknown")


def test_legacy_source_uses_registered_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "data"
    with monkeypatch.context() as patch:
        patch.delitem(COLLECTORS, "doubao")
        ingest_file(FIXTURES / "chatgpt/export-a.zip", root, "synthetic-legacy-account")
    ingest_file(FIXTURES / "doubao/export-a.json", root, DOUBAO)
    build_graph(root)
    with HumanOS(root) as service:
        assert service.search("野餐", source="synthetic-legacy-account").status == "ok"
    monkeypatch.setattr(policy, "SYNTHETIC_RAW_HASHES", {})
    # 未加类型前缀的历史来源同样解析到已登记类型，云端目的地可用。
    with HumanOS(root, "cloud") as service:
        assert service.search("野餐", source="synthetic-legacy-account").status == "ok"


def test_synthetic_allowlist_matches_fixture_files() -> None:
    assert {sha256_file(FIXTURES / path): path for path in SYNTHETIC_RAW_HASHES.values()} \
        == SYNTHETIC_RAW_HASHES


def test_cloud_allowed_only_when_every_raw_input_is_synthetic_fixture(
        mixed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 来源策略为 local_only 时，合成 fixture 白名单仍是唯一的云端放行通道。
    restrict(monkeypatch, ChatGPTCollector)
    restrict(monkeypatch, DoubaoCollector)
    build_graph(mixed)
    with HumanOS(mixed, "cloud") as service:
        assert service.context("野餐").status == "ok"
    ingest_file(variant(tmp_path, lambda value: value[0].update(title="合成变体")), mixed,
                "chatgpt:synthetic-variant")
    build_graph(mixed)
    with pytest.raises(ToolError) as caught:
        HumanOS(mixed, "cloud")
    assert caught.value.code == "EGRESS_BLOCKED"
    with HumanOS(mixed) as service:
        assert service.context("野餐", source=DOUBAO).status == "ok"
    with pytest.raises(ToolError):
        enforce_destination({DOUBAO: "doubao"}, "cloud", ())


def test_tools_do_not_read_raw(mixed: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    build_graph(mixed)
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("HumanOS must not read RAW")
    monkeypatch.setattr(ObjectStore, "verify", forbidden)
    monkeypatch.setattr(ObjectStore, "read", forbidden)
    with HumanOS(mixed) as service:
        result = service.search("野餐")
        eid = result.data["matches"][0]["evidence"][0]["evidence_id"]
        assert service.evidence(eid).status == "ok"


def test_json_cli_contract_readable_output_and_errors(mixed: Path, capsys: pytest.CaptureFixture[str],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    def call(*args: str) -> tuple[int, dict[str, Any]]:
        code = run(["--data-dir", str(mixed), *args, "--format", "json"])
        output = capsys.readouterr()
        assert not output.err
        return code, json.loads(output.out)
    code, value = call("graph", "build")
    assert code == 0 and value["api_version"] == 1 and value["data"]["counts"]["messages"] == 8
    before = fingerprint(mixed)
    for args in (("graph", "status"), ("topics",), ("search", "野餐"), ("context", "野餐")):
        code, value = call(*args)
        assert code == 0 and value["api_version"] == 1 and value["status"] == "ok"
    match = value["data"]["matches"][0]
    for args in (("timeline", "--conversation", match["conversation_id"]),
                 ("evidence", match["evidence"][0]["evidence_id"])):
        assert call(*args)[0] == 0
    monkeypatch.setattr(policy, "SYNTHETIC_RAW_HASHES", {})
    restrict(monkeypatch, DoubaoCollector)
    code, value = call("context", "野餐", "--destination", "cloud", "--source", CHATGPT)
    assert code == 1 and value["error"]["code"] == "EGRESS_BLOCKED"
    assert "matches" not in value["data"]
    assert call("search", "野餐", "--limit", "0")[1]["error"]["code"] == "INVALID_REQUEST"
    assert run(["search", "野餐", "--data-dir", str(mixed)]) == 0
    assert "图谱路径" in capsys.readouterr().out
    assert fingerprint(mixed) == before
    assert asdict(graph_status(mixed))["status"] == "ok"


def test_published_contract_and_example_match_cli(mixed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = Path(__file__).parents[2]
    schema = json.loads((root / "schemas/humanos-api-v1.json").read_text())
    sample = json.loads((root / "docs/examples/harness-context-v1.json").read_text())
    build_graph(mixed)
    assert run(["context", "野餐有哪些讨论？", "--data-dir", str(mixed), "--format", "json"]) == 0
    actual = json.loads(capsys.readouterr().out)
    for response in (sample, actual):
        assert set(schema["required"]) <= response.keys()
        assert response["api_version"] == 1 and response["tool"] == "context"
        assert response["data"]["generated_answer"] is None
        assert response["data"]["content_chars"] <= 3000
        assert len(response["data"]["matches"]) <= 10
        assert {match["source"] for match in response["data"]["matches"]} == {CHATGPT, DOUBAO}
        for match in response["data"]["matches"]:
            assert set(schema["$defs"]["message"]["required"]) <= match.keys()
            assert len(match["excerpt"]) <= 300
            for locator in match["evidence"]:
                assert set(schema["$defs"]["evidence"]["required"]) <= locator.keys()
    # 文件里的示例与真正 CLI 在消息身份、片段、角色及证据定位上相同；快照身份可不同。
    # DuckDB 按宿主时区渲染时间，示例与 CLI 的偏移可能不同，比较时统一换算到 UTC。
    assert _instants_in_utc(actual["data"]) == _instants_in_utc(sample["data"])


def _instants_in_utc(data: dict[str, Any]) -> dict[str, Any]:
    matches = [{**match, **{key: datetime.fromisoformat(match[key]).astimezone(UTC)
                            for key in ("occurred_at", "known_at") if match[key] is not None}}
               for match in data["matches"]]
    return {**data, "matches": matches}
