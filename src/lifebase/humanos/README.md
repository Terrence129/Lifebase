# HumanOS 数据接口

提供 `topics`、`conversations`、`search`、`timeline`、`evidence` 和 `context`，默认可读终端输出，
也支持 api_version=1 的 JSON。接口保留消息角色、版本、时间、图谱路径和证据定位；
上下文最多十条、每条三百字。当前没有模型生成回答。

来源目的地策略按整份图谱输入检查，来源筛选不能绕过；全部输入为仓库合成 fixture
时允许云端（ADR-020）；聊天来源默认 cloud_ok（ADR-021）。目的地是调用方声明，模型是否真正本地运行由消费方保证。运行时适配遵循 [ADR-013](../../../docs/adr/ADR-013-Agent运行时集成边界.md)。

契约与接入说明见 [Harness 接口](../../../docs/harness-interface.md)，操作见
[终端指南](../../../docs/demo.md)，实施约束见 [AGENTS.md](../../../AGENTS.md)。
