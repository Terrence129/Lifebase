# Schemas

JSON Schema 定义与代码同仓库、同版本：

- 改 schema 与改代码在同一个 commit 里。
- Envelope、Life Primitives 的正式 schema 在 Weekend Prototype 之后逐步落进来。
- 命名：`<名称>.<schema_version>.schema.json`，如 `envelope.v1.schema.json`。
- 原则：RAW 永不变；canonical schema 版本化；parser 版本化；派生数据可弃（见 AGENTS.md「已定设计决策」）。
