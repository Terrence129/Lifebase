"""独立私有数据仓库的路径授权与无损迁移验收；全部使用合成输入。"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from lifebase.core.hashing import sha256_file
from lifebase.core.paths import data_path
from lifebase.graph import build_graph, graph_status
from lifebase.humanos import HumanOS
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.verification import verify

FIXTURES = Path(__file__).parents[1] / "fixtures"


def private_repository(tmp_path: Path) -> Path:
    root = tmp_path / "Lifebase-data"
    (root / ".git").mkdir(parents=True)
    (root / ".git/config").write_text(
        '[remote "origin"]\n\turl = git@github.com:synthetic/Lifebase-data.git\n',
        encoding="utf-8")
    (root / ".lifebase-data.json").write_text(json.dumps({
        "schema_version": 1, "purpose": "lifebase-private-data", "visibility": "private",
        "repository": "synthetic/Lifebase-data",
        "libraries": {"personal": "libraries/personal", "demo": "libraries/demo"},
    }), encoding="utf-8")
    return root


def fingerprint(root: Path) -> dict[str, tuple[str, int, int]]:
    return {str(path.relative_to(root)): (sha256_file(path), path.stat().st_mtime_ns,
                                        stat.S_IMODE(path.stat().st_mode))
            for path in root.rglob("*") if path.is_file()}


def test_opt_in_only_allows_registered_library_roots(tmp_path: Path) -> None:
    root = private_repository(tmp_path)
    before = fingerprint(root)
    assert data_path(root / "libraries/personal") == root / "libraries/personal"
    assert data_path(root / "libraries/demo") == root / "libraries/demo"
    for path in (root, root / "exports/chatgpt", root / "libraries/other",
                 root / "libraries/personal/vault"):
        with pytest.raises(ValueError, match="Git 工作树"):
            data_path(path)
    assert fingerprint(root) == before


@pytest.mark.parametrize("change", [
    {"visibility": "public"}, {"purpose": "other"}, {"schema_version": True},
    {"schema_version": 2}, {"repository": "synthetic/other"},
    {"libraries": {"personal": "../personal"}},
    {"libraries": {"personal": "/libraries/personal"}},
    {"libraries": {"personal": "libraries/../personal"}}, {"libraries": {}},
])
def test_invalid_opt_in_is_rejected(tmp_path: Path, change: dict[str, Any]) -> None:
    root = private_repository(tmp_path)
    marker = root / ".lifebase-data.json"
    value = json.loads(marker.read_text()) | change
    marker.write_text(json.dumps(value))
    before = fingerprint(root)
    with pytest.raises(ValueError, match="Git 工作树"):
        data_path(root / "libraries/personal")
    assert fingerprint(root) == before


def test_missing_malformed_or_symlinked_marker_is_rejected(tmp_path: Path) -> None:
    root = private_repository(tmp_path)
    marker = root / ".lifebase-data.json"
    original = marker.read_bytes()
    marker.unlink()
    with pytest.raises(ValueError, match="Git 工作树"):
        data_path(root / "libraries/personal")
    marker.write_bytes(b"malformed synthetic marker")
    with pytest.raises(ValueError, match="Git 工作树"):
        data_path(root / "libraries/personal")
    marker.unlink()
    target = tmp_path / "marker.json"
    target.write_bytes(original)
    marker.symlink_to(target)
    with pytest.raises(ValueError, match="Git 工作树"):
        data_path(root / "libraries/personal")


def test_nested_git_repository_is_still_rejected(tmp_path: Path) -> None:
    root = private_repository(tmp_path)
    library = root / "libraries/personal"
    (library / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="Git 工作树"):
        data_path(library)


def test_relocated_library_and_legacy_alias_preserve_data(tmp_path: Path) -> None:
    original = tmp_path / "Lifebase"
    ingest_file(FIXTURES / "chatgpt/export-a.zip", original, "chatgpt:synthetic-account")
    ingest_file(FIXTURES / "doubao/export-a.json", original, "doubao:synthetic-account")
    first = build_graph(original)
    before = fingerprint(original)
    repository = private_repository(tmp_path)
    destination = repository / "libraries/personal"
    destination.parent.mkdir()
    original.rename(destination)
    original.symlink_to(destination, target_is_directory=True)
    assert data_path(original) == destination
    assert fingerprint(destination) == before
    assert verify(destination).status == "ok"
    assert graph_status(original).snapshot_id == first.snapshot_id
    with HumanOS(original) as service:
        result = service.context("野餐有哪些讨论？")
        assert {match["source"] for match in result.data["matches"]} == {
            "chatgpt:synthetic-account", "doubao:synthetic-account"}
    assert not ingest_file(FIXTURES / "chatgpt/export-a.zip", destination,
                           "chatgpt:synthetic-account").created
    assert fingerprint(destination) == before
