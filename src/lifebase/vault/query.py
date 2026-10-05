"""对登记的 Silver 分区做只读 DuckDB 查询；不开放任意外部文件读取。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from lifebase.vault.silver import SilverStore


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


def query(silver_root: Path, partitions: list[str], sql: str) -> QueryResult:
    tables = SilverStore(silver_root).load(partitions)
    with duckdb.connect(":memory:", config={"enable_external_access": False,
                                         "autoinstall_known_extensions": False,
                                         "autoload_known_extensions": False}) as connection:
        for name, table in tables.items():
            connection.register("incoming_" + name, table)
            connection.execute(f"CREATE TABLE {name} AS SELECT DISTINCT * FROM incoming_{name}")
            connection.unregister("incoming_" + name)
        connection.execute(
            "CREATE VIEW record_conflicts AS "
            "SELECT 'event' AS record_kind, record_id, count(*) AS revision_count "
            "FROM events GROUP BY record_id HAVING count(*) > 1 AND "
            "(count(known_at) < count(*) OR count(DISTINCT known_at) < count(*)) "
            "UNION ALL SELECT 'artifact', record_id, count(*) FROM artifacts GROUP BY record_id "
            "HAVING count(*) > 1 AND "
            "(count(known_at) < count(*) OR count(DISTINCT known_at) < count(*))"
        )
        statements = connection.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("query 仅允许一条 SELECT / WITH SELECT 查询")
        cursor = connection.execute(sql)
        assert cursor.description is not None
        to_arrow = getattr(cursor, "to_arrow_table", cursor.fetch_arrow_table)
        table = to_arrow()
        columns = tuple(table.column_names)
        # 经 Arrow 转回 Python，UTC 时间不依赖 DuckDB 可选的 pytz；保留重名列。
        def utc_value(value: Any) -> Any:
            if isinstance(value, datetime) and value.tzinfo is not None:
                return value.astimezone(UTC)
            if isinstance(value, list):
                return [utc_value(item) for item in value]
            if isinstance(value, dict):
                return {key: utc_value(item) for key, item in value.items()}
            return value

        rows = tuple(tuple(utc_value(item) for item in row)
                     for row in zip(*(column.to_pylist() for column in table.columns), strict=True))
        return QueryResult(columns, rows)
