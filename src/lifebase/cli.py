"""Lifebase CLI：手动导入 inbox、查看来源、只读查询 Silver。"""

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

from lifebase.core.paths import data_path
from lifebase.sync.collectors.chatgpt import ChatGPTCollector
from lifebase.sync.pipeline import ingest_file
from lifebase.sync.registry import SourceRegistry
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
    ingest = commands.add_parser("ingest", help="归档并规范化 ChatGPT 导出；未指定文件则扫描 inbox")
    ingest.add_argument("paths", nargs="*", type=Path)
    ingest.add_argument("--source", required=True, help="区分账户的来源 ID，例如 chatgpt:personal")
    listing = commands.add_parser("list", help="查看 Source Registry")
    querying = commands.add_parser("query", help="对 events / artifacts / evidence 执行只读 SQL")
    querying.add_argument("sql", help="一条 SELECT 或 WITH SELECT")
    for command in (ingest, listing, querying):
        command.add_argument("--data-dir", type=Path, default=argparse.SUPPRESS,
                             help="本地数据目录，也可放在命令前")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data_dir = data_path(args.data_dir)
        if args.command == "list":
            _print(SourceRegistry(data_dir).list_sources())
        elif args.command == "query":
            result = query(data_dir / "vault" / "silver", SourceRegistry(data_dir).partitions(), args.sql)
            _print(asdict(result))
        else:
            paths = args.paths
            if not paths:
                inbox = data_dir / "inbox"
                if not inbox.is_dir():
                    _print({"imports": [], "skipped": [], "message": "inbox 为空或尚未创建"})
                    return 0
                collector = ChatGPTCollector(args.source)
                candidates = sorted(path for path in inbox.iterdir() if path.is_file())
                paths = [path for path in candidates if collector.detect(str(path))]
                skipped = [path.name for path in candidates if path not in paths]
            else:
                skipped = []
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
    except (ValueError, OSError, sqlite3.Error, duckdb.Error) as error:
        print(f"lifebase: {error}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())
