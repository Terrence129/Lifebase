# ADR-004：约束文档的单一事实源与 Agent 友好结构

- 状态：Accepted
- 日期：2026-10-05

## 背景

改造前，同一批红线与规则被复制在 `AGENTS.md`、`CLAUDE.md`、`docs/context.md` 三处。ADR-002 已记录过「改一个命名需同步多处」的负担——这正是文档漂移的前兆，且多份副本之间没有明确的优先级。

同时，规则以「宣言式」表述为主：讲清了要什么，却缺少让 AI Agent 自证合规的手段（何时必须停下、如何验证、冲突时以谁为准）。对每轮都会注入 Agent 上下文的约束文件而言，结构效率直接影响 Agent 的可靠性与 token 成本。

## 决策

1. **`AGENTS.md` 是项目约束的唯一事实源（single source of truth）**，承载全部红线与规则。
2. 其他文档（`README.md`、`schemas/README.md`、`tests/fixtures/README.md` 等）只保留指向 `AGENTS.md` 的指针，**不得复制**其中的红线与规则。
3. **删除 `CLAUDE.md`**（原为指向 `AGENTS.md` 的指针）。若未来使用 Claude Code，用符号链接 `ln -s AGENTS.md CLAUDE.md` 补回，而非复制内容。
4. **移除约束文件对 `docs/context.md` 的引用**（该文件本身保留，作为背景资料，不再承担 canonical 角色）。
5. `AGENTS.md` 采用 Agent 友好结构，新增：冲突优先级、角色与「必须停下询问」条件、硬约束↔验证方式、收工前本地校验命令、完成定义（DoD）、方案输出模板。

## 后果

- 改规则只需改 `AGENTS.md` 一处，消除多处同步的漂移风险。
- `docs/adr/ADR-001`~`ADR-003` 中对 `context.md` 的引用属历史决策记录，保持不动。
- 「必测性质」（RAW hash 校验、collector 幂等性）目前仍只是约定、尚未落地为 CI 测试；落地为独立后续事项，不在本 ADR 范围内。
- 单一文件的代价：Claude Code 等只认 `CLAUDE.md` 的工具需手动补符号链接。

## 更新（2026-10-05）

为进一步压缩 Agent 每轮注入的 token，将**非约束的参考性内容**（架构图与数据流、目录速查、既定设计决策明细、项目背景与当前阶段）从 `AGENTS.md` 移出，集中到 `docs/reference.md`；`AGENTS.md` 自此**只保留约束**（冲突优先级、停止条件、红线、验证方式、DoD、工作规则、技术栈约定、交流约定）并留参考指针。

本更新是同一决策的细化，不改变「`AGENTS.md` 为约束唯一事实源」的结论；`docs/reference.md` 不复制红线，约束仍以 `AGENTS.md` 为准。
