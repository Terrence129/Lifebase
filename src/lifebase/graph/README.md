# LifeGraph

聊天来源、会话、消息版本与自动关键词主题组成 Gold 图谱；包含关系与主题提及关系
保留 Evidence。jieba TF-IDF 每条消息默认最多提取五个关键词，统计关联不等同于语义理解。

`lifebase graph build` 从已验证 Silver 发布独立 Parquet 快照；`graph status` 检查哈希、
结构与证据引用，以及输入是否更新。读取缺失、损坏或过期的图谱会失败，需显式构图。

设计见 [ADR-016](../../../docs/adr/ADR-016-聊天图谱与Harness就绪接口.md)，操作见
[终端指南](../../../docs/demo.md)，实施约束见 [AGENTS.md](../../../AGENTS.md)。
