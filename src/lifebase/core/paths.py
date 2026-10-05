"""本地数据目录校验，防止将 RAW 对象写进 Git 工作树。"""

from __future__ import annotations

from pathlib import Path


def data_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if any((parent / ".git").exists() for parent in (resolved, *resolved.parents)):
        raise ValueError("数据目录不能位于 Git 工作树中；请使用 ~/Lifebase 或仓库外目录")
    return resolved


def require_plain_path(path: Path, root: Path) -> None:
    """数据目录内不沿符号链接读取证据或写入派生产物。"""
    path.relative_to(root)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("数据路径含符号链接，操作已停止")
        if part == root:
            break
