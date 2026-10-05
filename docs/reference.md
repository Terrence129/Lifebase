# Lifebase 参考（非约束，按需阅读）

> 本文件是 [AGENTS.md](../AGENTS.md) 的参考附件，承载架构、目录、既定设计决策与项目背景等**非约束性**信息。
> **约束与红线一律以 `AGENTS.md` 为准**；本文件不复制红线。

## 1. 架构与数据流

```
LifeSync   → 采集：Collectors / Adapters / Importers / Data Inbox
LifeVault  → 存储：不可变 RAW（Bronze）+ 规范化（Silver）+ 派生（Gold）
LifeGraph  → 知识：Entities / Events / Evidence Fusion / 时间语义
HumanOS    → 交互：Search / Timeline / Trips / Past Me / AI（Month 12+ 才开始）
```

数据流：`Collector → RAW → Normalizer → Canonical records`。四层职责严格分离，不要跨层写代码；Collector 不直接写应用数据库。

## 2. 项目背景与当前阶段

- **定位**：local-first 个人数据基础设施 —— 持续采集、保存、规范化分散在微信、照片、GPS、邮件、ChatGPT、GitHub、银行等处的数字生活痕迹，形成有证据支撑、带时间语义的个人知识图谱（LifeGraph），并在此之上构建个人 AI 应用（HumanOS）。「Own your data first. Intelligence comes later.」项目以个人开源项目为第一定位，商业化暂缓，不得影响当前架构。
- **当前阶段（2026-10 快照，可能过期，以代码为准）**：首个 Weekend Prototype 已完成合成数据验收：手动 Data Inbox + 不可变 RAW archive + ChatGPT ZIP collector + canonical v1 + Parquet + DuckDB + ingest/list/query CLI。用户的官方导出尚在生成，真实格式兼容性待本地验证。

## 3. 既定设计决策（未经用户同意，不得重新讨论）

- **时间字段**：`occurred_at`（发生）/ `known_at`（知晓）/ `ingested_at`（入库）/ `valid_from` / `valid_to`。Past Me 检索必须按 `known_at <= 截止点` 过滤，防止未来知识向后泄漏。
- **分层**：Bronze = 原始证据（不可变、内容寻址）；Silver = 确定性规范化事实（可复现）；Gold = 派生数据（Trips/记忆/摘要/embedding，可随时重建丢弃）。
- **Life Primitives**：平台无关的 Entity / Artifact / Event / Observation / Transaction / Reservation / Relationship / State / Assertion / Evidence。禁止围绕具体 App 设计 schema。
- **Collector 接口**（`sync/base.py`）：`detect() / validate() / ingest() / normalize() / checkpoint() / metadata()`。每个 collector 必须幂等：同一份导出导入 10 次只产生 1 份数据。
- **Data Inbox 流程**：用户把 export 丢进 inbox → 自动 detect 来源 → hash → 归档 RAW → 规范化 → 更新 Source Registry。目标体验：Download → Drop → Done。
- **采集方式优先级**：官方 API/OAuth > 官方导出 > 本地文件/数据库 > 现有开源提取器 > 用户触发的浏览器自动化 > 逆向。追求「可复现的采集」，不是「完美的采集」。
- **存储栈**：本地文件系统 + 内容寻址对象存储 + Parquet + DuckDB + SQLite。PostgreSQL/pgvector 后期再引入；不为「可能以后需要」提前引入依赖。
- **备份**：复用 restic，禁止自研加密/备份层。
- **项目命名**：伞形名 **Lifebase**（包名 `lifebase`、CLI 命令 `lifebase`）；四层保留原名 LifeSync / LifeVault / LifeGraph / HumanOS，对应子包 `sync/` `vault/` `graph/` `humanos/`（ADR-002）。

## 4. 目录速查

- `src/lifebase/core/` — 统一封装（envelope）、内容寻址（跨层）
- `src/lifebase/sync/` — LifeSync 层：Collector 契约（base.py）、Source Registry（registry.py）、collectors/（当前只做 ChatGPT Export）
- `src/lifebase/vault/` — LifeVault 层：RAW 归档、manifest、silver/（规范化 Parquet）
- `src/lifebase/graph/`、`src/lifebase/humanos/` — 边界占位，当前阶段禁止在此写代码
- `schemas/` — JSON Schema，与代码同仓库同版本
- `docs/adr/` — 架构决策记录（ADR）
- `docs/context.md` — 完整项目规格（背景资料，非 canonical）
