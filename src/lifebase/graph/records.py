"""独立版本化的 Gold 图谱契约；不扩展 canonical v1。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pyarrow as pa

from lifebase.core.records import identity_hash

GRAPH_SCHEMA_VERSION = 1
NodeKind = Literal["source", "conversation", "message", "topic"]
EdgeKind = Literal["contains", "mentions"]


def node_id(kind: NodeKind, *identity: str) -> str:
    return identity_hash([kind, *identity])


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    kind: NodeKind
    source: str | None = None
    record_id: str | None = None
    revision_id: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class GraphEdge:
    edge_id: str
    kind: EdgeKind
    from_node: str
    to_node: str
    record_id: str | None
    revision_id: str | None
    weight: float | None
    algorithm_version: str | None
    evidence_ids: tuple[str, ...]


def edge_id(kind: EdgeKind, start: str, end: str) -> str:
    return identity_hash([kind, start, end])


@dataclass(frozen=True)
class GraphReport:
    status: Literal["ok", "missing", "stale", "error"]
    snapshot_id: str | None
    counts: dict[str, int]
    created: bool = False
    issues: tuple[dict[str, Any], ...] = ()


SCHEMAS = {
    "nodes": pa.schema([
        pa.field("node_id", pa.string(), nullable=False),
        pa.field("kind", pa.string(), nullable=False),
        *(pa.field(name, pa.string()) for name in ("source", "record_id", "revision_id", "label")),
    ]),
    "edges": pa.schema([
        *(pa.field(name, pa.string(), nullable=False)
          for name in ("edge_id", "kind", "from_node", "to_node")),
        pa.field("record_id", pa.string()), pa.field("revision_id", pa.string()),
        pa.field("weight", pa.float64()), pa.field("algorithm_version", pa.string()),
        pa.field("evidence_ids", pa.list_(pa.field("element", pa.string(), nullable=False)),
                 nullable=False),
    ]),
}
