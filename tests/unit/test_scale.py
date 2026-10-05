"""小规模验证基准工具正确性；CI 不执行完整基准或断言运行时间。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from lifebase.core.hashing import sha256_file
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.quality import quality
from lifebase.sync.verification import verify

REPO = Path(__file__).resolve().parents[2]


def generate_case(root: Path, messages: int, body_chars: int = 256) -> dict:
    completed = subprocess.run([
        sys.executable, "-m", "benchmarks.run", "--worker", "generate", "--exports", str(root),
        "--messages", str(messages), "--body-chars", str(body_chars),
    ], cwd=REPO, capture_output=True, text=True, check=True, timeout=60)
    return json.loads(completed.stdout)


@pytest.mark.parametrize("messages", [200, 2000])
def test_generated_scale_case_has_expected_quality_and_evidence(tmp_path: Path, messages: int) -> None:
    exports = tmp_path / "exports"
    spec = generate_case(exports, messages, body_chars=32)
    root = tmp_path / "data"
    for label in ("export-a", "export-b"):
        ingest_file(exports / f"{label}.zip", root, "chatgpt:synthetic-scale")
    report = quality(root).quality
    assert report.messages.identities == spec["logical_messages"]
    assert report.messages.versions == spec["message_versions"]
    assert report.conversations.identities == spec["conversations"]
    assert report.evidence == spec["evidence"] and report.status == "warning"
    assert report.messages.missing_occurred_at_versions == spec["logical_messages"] // 20 + messages // 2020
    assert report.messages.missing_known_at_versions == spec["logical_messages"] // 10
    assert report.messages.unsupported_content_versions == spec["logical_messages"] // 25 + messages // 2525
    assert verify(root).status == "ok"


def test_scale_generation_is_deterministic_and_refuses_overwrite(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    assert generate_case(a, 101) == generate_case(b, 101)
    assert {path.name: sha256_file(path) for path in a.iterdir()} == {
        path.name: sha256_file(path) for path in b.iterdir()}
    with pytest.raises(subprocess.CalledProcessError):
        generate_case(a, 101)


def test_benchmark_smoke_reports_separate_phase_measurements(tmp_path: Path) -> None:
    output = tmp_path / "baseline.json"
    subprocess.run([sys.executable, "-m", "benchmarks.run", "--sizes", "20", "--repeats", "1",
                    "--body-chars", "32", "--output", str(output)],
                   cwd=REPO, capture_output=True, text=True, check=True, timeout=60)
    report = json.loads(output.read_bytes())
    assert report["dataset"] == "synthetic only"
    case = report["cases"][0]
    assert case["input"]["logical_messages"] == 21
    assert set(case["summary"]) == {"ingest", "repeat_ingest", "query", "quality"}
    for phase in case["summary"].values():
        assert phase["median_elapsed_seconds"] >= 0
        assert phase["max_peak_rss_mib"] is None or phase["max_peak_rss_mib"] > 0
