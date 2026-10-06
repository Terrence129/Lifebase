# ADR-013：Agent 运行时集成边界

- 状态：Accepted，用户于 2026-10-06 批准。
- 日期：2026-10-06

## 背景

用户已 fork DeepSeek Harness，并构想由它承担 Lifebase 的 Agent 执行（构想整理见 [Agent 运行时集成设计稿](../design/agent-runtime-integration-hypothesis.md)）：Lifebase 提供数据、记忆与证据，Harness 提供 Agent Loop、工具调用、会话与模型适配；后续还设想检索工具、个人上下文注入、带证据的回答、Past Me、隐私路由，以及把 Harness 会话回采进 Lifebase。

这些能力大多属于 LifeGraph / HumanOS 阶段，当前不实现。但其中有一个边界现在就要定下来：Lifebase 与任何具体 Agent 运行时之间的依赖方向。构想稿本身也强调模型、运行时与界面都应可替换，只有个人数据不应被锁定。

## 决策

1. **Integrate**：Agent 执行（Agent Loop、工具运行时、会话、模型适配、子 agent）由外部运行时承担，Lifebase 不自研；DeepSeek Harness fork 是当前候选，不是唯一选择。
2. **依赖方向单向**：Lifebase 不 import、不依赖任何 Agent 运行时；运行时专用的插件、Profile 与适配代码放在运行时自己的仓库（如 Harness fork），由它依赖 Lifebase。
3. **Build（Defer 实现）**：Lifebase 对外只暴露只读查询接口（检索、时间线、证据回溯），返回 Silver / Gold 记录与 Evidence 定位，不向运行时开放 RAW vault 的直接读写。具体协议（Python API、CLI、MCP 等）在第一个消费方出现时再选，选定时新增依赖须按 [AGENTS.md](../../AGENTS.md) §1 停下询问。
4. **外发由 Lifebase 侧把关**：查询接口按来源外发策略（[ADR-012](ADR-012-来源外发策略.md)）决定能返回什么给可能连接云端模型的调用方，不依赖运行时自觉。个人上下文自动注入在外发执行层落地之前不做。
5. **AI 生成内容的证据边界**：AI 生成的内容（ChatGPT 助手消息、未来回采的 Agent 会话中的模型回答）按来源原始角色保留，只能证明「AI 当时说了什么」，不能作为关于用户现实生活的事实证据。回采 Agent 会话时，工具结果中回显的 Lifebase 数据保存为对原记录的引用，不重复归档为新的来源证据，避免循环论证。
6. **Defer**：Context Provider、Evidence Layer、隐私路由、Past Me Profile、Agent Team、Harness 会话 collector，均等首条来源的真实验收与 LifeGraph 之后再评估。

## 被否方案

- **Lifebase 自研 Agent 运行时**：重复造成熟基础设施，违背优先复用；Agent 执行也不是 Lifebase 的核心价值。
- **在 Lifebase 仓库内维护 Harness 插件**：使 Lifebase 依赖某个快速迭代的运行时，运行时的 breaking change 会传导到数据基础设施，与「运行时可替换」相矛盾。
- **现在就选定 MCP 等接口协议**：尚无消费方，提前引入依赖与接口维护成本；协议可在第一个消费方出现时以较小代价选定。
- **让运行时直接读取 Parquet / RAW**：绕过外发策略与证据边界，且把存储布局变成对外契约，阻碍日后的 schema 演进。

## 后果

- 收益：运行时可整体替换而不影响数据层；外发控制集中在 Lifebase 一侧；AI 内容不会在多轮回采后被当成事实。
- 代价：运行时插件需在另一个仓库单独维护，跨仓库联调成本更高；在查询接口落地前，任何 Agent 集成都无法开始。
- 本 ADR 目前没有机械门禁；`test_constraints.py` 现有的层级边界门禁只覆盖 `graph/` 与 `humanos/`。
