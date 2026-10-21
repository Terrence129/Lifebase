# Lifebase 参考（非约束，按需阅读）

> 本文件是 [AGENTS.md](../AGENTS.md) 的参考附件，承载架构、目录、既定设计决策与项目背景等**非约束性**信息。
> **约束与红线一律以 `AGENTS.md` 为准**；本文件不复制红线。

## 1. 架构与数据流

```
LifeSync   → 采集：Collectors / Adapters / Importers / Data Inbox
LifeVault  → 存储：不可变 RAW（Bronze）+ 规范化（Silver）+ 派生（Gold）
LifeGraph  → 已实现：来源 / 会话 / 消息版本 / 关键词主题 / Evidence；语义融合待扩展
HumanOS    → 已实现：只读 Search / Timeline / Evidence / Context；AI / Trips / Past Me 待接入
```

图示见 README 的 [架构](../README.md#架构)，源文件为 `images/architecture.svg` 与
`images/cloud-query-path.svg`；架构或外发路径变化时同步更新。

数据流：`Collector → RAW → Normalizer → Canonical records`。Collector 生成规范化记录，
pipeline 协调归档、Silver 发布与来源登记；实施边界见 [AGENTS.md](../AGENTS.md)。

## 2. 项目背景与当前阶段

- **定位**：local-first 个人数据基础设施 —— 持续采集、保存、规范化分散在微信、照片、GPS、邮件、ChatGPT、GitHub、银行等处的数字生活痕迹，形成有证据支撑、带时间语义的个人知识图谱（LifeGraph），并在此之上构建个人 AI 应用（HumanOS）。「Own your data first. Intelligence comes later.」项目以个人开源项目为第一定位，商业化暂缓。

### 当前阶段

更新日期：2026-10-21。Harness 联调首轮完成：DeepSeek Harness fork 的 Lifebase 插件以云端
DeepSeek API 在合成库上走通工具调用与引用回答（[ADR-020](adr/ADR-020-Harness联调与合成库云端放行.md)）。
2026-10-21 用户批准真实库使用云端模型：ChatGPT、豆包默认 `cloud_ok`，目的地仅限 DeepSeek 官方 API，
见 [ADR-021](adr/ADR-021-聊天来源恢复云端可用与真实库试运行.md)；真实库已由用户在 Harness 中试运行一题。
同日新增只读会话列表工具 `conversations` 与 timeline 分页，见 [ADR-022](adr/ADR-022-会话列表工具与分页.md)：ruff 无告警，
223 项 pytest 与插件 17 项 `node --test` 通过；真实库全部会话分页列完，每 100 个会话约 5 万字符。
接入方式见 [接口说明](harness-interface.md)。

阶段历史：2026-10-06，ChatGPT 与豆包采集、Gold 关键词图谱、HumanOS 只读工具及独立
私有数据仓库完成验收，见 ADR-006–010、ADR-014–017。2026-10-06–07，聊天来源曾放宽为
`cloud_ok`（ADR-018），首个零构建插件在另一 fork 分支跑通（ADR-019）；两者的外发与目的地
决策由 ADR-020 取代，聊天来源外发级别又由 ADR-021 恢复为 `cloud_ok`。
合成演示库为 3 个会话、8 条消息。数据仓库用法见 [数据仓库说明](data-repository.md)。

联调验收（2026-10-20，macOS，DeepSeek-V41-Flash，合成库）：

- 合成 fixture 哈希白名单放行合成库的 cloud 请求，snapshot_id 不变；来源为 `local_only` 时，
  非合成输入的库仍返回 `EGRESS_BLOCKED`（2026-10-20 验收时聊天来源为 `local_only`）。Lifebase 全量校验：ruff 无告警，214 项 pytest 通过。
- 插件 13 项 `node --test` 通过，含参数注入、目的地判定与真实 CLI 调用。
- 8 道合成评测题：查无证据时如实说明、区分用户原话与助手建议、来源与时间筛选、
  时间线还原、证据回查均通过。所有回答引用的 evidence_id 都出现在同一会话的
  Lifebase 工具结果中。
- 首轮发现模型借 Harness 的 bash 绕过插件直接运行 CLI（仅合成库，未触及真实库或凭证）；
  加入独占工具 guard 后，bash、read、glob、subagent、workflow、web_fetch 均在派发阶段被拒绝。

### 待验证事项与停止点

- 引用 ID 存在不等于结论准确：模型自查发现一题中的来源归属与措辞错误；「虚构回忆」题
  标题结论过满。目前没有自动的结论—证据一致性检查。
- 会话列表已提供，模型是否改用它、单题 token 是否下降（此前最高约 136K）待在 Harness 中复测。
  search 仍无分页。
- 被 guard 拒绝的工具定义仍发送给模型；Harness 升级后需复测 guard。2026-10-21 fork 同步到
  上游 `0.2.1-rc.2` 后已复测：合成库 Profile 下 bash、read 被拒，`lifebase_search` 正常，插件测试 14 项通过。ADR-019 的插件没有
  guard，不能指向 Lifebase 数据。
- 目的地是 provider 映射声明，不具备网络隔离能力。
- verify 仍为 warning，仅因既有两个 Finder .DS_Store。豆包时间与回复关系缺口见 ADR-015。
- jieba 统计关键词不做语义归纳或同义融合；查询按快照载入内存，见 [基线说明](benchmarks/README.md)。
- 真实后续快照的增量语义与来源格式变化待验证；原始备份恢复仍需单独验收。

### 下一步与暂缓范围（未执行）

| 分类 | 当前待开展内容 | 完成条件 |
| --- | --- | --- |
| Build（Harness 插件） | 结论—证据一致性检查与 Web 引用卡片 | 自动标出引用不支持的结论 |
| Build + Integrate | 模型回答的 Gold 断言保存 | 引用支持度稳定后，确定带输入证据与模型信息的保存格式 |
| Reuse（restic、现有 collector） | 后续来源快照与独立备份恢复验收 | 根据实际输入和用户确定的备份目的地展开 |
| Defer | 真实库进入模型、本地模型路由、语义主题、Past Me、其他来源与自动采集 | 需另行决策；新增来源的外发策略各自修订 |

## 3. 既定设计决策（未经用户同意，不得重新讨论）

- **时间字段**：`occurred_at`（发生）/ `known_at`（知晓）/ `ingested_at`（入库）/ `valid_from` / `valid_to`。Past Me 检索必须按 `known_at <= 截止点` 过滤，防止未来知识向后泄漏。
- **分层**：Bronze = 原始证据（不可变、内容寻址）；Silver = 确定性规范化事实（可复现）；Gold = 派生数据（Trips/记忆/摘要/embedding，可随时重建丢弃）。
- **Life Primitives**：平台无关的 Entity / Artifact / Event / Observation / Transaction / Reservation / Relationship / State / Assertion / Evidence。禁止围绕具体 App 设计 schema。
- **Collector 接口**（`sync/base.py`）：`detect() / validate() / ingest() / normalize() / checkpoint() / metadata()`。重复导出复用同一派生分区；验证要求见 [AGENTS.md](../AGENTS.md#3-硬约束--验证方式)。
- **Data Inbox 流程**：用户把 export 丢进 inbox → 自动 detect 来源 → hash → 归档 RAW → 规范化 → 更新 Source Registry。目标体验：Download → Drop → Done。
- **采集方式优先级**：官方 API/OAuth > 官方导出 > 本地文件/数据库 > 现有开源提取器 > 用户触发的浏览器自动化 > 逆向。追求「可复现的采集」，不是「完美的采集」。
- **存储栈**：本地文件系统 + 内容寻址对象存储 + Parquet + DuckDB + SQLite。PostgreSQL/pgvector 后期再引入；不为「可能以后需要」提前引入依赖。
- **备份**：复用 restic，禁止自研加密/备份层。
- **外发策略**：每个 collector 声明来源默认外发级别（`local_only` / `redact_before_cloud` / `cloud_ok`），HumanOS 按目的地声明执行；ChatGPT、豆包默认 `cloud_ok`，批准的云端目的地仅 DeepSeek 官方 API，全部输入为仓库合成 fixture 的图谱也可用于云端（ADR-012 / ADR-016 / ADR-020 / ADR-021）。
- **Agent 运行时边界**：Agent 执行由外部运行时承担；Lifebase 不依赖任何运行时，只对外提供只读查询接口；AI 生成内容不作为关于用户现实生活的事实证据（ADR-013）。接入 Lifebase 数据的运行时 Profile 只运行 Lifebase 工具（ADR-020）。
- **项目命名**：伞形名 **Lifebase**（包名 `lifebase`、CLI 命令 `lifebase`）；四层保留原名 LifeSync / LifeVault / LifeGraph / HumanOS，对应子包 `sync/` `vault/` `graph/` `humanos/`（ADR-002）。

## 4. 目录速查

- `src/lifebase/core/` — 统一封装（envelope）、内容寻址（跨层）
- `src/lifebase/sync/` — LifeSync 层：Collector 契约（base.py）、Source Registry（registry.py）、collectors/（来源注册表 + ChatGPT / Doubao Export）
- `src/lifebase/vault/` — LifeVault 层：RAW 归档、manifest、silver/（规范化 Parquet）与内存查询连接
- `src/lifebase/graph/`、`src/lifebase/humanos/` — Gold 聊天图谱、终端工具与只读接口；实施规则见 [AGENTS.md](../AGENTS.md#1-角色与必须停下询问条件最高优先)
- `schemas/` — JSON Schema，与代码同仓库同版本
- `docs/adr/` — 架构决策记录（ADR）
- `docs/design/` — 待评估的架构猜想与设计假设（§5 索引指向）
- `docs/context.md` — 完整项目规格（背景资料，非 canonical）

## 5. 待评估的架构猜想与灵感（索引，非既定决策）

本栏目是项目灵感入口，记录尚未验证的思路；记录不代表已选型或已实现。
**每条灵感一律独立成文**（`docs/design/*.md`），此处只保留一句话摘要与链接，
防止参考文档随灵感积累而膨胀。

- [Nango：LifeSync API 接入候选](design/nango-integration-hypothesis.md) — **Defer**。当多个 OAuth 来源的持续同步产生重复维护成本时，再评估以 **Integrate** 方式接入 Nango；记录适用场景、部署取舍、证据保留问题和重新评估条件，尚未选型或接入。
- [浏览器辅助采集：从已登录的 App 获取可归档数据](design/doubao-browser-collection-hypothesis.md) — doubao-helper 文件导入已实现，见 [ADR-015](adr/ADR-015-豆包JSON导入与多来源重放.md)；浏览器自动采集与完整分页响应归档仍为 **Defer**。
- [双来源终端切片与后续范围](design/post-collector-roadmap-proposal.md) — **Build / Reuse** 的图谱与工具已落地，见 ADR-016；Harness 首轮联调见 ADR-020。
- [Agent 运行时集成：DeepSeek Harness × Lifebase](design/agent-runtime-integration-hypothesis.md) — Agent 执行交外部运行时（**Integrate**），边界已定于 [ADR-013](adr/ADR-013-Agent运行时集成边界.md)；只读工具插件已在合成库联调（ADR-020）；自动上下文、Past Me、Agent Team 与会话回采仍为 **Defer**。
