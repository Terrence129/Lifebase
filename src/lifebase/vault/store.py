"""LifeVault 内容寻址 RAW 存储：原子发布、只追加、读回校验。"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lifebase.core.hashing import sha256_file


class IntegrityError(ValueError):
    """RAW 字节与内容地址不一致；调用方不能覆盖对象来修复。"""


@dataclass(frozen=True)
class StoredObject:
    content_hash: str
    size_bytes: int
    path: Path
    created: bool


class ObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.objects = root / "objects"

    def object_path(self, content_hash: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", content_hash) is None:
            raise ValueError("内容地址必须是 64 位小写十六进制 SHA-256")
        return self.objects / content_hash[:2] / content_hash[2:]

    def verify(self, content_hash: str) -> Path:
        path = self.object_path(content_hash)
        if path.is_symlink() or not path.is_file():
            raise IntegrityError(f"RAW 对象缺失或不是普通文件：{content_hash}")
        if sha256_file(path) != content_hash:
            raise IntegrityError(f"RAW 对象哈希不一致，已保留损坏对象：{content_hash}")
        return path

    def read(self, content_hash: str) -> bytes:
        path = self.object_path(content_hash)
        if path.is_symlink():
            raise IntegrityError(f"RAW 对象不是普通文件：{content_hash}")
        try:
            data = path.read_bytes()
        except FileNotFoundError as error:
            raise IntegrityError(f"RAW 对象缺失：{content_hash}") from error
        if hashlib.sha256(data).hexdigest() != content_hash:
            raise IntegrityError(f"RAW 对象哈希不一致，已保留损坏对象：{content_hash}")
        return data

    def put_file(self, source: Path) -> StoredObject:
        """先完整写入私有临时文件，再以硬链接原子发布；永不替换已有对象。"""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.objects.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary: Path | None = None
        try:
            digest = hashlib.sha256()
            size = 0
            with tempfile.NamedTemporaryFile(dir=self.objects, prefix=".incoming-", delete=False) as out:
                temporary = Path(out.name)
                with source.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        out.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                out.flush()
                os.fsync(out.fileno())
            content_hash = digest.hexdigest()
            path = self.object_path(content_hash)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary.chmod(0o400)
            try:
                os.link(temporary, path)
                created = True
                if os.name == "posix":
                    directory_fd = os.open(path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            except FileExistsError:
                created = False
            self.verify(content_hash)
            return StoredObject(content_hash, size, path, created)
        finally:
            # 只清理本次创建的临时文件，绝不删除或替换 RAW 对象。
            if temporary is not None:
                temporary.unlink(missing_ok=True)
