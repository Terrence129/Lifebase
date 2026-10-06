# Lifebase 参考（非约束，按需阅读）

> 本文件是 [AGENTS.md](../AGENTS.md) 的参考附件，承载架构、目录、既定设计决策与项目背景等**非约束性**信息。
> **约束与红线一律以 `AGENTS.md` 为准**；本文件不复制红线。

## 1. 架构与数据流

```
LifeSync   → 采集：Collectors / Adapters / Importers / Data Inbox
LifeVault  → 存储：不可变 RAW（Bronze）+ 规范化（Silver）+ 派生（Gold）
LifeGraph  → 知识：Entities / Events / Evidence Fusion / 时间语义
HumanOS    → 交互：Search / Timeline / Trips / Past Me / AI（长期规划，尚未实现）
```

数据流：`Collector → RAW → Normalizer → Canonical records`。Collector 生成规范化记录，
pipeline 协调归档、Silver 发布与来源登记；实施边界见 [AGENTS.md](../AGENTS.md)。

## 2. 项目背景与当前阶段

- **定位**：local-first 个人数据基础设施 —— 持续采集、保存、规范化分散在微信、照片、GPS、邮件、ChatGPT、GitHub、银行等处的数字生活痕迹，形成有证据支撑、带时间语义的个人知识图谱（LifeGraph），并在此之上构建个人 AI 应用（HumanOS）。「Own your data first. Intelligence comes later.」项目以个人开源项目为第一定位，商业化暂缓。

### 当前阶段

更新日期：2026-10-06。当前阶段为多来源文件导入与可靠性验证。ChatGPT 与豆包的
本地导出均可归档、规范化、查询与重放；这不代表已证明账户覆盖完整。

阶段历史：2026-10-06，首条 ChatGPT 原型完成 canonical v1、RAW/Silver 与六个
CLI 命令，单份真实官方导出验收通过。契约和存储见
[ADR-006](adr/ADR-006-首个采集切片的最小输出契约.md)、
[ADR-007](adr/ADR-007-RAW归档与Silver快照发布.md)，完整性检查、重放和质量统计见
[ADR-008](adr/ADR-008-只读完整性检查.md)、[ADR-009](adr/ADR-009-RAW重放与处理版本选择.md)、
[ADR-010](adr/ADR-010-导入质量报告与合成规模基线.md)，格式适配与真实验收见
[ADR-014](adr/ADR-014-ChatGPT分片导出与仅父节点适配.md)。

| 分类 | 当前阶段内容 | 验收与记录 |
| --- | --- | --- |
| Build + Reuse（json、Decimal、既有存储及查询） | doubao@0.1.0 接入每会话 JSON，映射稳定身份、消息时间、原样文本和文件根证据 | 合成测试覆盖十次导入、重叠版本、账户隔离、异常时间及 RAW 恢复；见 [ADR-015](adr/ADR-015-豆包JSON导入与多来源重放.md) |
| Build + Reuse（collector 注册表、CLI、既有 rebuild/verify） | 目录与 inbox 按来源扫描；JSON/ZIP 证据校验；按归档类型重放历史与混合来源 | 历史无前缀来源可重放，混合 rebuild 逐项报告版本；canonical v1、Envelope、依赖未改 |
| Reuse（本地 CLI、哈希校验） | 三份豆包真实导出及与 ChatGPT 的混合仓库验收 | 3 个会话、5,266 条消息、5,269 条证据；原输入、既有 ChatGPT 数据保持不变，重复导入与重放保持持久化文件不变 |

最近本地验证（2026-10-06，conda `lifebase`，macOS）：ruff 通过，176 项测试通过。
合并仓库的 4 个 RAW 对象、4 个 Silver 分区及 11,276 条证据检查没有错误；
verify=warning，仅因已有两个 Finder .DS_Store 文件，保持原状。豆包 quality=warning，
原因是会话时间缺失；全部消息均有 creation/update 时间，无空文本。
此处只记录本地结果；合成规模基线见 [基线说明](benchmarks/README.md)。

### 待验证事项与阻塞

- 当前没有导入格式阻塞；verify 的两项 Finder 文件警告仍可见，不影响数据哈希和证据校验。
- 豆包仅有工具导出的文本；rawCount 与 messages 数量均有差异，完整分页响应没有
  保存，覆盖范围未知。会话时间为空，回复树未映射；ChatGPT 时间与内容缺口见 ADR-014。
- 真实重叠快照、后续来源格式和工具版本变化仍待验证；真实缺失分区恢复未执行，
  由合成测试覆盖。
