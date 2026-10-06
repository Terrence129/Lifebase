# Agent 运行时集成：DeepSeek Harness × Lifebase

- 状态：待评估的架构猜想，尚未选型或接入。
- 记录日期：2026-10-06。
- 当前分类：**Defer**；Agent 执行若落地，按 **Integrate** 方式接入外部运行时。
- 来源：用户构想稿《DeepSeek Harness × Lifebase：Personal Agent Runtime 构想》（2026-10-06，仓库外原稿），本页为浓缩整理，非原文。
- 项目约束统一见 [AGENTS.md](../../AGENTS.md)。已定的边界见 [ADR-013](../adr/ADR-013-Agent运行时集成边界.md)，外发级别见 [ADR-012](../adr/ADR-012-来源外发策略.md)；本页其余内容不构成决策。

## 猜想

用户已 fork DeepSeek Harness。构想中，Harness 已具备 Agent Loop、工具调用、会话、模型适配、插件、沙箱、审批、持久化与子 agent 等能力，Lifebase 不必另造 Agent 运行时，两者分工如下：

```text
Lifebase  = 个人数据 + 记忆 + 知识（知道「我」）
Harness   = Agent / 工具 / 模型 / 会话运行时（替「我」推理与行动）
```

fork 的维护原则是尽量不改 Harness 核心，通过插件、Profile 与少量集成补丁扩展，保持能同步 upstream。fork 的价值应来自新能力，而不是更大的 diff。

## 构想中的七个方向

| # | 方向 | 要点 | 依赖的 Lifebase 能力 |
| --- | --- | --- | --- |
| 1 | Lifebase 工具 | `search_life` / `get_timeline` / `get_person` / `explain_claim` 等工具，回答附来源 | 只读查询接口、Evidence |
| 2 | 个人上下文提供方 | 每次请求前按问题检索相关的人、事件、项目、过往决策并注入上下文 | LifeGraph、外发执行层 |
| 3 | 带证据的个人 Agent | 回答拆成 Claim + Evidence + Provenance，可点开「为什么这么认为」 | Evidence 定位、Gold 断言 |
| 4 | Past Me 运行时 | `past-me-2022` 之类的 Profile，按 `known_at <= 截止点` 隔离知识；延伸为多个历史自我对话 | `known_at` 语义、自我快照 |
| 5 | 隐私感知的模型路由 | 高敏感数据走本地模型，敏感数据脱敏或摘要，普通问题走云端 | 外发策略及其执行 |
| 6 | Harness 会话回采 | Agent 会话作为新来源进入 LifeSync，形成「Lifebase → Agent → 会话 → Lifebase」闭环 | 新 collector、AI 内容边界 |
| 7 | 个人专家 Agent 团队 | Timeline / Work / Decision 等子 agent 分工后综合证据 | 以上全部 |

构想还设想用 Harness Profile 表达不同模式（default / local / private / research / past-me / archivist），并把生态分为三层：Collector（把数据拿进来）、Data Service（查询与推理 Lifebase 数据）、Harness 插件（让 agent 使用 Lifebase）。三层不混在一起。

构想推荐的顺序是：工具 → 上下文提供方 → 证据层 → 隐私路由 → Past Me → Agent 团队。首个垂直切片是「提问 → Harness → lifebase-search → 证据 → 回答附来源」。最有代表性的功能是「带证据的个人 Agent」。

## 评估意见

- **顺序风险**：上下文自动注入（第 2 步）先于隐私路由（第 4 步），意味着在没有外发执行之前，每次请求都会把个人数据发给云端模型。ADR-013 已决定：外发执行层落地之前不做自动注入。
- **证据洗白**：会话回采后，模型回答可能在几年后被当作证据，支撑新的结论。ADR-013 已决定：AI 生成内容只证明「AI 当时说了什么」，回显的 Lifebase 数据只存引用。
- **虚假精度**：构想示例中的「Confidence 0.87」如果由模型自报，就不可信。Gold 断言优先用断言类型加证据清单表达，是否引入数值置信度留待有校准方法时再议。
- **第三方内容**：聊天类来源默认 `local_only`（ADR-012），路由放宽需要显式配置。
- **未核实**：Harness 的扩展点、稳定性与许可证均来自构想稿的描述，正式集成前需要核对 upstream。

## Build / Reuse / Integrate / Defer

- **Build**：只读查询接口与证据回溯，因为这是 Lifebase 自身的价值。在首条来源真实验收之后，以 `lifebase query` 为起点演进。
- **Reuse**：已有 Evidence 定位（`raw_member` / `raw_pointer`）、`known_at` 规则与外发策略声明，不另起一套。
- **Integrate**：Agent 执行交给外部运行时（当前候选为 Harness fork），运行时插件放在运行时自己的仓库。
- **Defer**：上下文提供方、证据层、隐私路由执行、Past Me Profile、会话回采 collector、Agent 团队。

## 重新评估的触发条件

- ChatGPT 官方导出的真实验收完成，开始设计第一个对外查询接口时：评估方向 1 与接口协议。
- 外发策略有了执行方之后：评估方向 2 与方向 5。
- LifeGraph 开始设计时：评估方向 3、4、7。
- 计划接入第二个来源时：将 Harness 会话回采与其他候选来源一起比较。
