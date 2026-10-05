"""质量统计是派生报告；合成输入验证内容缺口与跨导出版本语义。"""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
from pathlib import Path

import pytest

from lifebase.cli import run
from lifebase.core.hashing import sha256_file
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.quality import quality

FIXTURES = Path(__file__).parents[1] / "fixtures" / "chatgpt"
SOURCE = "chatgpt:synthetic-account"


def snapshot(root: Path) -> dict[str, tuple[int, int, str | None]]:
    return {str(path.relative_to(root)): (
        path.stat().st_mode, path.stat().st_mtime_ns,
        sha256_file(path) if path.is_file() else None,
    ) for path in [root, *root.rglob("*")]}


def export(path: Path, records: list[dict]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(records))
    return path


def test_import_report_agrees_with_dataset_statistics(tmp_path: Path) -> None:
    root = tmp_path / "data"
    imported = ingest_file(FIXTURES / "export-a.zip", root, SOURCE)
    report = quality(root)
    assert report.selected_partitions == 1 and report.quality == imported.quality
    assert asdict(imported.quality) == {
        "status": "warning", "conversations": {
            "identities": 2, "versions": 2, "missing_occurred_at_versions": 0,
            "missing_known_at_versions": 0,
        }, "messages": {
            "identities": 5, "versions": 5, "missing_occurred_at_versions": 1,
            "missing_known_at_versions": 1, "text_versions": 5, "empty_text_versions": 0,
            "unsupported_content_versions": 0, "unsupported_content_types": {},
        }, "evidence": 7,
    }


def test_overlap_counts_identities_versions_and_missing_times_after_dedup(tmp_path: Path) -> None:
    root = tmp_path / "data"
    for label in ("export-a", "export-b"):
        ingest_file(FIXTURES / f"{label}.zip", root, SOURCE)
    before = snapshot(root)
    report = quality(root)
    assert report.selected_partitions == 2
    assert report.quality.messages.identities == 6 and report.quality.messages.versions == 7
    assert report.quality.conversations.identities == 2 and report.quality.conversations.versions == 3
    assert report.quality.messages.missing_occurred_at_versions == 1
    assert report.quality.messages.missing_known_at_versions == 1
    assert report.quality.evidence == 15
    assert snapshot(root) == before
    for _ in range(3):
        assert not ingest_file(FIXTURES / "export-a.zip", root, SOURCE).created
        before_report = snapshot(root)
        assert quality(root) == report
        assert snapshot(root) == before_report
    # 归档自己的临时文件可能改变目录 mtime；持久化文件及统计仍保持一致。
    assert {name: item for name, item in snapshot(root).items() if item[2] is not None} == {
        name: item for name, item in before.items() if item[2] is not None}


def test_nontext_empty_text_and_invalid_time_are_counted_without_body_output(tmp_path: Path) -> None:
    records = json.loads((FIXTURES / "export-a" / "conversations.json").read_bytes())
    mapping = records[0]["mapping"]
    mapping["node-1-user"]["message"]["content"] = {
        "content_type": "multimodal_text", "parts": [{"synthetic_image": "body-marker-only-in-RAW"}],
    }
    mapping["node-1-assistant-a"]["message"]["content"] = {
        "content_type": "audio", "parts": [{"synthetic_audio": "body-marker-only-in-RAW"}],
    }
    mapping["node-1-assistant-b"]["message"]["content"]["parts"] = ["", ""]
    mapping["node-1-user"]["message"]["create_time"] = "synthetic invalid time"
    mapping["node-1-user"]["message"]["update_time"] = None
    root = tmp_path / "data"
    imported = ingest_file(export(tmp_path / "synthetic.zip", records), root, SOURCE)
    report = quality(root).quality
    assert report == imported.quality and report.status == "warning"
    assert report.messages.text_versions == 3 and report.messages.empty_text_versions == 1
    assert report.messages.unsupported_content_versions == 2
    assert report.messages.unsupported_content_types == {"audio": 1, "multimodal_text": 1}
    assert report.messages.missing_occurred_at_versions == 2
    assert report.messages.missing_known_at_versions == 2
    assert "body-marker-only-in-RAW" not in json.dumps(asdict(report))


def test_quality_filters_accounts_and_processing_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    for account in ("account-a", "account-b"):
        ingest_file(FIXTURES / "export-a.zip", root, account)
    monkeypatch.setattr("lifebase.sync.collectors.chatgpt.PARSER_VERSION", "chatgpt@0.1.1")
    ingest_file(FIXTURES / "export-a.zip", root, "account-a")
    assert quality(root).quality.messages.identities == 10
    both = quality(root, source="account-a")
    assert both.quality.messages.versions == 5 and both.quality.evidence == 14
    selected = quality(root, source="account-a", collector_version="chatgpt@0.1.0",
                       parser_version="chatgpt@0.1.1", schema_version=1)
    assert selected.selected_partitions == 1 and selected.quality.evidence == 7
    assert quality(root, schema_version=99).quality.status == "empty"


def test_empty_quality_does_not_create_files(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "absent"
    assert run(["quality", "--data-dir", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["quality"]["status"] == "empty" and report["selected_partitions"] == 0
    assert not root.exists()
    imported = ingest_file(export(tmp_path / "synthetic-empty.zip", []), root, SOURCE)
    assert imported.quality.status == "empty" and imported.quality == quality(root).quality


def test_cli_quality_warning_is_not_import_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "data"
    assert run(["ingest", "--data-dir", str(root), "--source", SOURCE,
                str(FIXTURES / "export-a.zip")]) == 0
    item = json.loads(capsys.readouterr().out)["imports"][0]
    assert item["status"] == "imported" and item["quality"]["status"] == "warning"
    assert run(["--data-dir", str(root), "quality", "--source", SOURCE,
                "--parser-version", "chatgpt@0.1.0", "--schema-version", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["quality"] == item["quality"]
    result = item["partition"]
    (root / "vault" / "silver" / result / "artifacts.parquet").write_bytes(b"synthetic damage")
    assert run(["quality", "--data-dir", str(root)]) == 1
    assert "哈希不一致" in capsys.readouterr().err