- query / quality 将选中 Parquet 分区载入内存，已有资源基线仅覆盖合成输入。
  rebuild 依赖完整 RAW 与 manifest，不修复损坏文件，也不等同于备份恢复。

### 下一步与暂缓范围（未执行）

| 分类 | 后续工作 | 理由与完成条件 |
| --- | --- | --- |
| Reuse（现有 CLI、collector） | 后续两平台导出到达时验证真实快照重叠、版本与证据增长 | 现有本地输入已通过，真实增量语义仍待验证 |
| Build + Reuse（pytest、合成 fixture） | 新的来源格式出现后，补充回归并按处理版本扩展 parser | 已有适配有明确边界，按实际输入扩展 |
| Reuse（restic） | 后续单独评估备份与恢复验收 | RAW 重放解决派生数据重建，原始证据的备份恢复仍需独立验证；目前尚未集成 |
| Integrate | 本阶段尚未接入外部服务 | Nango 仅为待评估候选，待多个 OAuth 来源产生实际维护成本后再评估 |
| Defer | 浏览器自动采集、自动监听、更多来源、媒体理解、LifeGraph、LLM 与 HumanOS UI | 先验证两条来源的增量、覆盖范围与恢复可靠性 |

## 3. 既定设计决策（未经用户同意，不得重新讨论）

- **时间字段**：`occurred_at`（发生）/ `known_at`（知晓）/ `ingested_at`（入库）/ `valid_from` / `valid_to`。Past Me 检索必须按 `known_at <= 截止点` 过滤，防止未来知识向后泄漏。
- **分层**：Bronze = 原始证据（不可变、内容寻址）；Silver = 确定性规范化事实（可复现）；Gold = 派生数据（Trips/记忆/摘要/embedding，可随时重建丢弃）。
- **Life Primitives**：平台无关的 Entity / Artifact / Event / Observation / Transaction / Reservation / Relationship / State / Assertion / Evidence。禁止围绕具体 App 设计 schema。
- **Collector 接口**（`sync/base.py`）：`detect() / validate() / ingest() / normalize() / checkpoint() / metadata()`。重复导出复用同一派生分区；验证要求见 [AGENTS.md](../AGENTS.md#3-硬约束--验证方式)。
- **Data Inbox 流程**：用户把 export 丢进 inbox → 自动 detect 来源 → hash → 归档 RAW → 规范化 → 更新 Source Registry。目标体验：Download → Drop → Done。
- **采集方式优先级**：官方 API/OAuth > 官方导出 > 本地文件/数据库 > 现有开源提取器 > 用户触发的浏览器自动化 > 逆向。追求「可复现的采集」，不是「完美的采集」。
- **存储栈**：本地文件系统 + 内容寻址对象存储 + Parquet + DuckDB + SQLite。PostgreSQL/pgvector 后期再引入；不为「可能以后需要」提前引入依赖。
- **备份**：复用 restic，禁止自研加密/备份层。
- **外发策略**：每个 collector 声明来源默认外发级别（`local_only` / `redact_before_cloud` / `cloud_ok`），未来的查询接口与模型路由据此执行（ADR-012）。
- **Agent 运行时边界**：Agent 执行由外部运行时承担；Lifebase 不依赖任何运行时，只对外提供只读查询接口；AI 生成内容不作为关于用户现实生活的事实证据（ADR-013）。
- **项目命名**：伞形名 **Lifebase**（包名 `lifebase`、CLI 命令 `lifebase`）；四层保留原名 LifeSync / LifeVault / LifeGraph / HumanOS，对应子包 `sync/` `vault/` `graph/` `humanos/`（ADR-002）。

## 4. 目录速查

- `src/lifebase/core/` — 统一封装（envelope）、内容寻址（跨层）
- `src/lifebase/sync/` — LifeSync 层：Collector 契约（base.py）、Source Registry（registry.py）、collectors/（来源注册表 + ChatGPT / Doubao Export）
- `src/lifebase/vault/` — LifeVault 层：RAW 归档、manifest、silver/（规范化 Parquet）
- `src/lifebase/graph/`、`src/lifebase/humanos/` — 边界占位目录；实施规则见 [AGENTS.md](../AGENTS.md#1-角色与必须停下询问条件最高优先)
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
- [Agent 运行时集成：DeepSeek Harness × Lifebase](design/agent-runtime-integration-hypothesis.md) — **Defer**。Agent 执行交外部运行时（**Integrate**），Lifebase 只提供数据与证据；记录七个集成方向、评估意见与触发条件，边界已定于 [ADR-013](adr/ADR-013-Agent运行时集成边界.md)。
