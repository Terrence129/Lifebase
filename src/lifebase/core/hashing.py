"""内容寻址工具：RAW 字节的 SHA-256。"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    """返回原始字节的十六进制摘要，不做编码或内容清洗。"""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """流式计算文件摘要，避免将大型 RAW 文件全部载入内存。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
