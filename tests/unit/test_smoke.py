"""骨架冒烟测试：验证包安装、核心契约与不可变性。

Weekend Prototype 的起点 —— 从此 CI 有真实测试可跑。
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

import lifebase
from lifebase.core.envelope import Envelope


def test_package_importable() -> None:
    """src layout 安装正确，包可导入。"""
    assert lifebase.__version__ == "0.0.1"


def test_envelope_temporal_fields() -> None:
    """occurred_at / known_at 分离是 Past Me 正确性的根基。"""
    envelope = Envelope(
        source="chatgpt",
        source_record_id="conv-1",
        content_hash="abc123",
        collector_version="chatgpt@0.1.0",
        parser_version="chatgpt@0.1.0",
        occurred_at=datetime(2022, 1, 1, tzinfo=UTC),
        known_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert envelope.known_at > envelope.occurred_at


def test_envelope_is_immutable() -> None:
    """Envelope 是 frozen dataclass —— RAW 契约不可篡改。"""
    envelope = Envelope(
        source="x",
        source_record_id="1",
        content_hash="h",
        collector_version="v",
        parser_version="v",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        envelope.source = "y"  # type: ignore[misc]
