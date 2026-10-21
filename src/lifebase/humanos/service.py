"""固定只读查询、证据定位与有界上下文；不执行 Agent 或模型调用。"""

from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import duckdb

from lifebase.graph.inputs import CanonicalData
from lifebase.graph.keywords import KeywordExtractor
from lifebase.graph.records import node_id
from lifebase.graph.store import load_graph
from lifebase.humanos.policy import enforce_destination
from lifebase.humanos.records import (
    ConversationSummary,
    Destination,
    EvidenceLocator,
    GraphPath,
    MessageMatch,
    ToolError,
    ToolResult,
    Warning,
)
from lifebase.vault.query import read_connection


def _limit(limit: int) -> None:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ToolError("INVALID_REQUEST", "limit 必须为 1–100")


def _offset(offset: int) -> None:
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ToolError("INVALID_REQUEST", "offset 必须为 0–1000000 的整数")


TITLE_CHARS = 80


def _text(value: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ToolError("INVALID_REQUEST", "查询必须为 1–4096 字的非空文本")


def parse_time(value: str | None) -> datetime | None:
    """日期按 UTC 零点解释；时间戳必须明确给出时区。"""
    if value is None:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.fromisoformat(value).replace(tzinfo=UTC)
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(UTC)
    except (ValueError, TypeError) as error:
        raise ToolError("INVALID_REQUEST", "时间必须是 ISO 日期或含时区的 ISO 时间戳") from error


def _excerpt(parts: list[str] | None, terms: tuple[str, ...] = ()) -> tuple[str, bool]:
    text = "\n".join(parts or [])
    if len(text) <= 300:
        return text, False
    matches = [match for term in terms
               if (match := re.search(re.escape(term), text, re.IGNORECASE)) is not None]
    start = max(0, min((match.start() for match in matches), default=0) - 100)
    return text[start:start + 300], True


class HumanOS:
    """一个只读快照会话。使用 with 关闭其私有 DuckDB 内存连接。"""

    def __init__(self, data_dir: Path, destination: Destination = "local") -> None:
        snapshot = load_graph(data_dir)
        enforce_destination(snapshot.inputs.sources, destination, snapshot.inputs.raw_hashes)
        self.snapshot = snapshot
        self.destination = destination
        self._data = CanonicalData.from_tables(snapshot.silver, snapshot.inputs)
        self._manager: AbstractContextManager[duckdb.DuckDBPyConnection] = read_connection(
            snapshot.silver | {"graph_" + name: table for name, table in snapshot.tables.items()})
        self._connection: duckdb.DuckDBPyConnection | None = None

    def __enter__(self) -> Self:
        self._connection = self._manager.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self._manager.__exit__(*args)
        self._connection = None

    def _rows(self, sql: str, parameters: list[Any]) -> list[dict[str, Any]]:
        if self._connection is None:
            raise RuntimeError("HumanOS 必须在 with 会话中使用")
        cursor = self._connection.execute(sql, parameters)
        to_arrow = getattr(cursor, "to_arrow_table", cursor.fetch_arrow_table)
        return to_arrow().to_pylist()

    def _filters(self, source: str | None, role: str | None, since: datetime | None,
                 until: datetime | None) -> tuple[str, list[Any], str, list[Any]]:
        if source is not None and source not in self.snapshot.inputs.sources:
            raise ToolError("INVALID_REQUEST", "请求的来源未登记在此图谱中")
        if role is not None:
            _text(role)
        for value in (since, until):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None):
                raise ToolError("INVALID_REQUEST", "时间筛选必须含时区")
        if since is not None and until is not None and since >= until:
            raise ToolError("INVALID_REQUEST", "since 必须早于 until")
        conditions, parameters = [], []
        if source is not None:
            conditions.append("n.source = ?")
            parameters.append(source)
        if role is not None:
            conditions.append("a.role = ?")
            parameters.append(role)
        base = " AND ".join(conditions) or "TRUE"
        base_parameters = parameters.copy()
        if since is not None:
            conditions.append("a.occurred_at >= ?")
            parameters.append(since.astimezone(UTC))
        if until is not None:
            conditions.append("a.occurred_at < ?")
            parameters.append(until.astimezone(UTC))
        return " AND ".join(conditions) or "TRUE", parameters, base, base_parameters

    def _locator(self, row: dict[str, Any]) -> EvidenceLocator:
        return EvidenceLocator(**{field.name: row[field.name] for field in fields(EvidenceLocator)})

    def _match(self, row: dict[str, Any]) -> MessageMatch:
        rid, rev = row["record_id"], row["revision_id"]
        terms = tuple(row.get("matched_topics") or ())
        excerpt, truncated = _excerpt(row["text_parts"], terms)
        eids = self._data.references[("artifact", rid, rev)]
        return MessageMatch(rid, rev, row["context_record_id"], row["parent_record_id"],
                            row["source"], row["role"], row["occurred_at"], row["known_at"],
                            excerpt, truncated, row.get("score", 0.0), terms,
                            GraphPath(node_id("source", row["source"]),
                                      node_id("conversation", row["context_record_id"]),
                                      node_id("message", rid, rev),
                                      tuple(node_id("topic", term) for term in terms)),
                            tuple(self._locator(self._data.evidence[eid]) for eid in eids),
                            row["version_conflict"])

    def _result(self, tool: str, data: dict[str, Any], matches: list[MessageMatch],
                omitted: int = 0, total: int | None = None, offset: int = 0) -> ToolResult:
        warnings = []
        if omitted:
            warnings.append(Warning("UNKNOWN_TIME_EXCLUDED", "未知发生时间未参与范围命中", omitted))
        if not matches:
            warnings.append(Warning("INSUFFICIENT_EVIDENCE", "未找到符合筛选的消息证据"))
        if matches and all(match.role != "user" for match in matches):
            warnings.append(Warning("NO_USER_STATEMENT", "结果没有用户原话，不能作为用户事实或计划"))
        for code, message, count in (
            ("VERSION_CONFLICT", "同一消息存在无法按 known_at 排序的内容版本",
             sum(match.version_conflict for match in matches)),
            ("UNKNOWN_TIME", "消息时间缺失，未推测时间", sum(match.occurred_at is None for match in matches)),
            ("EXCERPT_TRUNCATED", "部分消息仅显示原文片段", sum(match.truncated for match in matches)),
        ):
            if count:
                warnings.append(Warning(code, message, count))
        if total is not None and total > offset + len(matches):
            warnings.append(Warning("RESULTS_TRUNCATED", "命中数量超过本次输出上限",
                                    total - offset - len(matches)))
        return ToolResult(tool, "ok" if matches else "empty", self.snapshot.snapshot_id,
                          data | {"matches": [asdict(match) for match in matches]}, tuple(warnings))

    def topics(self, *, source: str | None = None, limit: int = 10) -> ToolResult:
        _limit(limit)
        where, params, _, _ = self._filters(source, None, None, None)
        rows = self._rows(
            "SELECT t.node_id AS topic_id, t.label AS term, count(DISTINCT n.record_id) AS messages, "
            "count(DISTINCT a.context_record_id) AS conversations, "
            "count(DISTINCT n.source) AS sources, list(DISTINCT n.source ORDER BY n.source) AS source_ids "
            "FROM graph_edges e JOIN graph_nodes t ON t.node_id=e.to_node "
            "JOIN graph_nodes n ON n.node_id=e.from_node "
            "JOIN artifacts a ON a.record_id=n.record_id AND a.revision_id=n.revision_id "
            "WHERE e.kind='mentions' AND " + where + " GROUP BY t.node_id, t.label "
            "ORDER BY sources DESC, messages DESC, term LIMIT ?", params + [limit])
        return ToolResult("topics", "ok" if rows else "empty", self.snapshot.snapshot_id,
                          {"topics": rows})

    def _messages(self, *, query: str | None, conversation: str | None, source: str | None,
                  role: str | None, since: datetime | None, until: datetime | None,
                  limit: int, balance: bool = False, offset: int = 0,
                  ) -> tuple[list[MessageMatch], int, int]:
        _limit(limit)
        _offset(offset)
        where, params, base, base_params = self._filters(source, role, since, until)
        prefix = ""
        leading: list[Any] = []
        score, topics = "0.0", "[]::VARCHAR[]"
        if query is not None:
            _text(query)
            with KeywordExtractor() as extractor:
                terms = sorted({query.strip().casefold(), *(word for word, _ in extractor.extract(query))})
            prefix = (
                "WITH hits AS (SELECT e.from_node, sum(e.weight) AS score, "
                "list(t.label ORDER BY t.label) AS matched_topics FROM graph_edges e "
                "JOIN graph_nodes t ON t.node_id=e.to_node WHERE e.kind='mentions' AND "
                "t.label IN (" + ",".join("?" for _ in terms) + ") GROUP BY e.from_node) ")
            leading = terms
            score, topics = "h.score", "h.matched_topics"
        join = ("FROM graph_nodes n JOIN artifacts a ON a.record_id=n.record_id "
                "AND a.revision_id=n.revision_id ")
        if query is not None:
            join += "JOIN hits h ON h.from_node=n.node_id "
        join += "WHERE n.kind='message' AND "
        if conversation is not None:
            _text(conversation)
            where += " AND a.context_record_id=?"
            params.append(conversation)
            base += " AND a.context_record_id=?"
            base_params.append(conversation)
        total = self._rows(prefix + "SELECT count(*) AS total " + join + where,
                           leading + params)[0]["total"]
        omitted = 0
        if since is not None or until is not None:
            omitted = self._rows(prefix + "SELECT count(*) AS total " + join + base
                                 + " AND a.occurred_at IS NULL", leading + base_params)[0]["total"]
        selection = (
            "SELECT a.*, n.source, " + score + " AS score, " + topics + " AS matched_topics, "
            "EXISTS(SELECT 1 FROM record_conflicts c WHERE c.record_kind='artifact' "
            "AND c.record_id=a.record_id) AS version_conflict " + join + where)
        ordering = (" ORDER BY score DESC, occurred_at DESC NULLS LAST, record_id, revision_id"
                    if query is not None else
                    " ORDER BY occurred_at ASC NULLS LAST, record_id, revision_id")
        if balance:
            # 每个来源先取其最高分命中；全局候选仍有固定上限，不把全库返回给调用方。
            sql = prefix + "SELECT * FROM (" + selection + ") candidates "
            leaders = self._rows(sql + "QUALIFY row_number() OVER (PARTITION BY source "
                                 + ordering + ")=1" + ordering + " LIMIT ?",
                                 leading + params + [limit])
            remaining = self._rows(prefix + selection + ordering + " LIMIT ?",
                                   leading + params + [limit])
            chosen = {(row["record_id"], row["revision_id"]) for row in leaders}
            rows = leaders + [row for row in remaining
                              if (row["record_id"], row["revision_id"]) not in chosen]
            rows = rows[:limit]
        else:
            rows = self._rows(prefix + selection + ordering + " LIMIT ? OFFSET ?",
                              leading + params + [limit, offset])
        return [self._match(row) for row in rows], omitted, total

    def search(self, query: str, *, source: str | None = None, role: str | None = None,
               since: datetime | None = None, until: datetime | None = None,
               limit: int = 10) -> ToolResult:
        matches, omitted, total = self._messages(query=query, conversation=None, source=source,
                                                role=role, since=since, until=until, limit=limit)
        return self._result("search", {"query": query, "total": total}, matches, omitted, total)

    def timeline(self, conversation: str, *, source: str | None = None, role: str | None = None,
                 since: datetime | None = None, until: datetime | None = None,
                 limit: int = 10, offset: int = 0) -> ToolResult:
        matches, omitted, total = self._messages(query=None, conversation=conversation, source=source,
                                                role=role, since=since, until=until, limit=limit,
                                                offset=offset)
        end = offset + len(matches)
        return self._result("timeline", {"conversation_id": conversation, "total": total,
                                         "offset": offset, "next_offset": end if end < total else None},
                            matches, omitted, total, offset)

    def conversations(self, *, source: str | None = None, since: datetime | None = None,
                      until: datetime | None = None, limit: int = 10, offset: int = 0) -> ToolResult:
        """按最近活动倒序列出会话元数据；时间筛选选取范围内有消息的会话。"""
        _limit(limit)
        _offset(offset)
        self._filters(source, None, since, until)
        scope, params = "c.kind='conversation'", []
        if source is not None:
            scope += " AND c.source=?"
            params.append(source)
        stats = (
            "WITH m AS (SELECT a.context_record_id AS cid, a.record_id, a.role, a.occurred_at "
            "FROM graph_nodes n JOIN artifacts a ON a.record_id=n.record_id "
            "AND a.revision_id=n.revision_id WHERE n.kind='message'), "
            "s AS (SELECT c.record_id AS cid, c.source, min(m.occurred_at) AS first_at, "
            "max(m.occurred_at) AS last_at, count(DISTINCT m.record_id) AS messages, "
            "count(DISTINCT m.record_id) FILTER (WHERE m.role='user') AS user_messages "
            "FROM graph_nodes c LEFT JOIN m ON m.cid=c.record_id WHERE " + scope
            + " GROUP BY c.record_id, c.source) ")
        window, window_params = "TRUE", []
        if since is not None or until is not None:
            clauses = ["m.cid=s.cid"]
            for operator, value in ((">=", since), ("<", until)):
                if value is not None:
                    clauses.append("m.occurred_at " + operator + " ?")
                    window_params.append(value.astimezone(UTC))
            window = "EXISTS (SELECT 1 FROM m WHERE " + " AND ".join(clauses) + ")"
        total = self._rows(stats + "SELECT count(*) AS total FROM s WHERE " + window,
                           params + window_params)[0]["total"]
        omitted = 0
        if window != "TRUE":
            omitted = self._rows(
                stats + "SELECT count(*) AS total FROM s WHERE NOT " + window
                + " AND EXISTS (SELECT 1 FROM m WHERE m.cid=s.cid AND m.occurred_at IS NULL)",
                params + window_params)[0]["total"]
        rows = self._rows(stats + "SELECT * FROM s WHERE " + window
                          + " ORDER BY last_at DESC NULLS LAST, cid LIMIT ? OFFSET ?",
                          params + window_params + [limit, offset])
        ids = [row["cid"] for row in rows]
        topics: dict[str, list[str]] = {cid: [] for cid in ids}
        conflicts: set[str] = set()
        if ids:
            marks = ",".join("?" for _ in ids)
            for row in self._rows(
                    "SELECT cid, label FROM (SELECT a.context_record_id AS cid, t.label, "
                    "sum(e.weight) AS weight FROM graph_edges e "
                    "JOIN graph_nodes t ON t.node_id=e.to_node JOIN graph_nodes n ON n.node_id=e.from_node "
                    "JOIN artifacts a ON a.record_id=n.record_id AND a.revision_id=n.revision_id "
                    "WHERE e.kind='mentions' AND a.context_record_id IN (" + marks + ") "
                    "GROUP BY a.context_record_id, t.label) "
                    "QUALIFY row_number() OVER (PARTITION BY cid ORDER BY weight DESC, label) <= 5 "
                    "ORDER BY cid, weight DESC, label", ids):
                topics[row["cid"]].append(row["label"])
            conflicts = {row["record_id"] for row in self._rows(
                "SELECT record_id FROM record_conflicts WHERE record_kind='event' "
                "AND record_id IN (" + marks + ")", ids)}
        revisions: dict[str, list[dict[str, Any]]] = {}
        for event in self._data.events:
            if event["record_id"] in topics:
                revisions.setdefault(event["record_id"], []).append(event)
        summaries = []
        for row in rows:
            cid = row["cid"]
            # 标题取 known_at 最新的版本；known_at 缺失的版本排在最前，冲突另行标记。
            event = max(revisions[cid], key=lambda item: (
                item["known_at"] is not None, item["known_at"] or datetime.min.replace(tzinfo=UTC),
                item["revision_id"]))
            title = event["title"]
            eids = self._data.references[("event", cid, event["revision_id"])]
            summaries.append(ConversationSummary(
                cid, row["source"], title[:TITLE_CHARS] if title is not None else None,
                title is not None and len(title) > TITLE_CHARS, row["first_at"], row["last_at"],
                row["messages"], row["user_messages"], tuple(topics[cid]), eids, cid in conflicts))
        warnings = []
        if not summaries:
            warnings.append(Warning("INSUFFICIENT_EVIDENCE", "未找到符合筛选的会话"))
        if omitted:
            warnings.append(Warning("UNKNOWN_TIME_EXCLUDED", "含未知时间消息的会话未参与范围命中", omitted))
        for code, message, count in (
            ("UNKNOWN_TIME", "会话没有带时间的消息，未推测时间",
             sum(item.last_message_at is None for item in summaries)),
            ("VERSION_CONFLICT", "会话标题存在无法按 known_at 排序的版本",
             sum(item.version_conflict for item in summaries)),
        ):
            if count:
                warnings.append(Warning(code, message, count))
        end = offset + len(summaries)
        if total > end:
            warnings.append(Warning("RESULTS_TRUNCATED", "会话数量超过本次输出上限，可用 offset 继续",
                                    total - end))
        return ToolResult("conversations", "ok" if summaries else "empty", self.snapshot.snapshot_id,
                          {"total": total, "offset": offset, "next_offset": end if end < total else None,
                           "conversations": [asdict(item) for item in summaries]}, tuple(warnings))

    def context(self, question: str, *, source: str | None = None, role: str | None = None,
                since: datetime | None = None, until: datetime | None = None,
                limit: int = 10) -> ToolResult:
        _limit(limit)
        if limit > 10:
            raise ToolError("INVALID_REQUEST", "context 最多输出 10 条消息")
        matches, omitted, total = self._messages(query=question, conversation=None, source=source,
                                                role=role, since=since, until=until,
                                                limit=limit, balance=True)
        return self._result("context", {"question": question, "total": total,
                                        "destination": self.destination, "generated_answer": None,
                                        "content_chars": sum(len(match.excerpt) for match in matches)},
                            matches, omitted, total)

    def evidence(self, evidence_id: str) -> ToolResult:
        _text(evidence_id)
        rows = self._rows("SELECT * FROM evidence WHERE evidence_id=?", [evidence_id])
        if not rows:
            return ToolResult("evidence", "empty", self.snapshot.snapshot_id, {"evidence": None},
                              (Warning("INSUFFICIENT_EVIDENCE", "未找到此证据引用"),))
        row = rows[0]
        kind = row["record_kind"]
        table = "artifacts" if kind == "artifact" else "events"
        record = self._rows("SELECT * FROM " + table + " WHERE record_id=? AND revision_id=?",
                            [row["record_id"], row["revision_id"]])[0]
        parts = record.pop("text_parts", None) if kind == "artifact" else [record.pop("title") or ""]
        excerpt, truncated = _excerpt(parts)
        warnings = (Warning("EXCERPT_TRUNCATED", "仅返回规范化记录片段", 1),) if truncated else ()
        return ToolResult("evidence", "ok", self.snapshot.snapshot_id,
                          {"evidence": asdict(self._locator(row)),
                           "record": record | {"excerpt": excerpt, "truncated": truncated}}, warnings)
