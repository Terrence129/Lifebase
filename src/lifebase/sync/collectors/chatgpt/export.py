"""ChatGPT ZIP 输入：有界读取单文件或分片，并保留各成员的原始定位。"""

from __future__ import annotations

import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lifebase.core.hashing import sha256_bytes, sha256_file

MAX_JSON_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
NUMBERED_MEMBER = re.compile(r"conversations-([0-9]+)\.json")


class ExportError(ValueError):
    """来源格式错误；归档输入保留供核查或后续重新解析。"""


@dataclass(frozen=True)
class RawMember:
    member: str
    member_hash: str
    conversations: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class RawExport:
    content_hash: str
    members: tuple[RawMember, ...]
    issues: tuple[str, ...] = ()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExportError("JSON 含重复 key，不能无损确定记录结构")
        result[key] = value
    return result


def _read_json(archive: zipfile.ZipFile, name: str, limit: int) -> tuple[bytes, Any]:
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise ExportError(f"{name} 超过 JSON 处理上限；RAW 已保留")
    if info.flag_bits & 1:
        raise ExportError("本版不支持加密 ZIP；RAW 已保留")
    with archive.open(info) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ExportError(f"{name} 解压大小超过 JSON 处理上限；RAW 已保留")
    return data, json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)


def _conversation_members(counts: Counter[str]) -> list[str]:
    numbered = [name for name in counts if NUMBERED_MEMBER.fullmatch(name)]
    if "conversations.json" in counts and numbered:
        raise ExportError("单文件与编号会话文件同时存在，无法确定输入布局")
    members = ["conversations.json"] if "conversations.json" in counts else numbered
    if not members:
        raise ExportError("ZIP 必须包含 conversations.json 或从 0 起连续编号的会话文件")
    if any(counts[name] != 1 for name in members):
        raise ExportError("ZIP 会话成员必须唯一")
    if numbered:
        try:
            ordered = sorted((int(NUMBERED_MEMBER.fullmatch(name)[1]), name) for name in numbered)
        except ValueError as error:
            raise ExportError("会话文件编号无法解析") from error
        if [index for index, _ in ordered] != list(range(len(ordered))):
            raise ExportError("会话文件编号须从 0 起连续且唯一")
        members = [name for _, name in ordered]
    return members


def _manifest_members(archive: zipfile.ZipFile, counts: Counter[str],
                      members: list[str]) -> list[str]:
    if counts["export_manifest.json"] != 1:
        raise ExportError("export_manifest.json 必须唯一")
    _, manifest = _read_json(archive, "export_manifest.json", MAX_MANIFEST_BYTES)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("logical_files"), dict):
        raise ExportError("manifest.logical_files 必须是对象")
    entry = manifest["logical_files"].get("conversations.json")
    if not isinstance(entry, dict):
        raise ExportError("manifest 缺少 conversations.json 逻辑文件")
    files = entry.get("files")
    if (not isinstance(files, list) or not files
            or not all(isinstance(name, str) for name in files)
            or len(set(files)) != len(files) or set(files) != set(members)):
        raise ExportError("manifest 会话文件引用与 ZIP 成员不一致或重复")
    shard_count = entry.get("shard_count")
    if (type(shard_count) is not int or shard_count != len(files)
            or type(entry.get("sharded")) is not bool
            or entry["sharded"] != (members != ["conversations.json"])):
        raise ExportError("manifest 分片标记或数量不一致")
    # 只核对会话文件库存，不为媒体、账户或 Sites 创建解析依赖。
    inventory = manifest.get("export_files")
    if inventory is not None:
        if not isinstance(inventory, list):
            raise ExportError("manifest.export_files 必须是数组")
        selected: dict[str, int] = {}
        for item in inventory:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ExportError("manifest 文件库存条目非法")
            name = item["path"]
            if name not in members:
                continue
            size = item.get("size_bytes")
            if (name in selected or type(size) is not int
                    or size != archive.getinfo(name).file_size):
                raise ExportError("manifest 会话库存重复或长度不一致")
            selected[name] = size
        if set(selected) != set(members):
            raise ExportError("manifest 文件库存缺少会话成员")
    return files


def read_export(path: Path) -> RawExport:
    issues: tuple[str, ...] = ()
    try:
        with zipfile.ZipFile(path) as archive:
            counts = Counter(archive.namelist())
            members = _conversation_members(counts)
            if "export_manifest.json" in counts:
                members = _manifest_members(archive, counts, members)
            elif members != ["conversations.json"]:
                issues = ("编号会话文件没有 manifest，无法证明导出完整性",)
            if sum(archive.getinfo(name).file_size for name in members) > MAX_JSON_BYTES:
                raise ExportError("会话 JSON 总量超过 128 MiB 处理上限；RAW 已保留")
            result: list[RawMember] = []
            total_bytes = 0
            for name in members:
                # 不解压到文件系统；按剩余额度约束实际解压字节。
                data, parsed = _read_json(archive, name, MAX_JSON_BYTES - total_bytes)
                total_bytes += len(data)
                if (not isinstance(parsed, list)
                        or not all(isinstance(item, dict) for item in parsed)):
                    raise ExportError(f"{name} 顶层必须是会话对象数组")
                result.append(RawMember(name, sha256_bytes(data), tuple(parsed)))
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, RuntimeError,
            NotImplementedError, RecursionError) as error:
        raise ExportError(f"无法读取会话 JSON：{type(error).__name__}") from error
    return RawExport(sha256_file(path), tuple(result), issues)
