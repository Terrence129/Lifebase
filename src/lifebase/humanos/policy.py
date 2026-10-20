"""目的地声明与来源策略门禁；运行时的实际模型路由须另行验证。"""

from __future__ import annotations

from collections.abc import Iterable

from lifebase.humanos.records import Destination, ToolError
from lifebase.sync.base import EGRESS_POLICIES
from lifebase.sync.collectors import COLLECTORS

# 仓库内合成 fixture 的 RAW SHA-256（ADR-020）。图谱输入全部命中时才放宽云端门禁；
# 与 fixture 文件的一致性由 tests/unit/test_graph_humanos.py 校验。
SYNTHETIC_RAW_HASHES: dict[str, str] = {
    "4343f91bd07018432999d29015e52f8b4e77b5c62e5d6bc06f1b2796d35f2fa4": "chatgpt/export-a.zip",
    "dcd357977d275e01eed0b4afb5583a65f1c6bc0f798c42fd2a90d9d5f667d213": "chatgpt/export-b.zip",
    "ac560fea856d6689b3ae63aba341be58a00b6a1bbedea204e4128e8aee03d007": "doubao/export-a.json",
}


def enforce_destination(sources: dict[str, str], destination: Destination,
                        raw_hashes: Iterable[str] = ()) -> None:
    if destination not in ("local", "cloud"):
        raise ToolError("INVALID_REQUEST", "destination 必须为 local 或 cloud")
    hashes = set(raw_hashes)
    synthetic = bool(hashes) and hashes <= SYNTHETIC_RAW_HASHES.keys()
    for source, source_type in sources.items():
        if source_type not in COLLECTORS:
            raise ToolError("EGRESS_BLOCKED", "来源策略未知，请求已拒绝")
        policy = COLLECTORS[source_type](source).metadata().get("egress_policy")
        if policy not in EGRESS_POLICIES:
            raise ToolError("EGRESS_BLOCKED", "来源未声明有效外发策略")
        if destination == "cloud" and policy != "cloud_ok" and not synthetic:
            # Gold 身份与全局主题统计依赖整份输入，来源筛选不能缩小外发依赖范围。
            raise ToolError("EGRESS_BLOCKED", "图谱包含受限来源，不能用于云端目的地；本阶段不做脱敏")
