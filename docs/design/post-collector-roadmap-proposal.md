# 双来源终端切片与后续范围

更新日期：2026-10-20。用户批准的采集、存储、自动关键词图谱及 HumanOS 数据接口已
落地；决策见 [ADR-016](../adr/ADR-016-聊天图谱与Harness就绪接口.md)，当前验收与停止点见
[项目进度](../reference.md#2-项目背景与当前阶段)，操作见 [终端指南](../demo.md)。

## 当前交付

| 分类 | 交付 | 理由 |
| --- | --- | --- |
| Reuse | 已有 ChatGPT / Doubao collector、RAW/Silver、Evidence、Parquet 和 DuckDB | 两条来源与存储可以直接支撑图谱切片 |
| Reuse | 已锁定的 jieba 0.42.1 TF-IDF | 自动提取关键词主题，独立验收不依赖模型 |
| Build | 版本化 Gold 图谱、只读工具、终端输出、api_version=1 上下文包 | 主题关系参与检索，消息保持来源、角色、版本、时间与证据 |

统计主题表示文本关联，不自动判断现实事实、计划或人物身份。最多十条消息的上下文包
尚无模型生成回答。完整实现行为由 ADR-016 和 [接口契约](../harness-interface.md) 说明。

## 下一阶段

| 分类 | 后续工作 | 触发与完成条件 |
| --- | --- | --- |
| Integrate | 本地 DeepSeek Harness fork 的只读工具插件和 Profile | 2026-10-20 已在合成库联调，见 ADR-020 |
| Build + Integrate | 模型回答的 Gold 断言保存 | 先验证引用支持回答，再确定保存格式与输入证据关联 |
| Reuse（restic） | 单独备份与恢复验收 | 用户确定目的地后开展；Gold/Silver 重建不等同于原始数据恢复 |
| Defer | 语义主题、同义概念融合、Past Me、浏览器 UI、更多来源与自动采集 | 当前统计图谱不足以证明这些能力，需要另定范围和验收 |

Harness 首轮联调只覆盖合成库；完整个人数据应用另行估计工作量。约束与审批边界见 [AGENTS.md](../../AGENTS.md)，
运行时依赖方向见 [ADR-013](../adr/ADR-013-Agent运行时集成边界.md)。
