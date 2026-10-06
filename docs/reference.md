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

数据流：`Collector → RAW → Normalizer → Canonical records`。Collector 生成规范化记录，
pipeline 协调归档、Silver 发布与来源登记；实施边界见 [AGENTS.md](../AGENTS.md)。

## 2. 项目背景与当前阶段

- **定位**：local-first 个人数据基础设施 —— 持续采集、保存、规范化分散在微信、照片、GPS、邮件、ChatGPT、GitHub、银行等处的数字生活痕迹，形成有证据支撑、带时间语义的个人知识图谱（LifeGraph），并在此之上构建个人 AI 应用（HumanOS）。「Own your data first. Intelligence comes later.」项目以个人开源项目为第一定位，商业化暂缓。

### 当前阶段

更新日期：2026-10-07。双来源自动关键词图谱与 HumanOS 只读工具已经实现；Harness 联调的
首个垂直切片已在该 fork 的 `feat/lifebase-readonly-plugin` 分支跑通——一个零构建只读
插件把五个查询命令暴露为 Harness 工具，云端 DeepSeek 模型调用工具并带 `record_id` /
`revision_id` / `evidence_id` 引用回答。加载路径、退出码映射、空结果语义与目的地透传
都有自动化验收；实现位置、工具清单与配置见 [接口说明](harness-interface.md)。插件的交付
形态与 `destination` 的声明责任见 [ADR-019](adr/ADR-019-只读插件的交付形态与目的地声明.md)。

2026-10-06 聊天来源的默认外发级别由 `local_only` 放宽为 `cloud_ok`，合成库与真实库
一致生效，见 [ADR-018](adr/ADR-018-聊天来源默认外发策略放宽.md)。

阶段历史：2026-10-06，ChatGPT 原型与本地验收完成，见
[ADR-006](adr/ADR-006-首个采集切片的最小输出契约.md)、
[ADR-007](adr/ADR-007-RAW归档与Silver快照发布.md)、
[ADR-008](adr/ADR-008-只读完整性检查.md)、
[ADR-009](adr/ADR-009-RAW重放与处理版本选择.md)、
[ADR-010](adr/ADR-010-导入质量报告与合成规模基线.md)、
[ADR-014](adr/ADR-014-ChatGPT分片导出与仅父节点适配.md)。
同日豆包与混合来源验收完成，见 [ADR-015](adr/ADR-015-豆包JSON导入与多来源重放.md)；
Gold 与 Harness 就绪接口的切片见 [ADR-016](adr/ADR-016-聊天图谱与Harness就绪接口.md)。
同日真实库、合成库及来源导出迁入独立 private 数据仓库并完成同步，见
[ADR-017](adr/ADR-017-独立私有数据仓库与无损迁移.md)。同日聊天来源默认外发级别放宽为
云端可用，见 [ADR-018](adr/ADR-018-聊天来源默认外发策略放宽.md)。

最近本地验收（2026-10-06，conda lifebase，macOS）：两条来源的 128 个会话、11,148 条
消息形成 22,059 个节点、49,183 条关系，包含 10,781 个关键词主题与 37,907 条提及关系。
首次构图约 8 秒，重复构图复用产物；既有 RAW、Silver、索引的哈希、修改时间和权限
保持不变。真实上下文召回两个来源且满足三千字上限；当天稍后外发级别放宽后，云端请求
随之通过（[ADR-018](adr/ADR-018-聊天来源默认外发策略放宽.md)）。

合成演示库包含 3 个会话、8 条消息、11 条证据、24 个主题与 32 条提及关系，图谱和
RAW/Silver 检查均为 ok。操作见 [终端指南](demo.md)，正式 JSON 契约与合成输出见
[接口说明](harness-interface.md)。全量校验：ruff 无告警，212 项 pytest 测试通过
（20.84 秒）；私有仓库维护脚本也通过 ruff 与 shell 语法检查。

数据迁移验收：300 个文件以同盘重命名移动，哈希、权限、修改时间和 inode 保持
不变，库内布局和快照身份不变。285 个 LFS 指针及本地 LFS 实体检查通过，已推送
至独立私有远端；旧路径保留兼容链接。fresh clone 与 LFS hydrate 后，296 个已提交
数据文件哈希一致，两个库的证据与图谱检查通过，RAW 只读权限已恢复；本次临时
恢复库已清理。使用方式见 [数据仓库说明](data-repository.md)。

### 待验证事项

