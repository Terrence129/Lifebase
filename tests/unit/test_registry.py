"""来源注册表：source_type 解析、collector 实例化、自动识别与版本一致性。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lifebase.sync.base import EGRESS_POLICIES
from lifebase.sync.collectors import (
    COLLECTORS,
    detect_collector,
    make_collector,
    metadata_for,
    source_type,
)
from lifebase.sync.collectors.chatgpt import ChatGPTCollector

FIXTURES = Path(__file__).parents[1] / "fixtures" / "chatgpt"


def test_source_type_parses_account_prefix() -> None:
    assert source_type("chatgpt:personal") == "chatgpt"


def test_source_type_falls_back_to_single_registered_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(COLLECTORS, "doubao")
    assert source_type("account-a") == "chatgpt"
    assert source_type("other:personal") == "chatgpt"


def test_source_type_rejects_unknown_prefix_with_multiple_collectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(COLLECTORS, "dummy", ChatGPTCollector)
    with pytest.raises(ValueError, match="未知来源类型"):
        source_type("unknown:personal")


def test_make_collector_returns_registered_collector() -> None:
    collector = make_collector("chatgpt:personal")
    assert isinstance(collector, ChatGPTCollector)
    assert collector.source == "chatgpt:personal"


def test_make_collector_rejects_unknown_source_with_multiple_registered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(COLLECTORS, "dummy", ChatGPTCollector)
    with pytest.raises(ValueError, match="未知来源类型"):
        make_collector("unknown:personal")


def test_metadata_for_specific_and_single_default(monkeypatch: pytest.MonkeyPatch) -> None:
    meta = metadata_for("chatgpt:personal")
    assert meta["source_type"] == "chatgpt"
    assert meta["collector_version"].startswith("chatgpt@")
    monkeypatch.delitem(COLLECTORS, "doubao")
    assert metadata_for(None) == meta


def test_metadata_for_none_requires_single_collector(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(COLLECTORS, "dummy", ChatGPTCollector)
    with pytest.raises(ValueError, match="已登记多个"):
        metadata_for(None)


def test_detect_collector_matches_zip_and_skips_other(tmp_path: Path) -> None:
    assert detect_collector(str(FIXTURES / "export-a.zip")) == "chatgpt"
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("synthetic unrelated input")
    assert detect_collector(str(unrelated)) is None


def test_registered_collectors_have_consistent_version_prefix() -> None:
    for name, cls in COLLECTORS.items():
        meta = cls(f"{name}:check").metadata()
        assert meta["source_type"] == name
        assert meta["collector_version"].startswith(f"{name}@")


def test_registered_collectors_declare_egress_policy() -> None:
    """ADR-012：每个 collector 必须声明合法的来源默认外发策略。"""
    for name, cls in COLLECTORS.items():
        assert cls(f"{name}:check").metadata().get("egress_policy") in EGRESS_POLICIES, name


def test_chatgpt_defaults_to_local_only() -> None:
    assert metadata_for("chatgpt:personal")["egress_policy"] == "local_only"


def test_doubao_is_registered_and_defaults_to_local_only() -> None:
    assert source_type("doubao:personal") == "doubao"
    meta = metadata_for("doubao:personal")
    assert meta["source_type"] == "doubao" and meta["egress_policy"] == "local_only"


def test_archive_hint_cannot_conflict_with_registered_source_prefix() -> None:
    with pytest.raises(ValueError, match="冲突"):
        make_collector("chatgpt:personal", collector_version="doubao@0.1.0")
