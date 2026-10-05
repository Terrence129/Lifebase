"""Source Registry —— 所有数据源的状态与元数据。

字段（docs/context.md §6）：
    source_id, source_type, collector_version, sync_method,
    last_sync, earliest_record, latest_record, coverage,
    status, errors, credentials_reference, parser_version

当前阶段：仅定义数据结构，实现随 Weekend Prototype 的 list 命令推进。
"""