- 联调只在合成演示库上做了端到端；真实库（11,148 条消息）尚未进入云端模型。
- web UI 的插件行渲染（标题、描述、图标）未经浏览器核对，只核对了导出资源与注册结果。
- 回答质量与引用支持度只有一次人工观察，没有评测集；Gold 断言保存格式未定。
- 查询端执行目的地声明策略，不具备网络隔离能力，不能证明调用方实际使用本地模型。
- verify 仍为 warning，仅因既有两个 Finder .DS_Store；4 个 RAW、4 个 Silver 分区和
  11,276 条证据没有错误。豆包会话时间、回复关系和覆盖范围缺口见 ADR-015。
- jieba 统计关键词不做语义主题归纳或同义融合；长消息返回有界片段，冲突与时间缺失
  通过 warnings 可见。查询继续按快照载入内存，规模基线见 [基线说明](benchmarks/README.md)。
- 真实后续快照的增量语义与来源格式变化待验证；原始备份恢复仍需单独验收。

### 下一步与暂缓范围（未执行）

| 分类 | 当前待开展内容 | 完成条件 |
| --- | --- | --- |
| Integrate 续（本地 DeepSeek Harness fork） | 真实库端到端，以及回答质量与引用支持度的可复查记录 | 在真实库跑通一次，并留下带输入与输出的评测记录 |
| Build + Integrate | 模型回答的 Gold 断言保存 | 引用支持度通过后，确定带输入证据与模型信息的保存格式 |
| Reuse（restic、现有 collector） | 后续来源快照与独立备份恢复验收 | 根据实际输入和用户确定的备份目的地展开 |
| Defer | 语义主题、同义融合、Past Me、浏览器 UI、其他来源与自动采集 | 当前聊天切片不提供这些能力，另定范围 |

## 3. 既定设计决策（未经用户同意，不得重新讨论）

- **时间字段**：`occurred_at`（发生）/ `known_at`（知晓）/ `ingested_at`（入库）/ `valid_from` / `valid_to`。Past Me 检索必须按 `known_at <= 截止点` 过滤，防止未来知识向后泄漏。
- **分层**：Bronze = 原始证据（不可变、内容寻址）；Silver = 确定性规范化事实（可复现）；Gold = 派生数据（Trips/记忆/摘要/embedding，可随时重建丢弃）。
- **Life Primitives**：平台无关的 Entity / Artifact / Event / Observation / Transaction / Reservation / Relationship / State / Assertion / Evidence。禁止围绕具体 App 设计 schema。
- **Collector 接口**（`sync/base.py`）：`detect() / validate() / ingest() / normalize() / checkpoint() / metadata()`。重复导出复用同一派生分区；验证要求见 [AGENTS.md](../AGENTS.md#3-硬约束--验证方式)。
- **Data Inbox 流程**：用户把 export 丢进 inbox → 自动 detect 来源 → hash → 归档 RAW → 规范化 → 更新 Source Registry。目标体验：Download → Drop → Done。
- **采集方式优先级**：官方 API/OAuth > 官方导出 > 本地文件/数据库 > 现有开源提取器 > 用户触发的浏览器自动化 > 逆向。追求「可复现的采集」，不是「完美的采集」。
- **存储栈**：本地文件系统 + 内容寻址对象存储 + Parquet + DuckDB + SQLite。PostgreSQL/pgvector 后期再引入；不为「可能以后需要」提前引入依赖。
- **备份**：复用 restic，禁止自研加密/备份层。
- **外发策略**：每个 collector 声明来源默认外发级别（`local_only` / `redact_before_cloud` / `cloud_ok`），HumanOS 按目的地声明执行，实际模型路由待联调（ADR-012 / ADR-016）。聊天来源的默认级别自 2026-10-06 起为 `cloud_ok`（ADR-018）。
- **Agent 运行时边界**：Agent 执行由外部运行时承担；Lifebase 不依赖任何运行时，只对外提供只读查询接口；AI 生成内容不作为关于用户现实生活的事实证据（ADR-013）。
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
- [双来源终端切片与后续范围](design/post-collector-roadmap-proposal.md) — **Build / Reuse** 的图谱与工具已落地，见 ADR-016；**Integrate** 的 Harness 和模型回答仍待联调。
- [Agent 运行时集成：DeepSeek Harness × Lifebase](design/agent-runtime-integration-hypothesis.md) — Agent 执行交外部运行时（**Integrate**），边界已定于 [ADR-013](adr/ADR-013-Agent运行时集成边界.md)；只读工具已经实现，模型接入待联调；自动上下文、Past Me、Agent Team 与会话回采仍为 **Defer**。
