"""目的地声明与来源策略门禁；运行时的实际模型路由须另行验证。"""

from __future__ import annotations

from lifebase.humanos.records import Destination, ToolError
from lifebase.sync.base import EGRESS_POLICIES
from lifebase.sync.collectors import COLLECTORS


def enforce_destination(sources: dict[str, str], destination: Destination) -> None:
    if destination not in ("local", "cloud"):
        raise ToolError("INVALID_REQUEST", "destination 必须为 local 或 cloud")
    for source, source_type in sources.items():
        if source_type not in COLLECTORS:
            raise ToolError("EGRESS_BLOCKED", "来源策略未知，请求已拒绝")
        policy = COLLECTORS[source_type](source).metadata().get("egress_policy")
        if policy not in EGRESS_POLICIES:
            raise ToolError("EGRESS_BLOCKED", "来源未声明有效外发策略")
        if destination == "cloud" and policy != "cloud_ok":
            # Gold 身份与全局主题统计依赖整份输入，来源筛选不能缩小外发依赖范围。
            raise ToolError("EGRESS_BLOCKED", "图谱包含受限来源，不能用于云端目的地；本阶段不做脱敏")
