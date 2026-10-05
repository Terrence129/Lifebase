"""确定性 ChatGPT 合成导出：重叠、编辑、分支、缺失时间和非文本。"""

from __future__ import annotations

import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

START = 1767225600
CONVERSATION_SIZE = 50


@dataclass(frozen=True)
class SyntheticCase:
    base_messages: int
    added_messages: int
    edited_messages: int
    logical_messages: int
    message_versions: int
    conversations: int
    evidence: int
    body_chars: int
    zip_bytes: int
    json_bytes: int


def _conversations(total: int, base: int, body_chars: int, edited: bool) -> list[dict[str, Any]]:
    conversations: list[dict[str, Any]] = []
    for start in range(0, total, CONVERSATION_SIZE):
        index = start // CONVERSATION_SIZE
        cid = f"synthetic-scale-conversation-{index}"
        root = f"synthetic-root-{index}"
        mapping: dict[str, Any] = {root: {
            "id": root, "parent": None, "children": [], "message": None,
        }}
        for offset in range(min(CONVERSATION_SIZE, total - start)):
            number = start + offset + 1
            node = f"synthetic-node-{number}"
            parent = root if offset == 0 else f"synthetic-node-{number - 1}"
            if offset == 20:
                parent = f"synthetic-node-{number - 2}"
            changed = edited and number <= base and number % 101 == 0
            content = {"content_type": "text", "parts": [
                f"synthetic message {number} ", "x" * body_chars + (" edited" if changed else ""),
            ]}
            if number % 25 == 0:
                content = {"content_type": "multimodal_text", "parts": [{
                    "content_type": "image_asset_pointer", "asset_pointer": f"synthetic://{number}",
                }]}
            known = None if number % 10 == 0 else START + number + 1
            if changed:
                known = START + number + 2_000_000
            mapping[node] = {"id": node, "parent": parent, "children": [], "message": {
                "id": f"synthetic-message-{number}",
                "author": {"role": "user" if number % 2 else "assistant"},
                "content": content, "create_time": None if number % 20 == 0 else START + number,
                "update_time": known,
            }}
            mapping[parent]["children"].append(node)
        conversations.append({
            "id": cid, "title": f"synthetic scale conversation {index}",
            "create_time": START + start, "update_time": START + start + 500_000,
            "current_node": node, "mapping": mapping,
        })
    return list(reversed(conversations)) if edited else conversations


def generate_case(root: Path, messages: int, body_chars: int = 256) -> SyntheticCase:
    """只能写入新目录；不读取或变换任何真实导出。"""
    if messages < 1 or body_chars < 0:
        raise ValueError("messages 必须为正数，body_chars 不能为负")
    root.mkdir(parents=True, exist_ok=False)
    added = messages // 20
    json_bytes = 0
    zip_bytes = 0
    for label, total, edited in (("export-a", messages, False),
                                 ("export-b", messages + added, True)):
        data = json.dumps(_conversations(total, messages, body_chars, edited),
                          ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        info = zipfile.ZipInfo("conversations.json", date_time=(2026, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100600 << 16
        with (root / f"{label}.zip").open("xb") as stream, zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(info, data)
        json_bytes += len(data)
        zip_bytes += (root / f"{label}.zip").stat().st_size
    return SyntheticCase(messages, added, messages // 101, messages + added,
                         messages + added + messages // 101,
                         math.ceil((messages + added) / CONVERSATION_SIZE),
                         2 * messages + added + math.ceil(messages / CONVERSATION_SIZE)
                         + math.ceil((messages + added) / CONVERSATION_SIZE),
                         body_chars, zip_bytes, json_bytes)
