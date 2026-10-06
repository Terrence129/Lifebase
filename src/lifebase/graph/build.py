"""从 canonical records 构建确定性关系与关键词主题。"""

from __future__ import annotations

import math
from dataclasses import asdict

import pyarrow as pa

from lifebase.graph.inputs import CanonicalData, GraphError, InputSelection
from lifebase.graph.keywords import ALGORITHM_VERSION, KeywordExtractor
from lifebase.graph.records import SCHEMAS, GraphEdge, GraphNode, edge_id, node_id


def structure(data: CanonicalData, inputs: InputSelection) -> tuple[
    dict[str, GraphNode], dict[str, GraphEdge],
]:
    nodes: dict[str, GraphNode] = {}
    edges: dict[str, GraphEdge] = {}
    for source in inputs.sources:
        sid = node_id("source", source)
        nodes[sid] = GraphNode(sid, "source", source=source, label=source)
    conversations: dict[str, list[str]] = {}
    conversation_sources: dict[str, str] = {}
    for row in data.events:
        key = ("event", row["record_id"], row["revision_id"])
        conversations.setdefault(row["record_id"], []).extend(data.references[key])
        conversation_sources[row["record_id"]] = data.sources[key]
    for rid, eids in sorted(conversations.items()):
        source = conversation_sources[rid]
        cid, sid = node_id("conversation", rid), node_id("source", source)
        nodes[cid] = GraphNode(cid, "conversation", source, rid)
        eid = edge_id("contains", sid, cid)
        edges[eid] = GraphEdge(eid, "contains", sid, cid, rid, None, None, None,
                               tuple(sorted(set(eids))))
    for row in data.messages:
        rid, revision = row["record_id"], row["revision_id"]
        key = ("artifact", rid, revision)
        mid, cid = node_id("message", rid, revision), node_id("conversation", row["context_record_id"])
        nodes[mid] = GraphNode(mid, "message", data.sources[key], rid, revision)
        eid = edge_id("contains", cid, mid)
        edges[eid] = GraphEdge(eid, "contains", cid, mid, rid, revision, None, None,
                               data.references[key])
    return nodes, edges


def build_tables(data: CanonicalData, inputs: InputSelection, keywords_per_message: int
                 ) -> dict[str, pa.Table]:
    nodes, edges = structure(data, inputs)
    with KeywordExtractor() as extractor:
        for row in data.messages:
            rid, revision = row["record_id"], row["revision_id"]
            mid = node_id("message", rid, revision)
            text = "\n".join(row["text_parts"] or [])
            for term, weight in extractor.extract(text, keywords_per_message):
                tid = node_id("topic", term)
                nodes[tid] = GraphNode(tid, "topic", label=term)
                eid = edge_id("mentions", mid, tid)
                edges[eid] = GraphEdge(eid, "mentions", mid, tid, rid, revision, weight,
                                       ALGORITHM_VERSION, data.references[("artifact", rid, revision)])
    return {
        "nodes": pa.Table.from_pylist([asdict(nodes[key]) for key in sorted(nodes)],
                                      schema=SCHEMAS["nodes"]),
        "edges": pa.Table.from_pylist([asdict(edges[key]) for key in sorted(edges)],
                                      schema=SCHEMAS["edges"]),
    }


def validate_references(tables: dict[str, pa.Table], data: CanonicalData,
                        inputs: InputSelection, keywords_per_message: int) -> None:
    """检查节点身份、结构关系、主题原文与每条 Evidence；不重新提取 TF-IDF。"""
    fixed_nodes, fixed_edges = structure(data, inputs)
    nodes = {row["node_id"]: row for row in tables["nodes"].to_pylist()}
    edges = {row["edge_id"]: row for row in tables["edges"].to_pylist()}
    if len(nodes) != tables["nodes"].num_rows or len(edges) != tables["edges"].num_rows:
        raise GraphError("GRAPH_INVALID", "图谱身份重复")
    for key, expected in fixed_nodes.items():
        if nodes.get(key) != asdict(expected):
            raise GraphError("GRAPH_INVALID", "图谱记录或来源节点与 Silver 不一致")
    for key, expected in fixed_edges.items():
        value = asdict(expected)
        value["evidence_ids"] = list(expected.evidence_ids)
        if edges.get(key) != value:
            raise GraphError("GRAPH_INVALID", "图谱包含关系或证据与 Silver 不一致")
    for key, row in nodes.items():
        if key in fixed_nodes:
            continue
        term = row["label"]
        if (row["kind"] != "topic" or not isinstance(term, str) or not term.strip()
                or term != term.casefold() or key != node_id("topic", term)
                or row != asdict(GraphNode(key, "topic", label=term))):
            raise GraphError("GRAPH_INVALID", "非法主题节点")
    messages = {(row["record_id"], row["revision_id"]): row for row in data.messages}
    used_topics: set[str] = set()
    mention_counts: dict[str, int] = {}
    for key, row in edges.items():
        if key in fixed_edges:
            continue
        rid, rev = row["record_id"], row["revision_id"]
        message = messages.get((rid, rev))
        topic = nodes.get(row["to_node"])
        weight = row["weight"]
        if (row["kind"] != "mentions" or message is None or topic is None
                or topic["kind"] != "topic"
                or row["from_node"] != node_id("message", rid, rev)
                or key != edge_id("mentions", row["from_node"], row["to_node"])
                or weight is None or not math.isfinite(weight) or weight <= 0
                or row["algorithm_version"] != ALGORITHM_VERSION
                or row["evidence_ids"] != list(data.references[("artifact", rid, rev)])
                or topic["label"] not in "\n".join(message["text_parts"] or []).casefold()):
            raise GraphError("GRAPH_INVALID", "主题关联、原文或证据引用不一致")
        used_topics.add(row["to_node"])
        mention_counts[row["from_node"]] = mention_counts.get(row["from_node"], 0) + 1
    if (used_topics != {key for key, row in nodes.items() if row["kind"] == "topic"}
            or any(count > keywords_per_message for count in mention_counts.values())):
        raise GraphError("GRAPH_INVALID", "主题节点孤立或关键词数量超限")


def counts(tables: dict[str, pa.Table]) -> dict[str, int]:
    result = {name: table.num_rows for name, table in tables.items()}
    for kind in ("source", "conversation", "message", "topic"):
        result[kind + "s"] = sum(value == kind for value in tables["nodes"]["kind"].to_pylist())
    result["mentions"] = sum(value == "mentions" for value in tables["edges"]["kind"].to_pylist())
    return result
