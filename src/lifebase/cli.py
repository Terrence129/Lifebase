"""Lifebase CLI：手动导入 inbox、查看来源、只读查询与完整性检查。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from lifebase.core.paths import data_path
from lifebase.graph import GraphError, build_graph, graph_status
from lifebase.humanos import HumanOS, ToolError, ToolResult
from lifebase.humanos.service import parse_time
from lifebase.humanos.terminal import render
from lifebase.sync.collectors import make_collector
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.quality import quality
from lifebase.sync.rebuild import rebuild
from lifebase.sync.registry import SourceRegistry
from lifebase.sync.verification import verify
from lifebase.vault.query import query


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, (Path, Decimal)):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"无法序列化输出类型：{type(value).__name__}")


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, default=_json_default))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lifebase", description="本地 RAW 归档与可追溯查询")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / "Lifebase",
                        help="本地数据目录（默认 ~/Lifebase）")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="归档并规范化导出文件；目录按来源扫描，默认 inbox")
    ingest.add_argument("paths", nargs="*", type=Path)
    ingest.add_argument("--source", required=True, help="区分账户的来源 ID，例如 chatgpt:personal / doubao:personal")
    listing = commands.add_parser("list", help="查看 Source Registry")
    querying = commands.add_parser("query", help="对 events / artifacts / evidence 执行只读 SQL")
    querying.add_argument("sql", help="一条 SELECT 或 WITH SELECT")
    reporting = commands.add_parser("quality", help="汇总导入质量，区分身份、版本和内容缺口")
    for command in (querying, reporting):
        command.add_argument("--source", help="只选择指定来源")
        command.add_argument("--collector-version", help="只选择指定 collector 处理版本")
        command.add_argument("--parser-version", help="只选择指定 parser 处理版本")
        command.add_argument("--schema-version", type=int, help="只选择指定 schema 版本")
    verifying = commands.add_parser("verify", help="只读检查 RAW、Silver 与证据引用")
    rebuilding = commands.add_parser("rebuild", help="从 RAW 重建缺失派生数据，复用完整产物")
    rebuilding.add_argument("--source", help="只重建指定来源；默认处理全部归档来源")
    for command in (ingest, listing, querying, verifying, rebuilding, reporting):
        command.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS,
                             help="本地数据目录，也可放在命令前")
    graph = commands.add_parser("graph", help="自动构建或检查聊天主题图谱")
    graph.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
    actions = graph.add_subparsers(dest="graph_action", required=True)
    building = actions.add_parser("build", help="从已验证 Silver 发布 Gold 图谱")
    building.add_argument("--keywords-per-message", type=int, default=5)
    checking = actions.add_parser("status", help="检查 Gold 哈希、引用及是否过期")
    topics = commands.add_parser("topics", help="列出自动提取的关键词主题")
    search = commands.add_parser("search", help="沿主题关系搜索有证据的消息")
    search.add_argument("text")
    timeline = commands.add_parser("timeline", help="按时间阅读会话与版本")
    timeline.add_argument("--conversation", required=True, help="检索结果中的 conversation_id")
    evidence = commands.add_parser("evidence", help="只读返回规范化记录和证据定位")
    evidence.add_argument("evidence_id")
    context = commands.add_parser("context", help="准备供外部运行时消费的证据上下文")
    context.add_argument("question")
    for command in (building, checking, topics, search, timeline, evidence, context):
        command.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS)
        command.add_argument("--format", choices=("text", "json"), default="text")
    for command in (topics, search, timeline, evidence, context):
        command.add_argument("--destination", choices=("local", "cloud"), default="local")
    for command in (topics, search, timeline, context):
        command.add_argument("--source")
        command.add_argument("--limit", type=int, default=10)
    for command in (search, timeline, context):
        command.add_argument("--role")
        command.add_argument("--since", help="UTC 日期或带时区的时间戳，包含起点")
        command.add_argument("--until", help="UTC 日期或带时区的时间戳，不包含终点")
    return parser


TOOL_COMMANDS = {"graph", "topics", "search", "timeline", "evidence", "context"}


def _run_tool(args: argparse.Namespace, data_dir: Path) -> ToolResult:
    if args.command == "graph":
        report = (build_graph(data_dir, args.keywords_per_message) if args.graph_action == "build"
                  else graph_status(data_dir))
        return ToolResult("graph." + args.graph_action, report.status, report.snapshot_id, asdict(report))
    with HumanOS(data_dir, args.destination) as service:
        if args.command == "evidence":
            return service.evidence(args.evidence_id)
        options = {"source": args.source, "limit": args.limit}
        if args.command == "topics":
            return service.topics(**options)
        options.update(role=args.role, since=parse_time(args.since), until=parse_time(args.until))
        if args.command == "search":
            return service.search(args.text, **options)
        if args.command == "timeline":
            return service.timeline(args.conversation, **options)
        return service.context(args.question, **options)


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data_dir = data_path(args.data_dir)
        if args.command in TOOL_COMMANDS:
            result = _run_tool(args, data_dir)
            if args.format == "json":
                _print(asdict(result))
            else:
                print(render(result))
            return 0 if result.status in ("ok", "empty") else 1
        if args.command == "list":
            _print(SourceRegistry(data_dir).list_sources())
        elif args.command == "verify":
            report = verify(data_dir)
            _print(asdict(report))
            return 0 if report.status == "ok" else 1
        elif args.command == "rebuild":
            report = rebuild(data_dir, args.source)
            _print(asdict(report))
            return 0 if report.status == "ok" else 1
        elif args.command == "quality":
            _print(asdict(quality(data_dir, source=args.source,
                                 collector_version=args.collector_version,
                                 parser_version=args.parser_version, schema_version=args.schema_version)))
        elif args.command == "query":
            partitions = SourceRegistry(data_dir).partitions(
                source=args.source, collector_version=args.collector_version,
                parser_version=args.parser_version, schema_version=args.schema_version,
            )
            result = query(data_dir / "vault" / "silver", partitions, args.sql)
            _print(asdict(result))
        else:
            inputs = args.paths
            collector = make_collector(args.source)
            if not inputs:
                inbox = data_dir / "inbox"
                if not inbox.is_dir():
                    _print({"imports": [], "skipped": [], "message": "inbox 为空或尚未创建"})
                    return 0
                inputs = [inbox]
            paths: list[Path] = []
            skipped: list[str] = []
            for item in inputs:
                item = item.expanduser()
                if item.is_dir():
                    for candidate in sorted(path for path in item.iterdir() if path.is_file()):
                        if collector.detect(str(candidate)):
                            paths.append(candidate)
                        else:
                            skipped.append(candidate.name)
                else:
                    paths.append(item)
            imports: list[dict[str, Any]] = []
            failed = False
            for path in paths:
                try:
                    result = ingest_file(path.expanduser(), data_dir, args.source)
                    imports.append({"file": path.name, "status": "imported" if result.created else
                                    "unchanged", **asdict(result)})
                except (ValueError, OSError, sqlite3.Error) as error:
                    failed = True
                    imports.append({"file": path.name, "status": "error", "error": str(error)})
            _print({"imports": imports, "skipped": skipped})
            return 1 if failed else 0
    except (ValueError, OSError, sqlite3.Error, duckdb.Error, pa.ArrowException) as error:
        if args.command in TOOL_COMMANDS and args.format == "json":
            code = error.code if isinstance(error, (GraphError, ToolError)) else "INPUT_INVALID"
            _print({"api_version": 1, "tool": args.command, "status": "error", "snapshot_id": None,
                    "data": {}, "warnings": [], "error": {"code": code, "message": str(error)}})
            return 1
        print(f"lifebase: {error}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())
