"""新终端命令的可读输出；JSON 契约由 dataclass 序列化。"""

from __future__ import annotations

from lifebase.humanos.records import ToolResult


def render(result: ToolResult) -> str:
    lines = [f"{result.tool}: {result.status}"]
    if result.snapshot_id:
        lines.append(f"图谱快照: {result.snapshot_id}")
    data = result.data
    if result.tool.startswith("graph."):
        lines.extend(f"{name}: {value}" for name, value in data["counts"].items())
        lines.extend(f"{issue['code']}: {issue['message']}" for issue in data["issues"])
    for topic in data.get("topics", []):
        lines.append(f"{topic['term']} — {topic['messages']} 条消息，"
                     f"{topic['conversations']} 个会话，{topic['sources']} 个来源")
    if result.tool == "context":
        lines.append("证据上下文已准备；AI 回答等待 Harness 接入。")
    for match in data.get("matches", []):
        instant = match["occurred_at"]
        lines.append(f"\n[{match['source']} / {match['role']}] "
                     + (instant.isoformat() if instant is not None else "时间未知"))
        lines.append(match["excerpt"] + (" …（片段）" if match["truncated"] else ""))
        lines.append(f"会话: {match['conversation_id']}")
        lines.append(f"消息: {match['record_id']} / {match['revision_id']}")
        if match["matched_topics"]:
            lines.append("图谱路径: " + "、".join(match["matched_topics"]) + " → 消息 → 会话 → 来源")
        for evidence in match["evidence"]:
            lines.append(f"证据: {evidence['evidence_id']} "
                         f"({evidence['raw_member'] or 'JSON'}#{evidence['raw_pointer']})")
    if result.tool == "evidence" and data.get("evidence"):
        evidence = data["evidence"]
        lines.append(f"证据: {evidence['evidence_id']}")
        lines.append(f"来源: {evidence['source']}")
        lines.append(f"RAW 哈希: {evidence['content_hash']}")
        lines.append(f"定位: {evidence['raw_member'] or 'JSON'}#{evidence['raw_pointer']}")
        lines.append(data["record"]["excerpt"])
    lines.extend(f"提醒 {warning.code}: {warning.message}"
                 + (f"（{warning.count}）" if warning.count else "") for warning in result.warnings)
    return "\n".join(lines)
