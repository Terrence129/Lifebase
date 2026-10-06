"""本地数据目录校验；独立私有数据仓库通过显式登记选择加入。"""

from __future__ import annotations

import configparser
import json
import re
from pathlib import Path, PurePosixPath


def _registered_private_library(repository: Path, path: Path) -> bool:
    """只接受指定远端及库根；本地声明不代替推送前的远端可见性检查。"""
    marker = repository / ".lifebase-data.json"
    git = repository / ".git"
    try:
        if (not git.is_dir() or git.is_symlink() or marker.is_symlink()
                or marker.stat().st_size > 65536):
            return False
        value = json.loads(marker.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or type(value.get("schema_version")) is not int
                or value["schema_version"] != 1 or value.get("purpose") != "lifebase-private-data"
                or value.get("visibility") != "private"):
            return False
        identity = value.get("repository")
        if (not isinstance(identity, str)
                or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity) is None):
            return False
        config = configparser.ConfigParser(interpolation=None)
        config.read_string((git / "config").read_text(encoding="utf-8"))
        origin = config.get('remote "origin"', "url", fallback="")
        if origin not in {f"git@github.com:{identity}.git", f"https://github.com/{identity}.git",
                          f"ssh://git@github.com/{identity}.git"}:
            return False
        libraries = value.get("libraries")
        if not isinstance(libraries, dict) or not libraries:
            return False
        allowed = []
        for relative in libraries.values():
            if not isinstance(relative, str):
                return False
            parts = PurePosixPath(relative).parts
            if (len(parts) < 2 or parts[0] != "libraries" or ".." in parts
                    or PurePosixPath(relative).is_absolute()):
                return False
            library = repository.joinpath(*parts)
            require_plain_path(library, repository)
            allowed.append(library)
        return path in allowed
    except (OSError, ValueError, TypeError, configparser.Error):
        return False


def data_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists() and not _registered_private_library(parent, resolved):
            raise ValueError("数据目录不能位于普通 Git 工作树中；请使用仓库外目录，"
                             "或显式登记的独立私有数据仓库")
    return resolved


def require_plain_path(path: Path, root: Path) -> None:
    """数据目录内不沿符号链接读取证据或写入派生产物。"""
    path.relative_to(root)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError("数据路径含符号链接，操作已停止")
        if part == root:
            break
