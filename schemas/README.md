# Schemas

JSON Schema 定义与代码同仓库、同版本：

- 改 schema 与改代码在同一个 commit 里。
- 已发布 canonical v1：`event.v1.schema.json`、`artifact.v1.schema.json`、
  `evidence.v1.schema.json`；dataclass 位于 `src/lifebase/core/records.py`。
- Evidence 的 JSON / Parquet 展开保存原有 Envelope 字段；现有 Envelope dataclass 不变。
- canonical 命名：`<名称>.<schema_version>.schema.json`，如 `envelope.v1.schema.json`。
- HumanOS 工具输出独立于 canonical：[humanos-api-v1.json](humanos-api-v1.json)；
  字段、界限与合成样例见 [接口说明](../docs/harness-interface.md)。
- 契约与映射说明见 `docs/design/chatgpt-minimal-contract-draft.md`；项目约束以
  `AGENTS.md` 为准，既定设计决策见 `docs/reference.md`。
