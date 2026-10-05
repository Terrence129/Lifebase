"""RAW 归档的完整性、幂等性与并发发布保护；仅使用合成字节。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from lifebase.core.hashing import sha256_bytes
from lifebase.vault.manifest import ArchiveManifest
from lifebase.vault.store import IntegrityError, ObjectStore


def test_archive_roundtrip_and_idempotency(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.zip"
    original = b"synthetic RAW\x00\xff\n"
    source.write_bytes(original)
    root = tmp_path / "vault"
    manifest = ArchiveManifest(root)
    first = manifest.archive(source, "synthetic-account", "test@1")
    for _ in range(9):
        assert manifest.archive(source, "synthetic-account", "test@1") == first
    assert first.content_hash == sha256_bytes(original)
    assert ObjectStore(root).read(first.content_hash) == original
    assert len([p for p in (root / "objects").rglob("*") if p.is_file()]) == 1
    assert source.read_bytes() == original


def test_corrupted_object_is_never_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.bin"
    source.write_bytes(b"synthetic original")
    store = ObjectStore(tmp_path / "vault")
    stored = store.put_file(source)
    # 在一次性合成测试目录中注入损坏，模拟外部磁盘或用户操作故障。
    stored.path.chmod(0o644)
    stored.path.write_bytes(b"synthetic corruption")
    with pytest.raises(IntegrityError, match="哈希不一致"):
        store.read(stored.content_hash)
    with pytest.raises(IntegrityError, match="哈希不一致"):
        store.put_file(source)
    assert stored.path.read_bytes() == b"synthetic corruption"


def test_concurrent_publish_creates_one_complete_object(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.bin"
    original = b"synthetic concurrent RAW" * 10000
    source.write_bytes(original)
    store = ObjectStore(tmp_path / "vault")
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: store.put_file(source), range(8)))
    assert sum(result.created for result in results) == 1
    assert store.read(results[0].content_hash) == original
    assert not list(store.objects.glob(".incoming-*"))


def test_account_provenance_survives_shared_object(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.bin"
    source.write_bytes(b"synthetic shared bytes")
    manifest = ArchiveManifest(tmp_path / "vault")
    a = manifest.archive(source, "account-a", "test@1")
    b = manifest.archive(source, "account-b", "test@1")
    assert a.content_hash == b.content_hash
    assert a.source != b.source


@pytest.mark.parametrize("value", ["../escape", "a" * 63, "A" * 64])
def test_invalid_content_address_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError):
        ObjectStore(tmp_path).object_path(value)
