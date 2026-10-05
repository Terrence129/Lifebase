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

数据流：`Collector → RAW → Normalizer → Canonical records`。四层职责严格分离，不要跨层写代码；Collector 不直接写应用数据库。

## 2. 项目背景与当前阶段

- **定位**：local-first 个人数据基础设施 —— 持续采集、保存、规范化分散在微信、照片、GPS、邮件、ChatGPT、GitHub、银行等处的数字生活痕迹，形成有证据支撑、带时间语义的个人知识图谱（LifeGraph），并在此之上构建个人 AI 应用（HumanOS）。「Own your data first. Intelligence comes later.」项目以个人开源项目为第一定位，商业化暂缓，不得影响当前架构。

### 当前阶段

更新日期：**2026-10-05**。当前处于首条 ChatGPT 导入链路的原型与可靠性验证阶段；
以下完成状态以现有实现、合成测试及本地验收为依据，不代表真实官方导出已通过验收。

| 分类 | 已完成内容 | 验收与记录 |
| --- | --- | --- |
| Reuse（conda、uv、pytest、ruff） | 专用开发环境、依赖声明与锁文件、CI 检查流程 | 环境同步说明见 [README](../README.md#开发环境)，决策见 [ADR-005](adr/ADR-005-conda开发环境与uv依赖锁定.md) |
| Build | canonical v1 的 Event / Artifact / Evidence 契约、合成样例、来源与时间语义 | 保留分支和内容版本，现有 Envelope 未改；见 [契约](design/chatgpt-minimal-contract-draft.md) |
| Build + Reuse（hashlib、SQLite、PyArrow、DuckDB） | 不可变 RAW 归档、ChatGPT ZIP collector、Parquet、可追溯只读查询及 ingest/list/query | 合成端到端验收覆盖哈希、十次导入幂等、重叠导出、账户隔离和证据回溯；见 [ADR-007](adr/ADR-007-RAW归档与Silver快照发布.md) |
| Build + Reuse（sqlite3、zipfile、PyArrow） | verify：只读检查 RAW、索引、Silver 和证据引用 | 缺失、损坏及未登记产物能定位；合成测试验证检查不改写数据；见 [ADR-008](adr/ADR-008-只读完整性检查.md) |
| Build + Reuse（已有 collector、SQLite、PyArrow） | rebuild：仅凭 RAW 与 manifest 重建派生数据；query 显式筛选来源与处理版本 | 保留首次入库时间，完整产物复用，损坏产物不覆盖；见 [ADR-009](adr/ADR-009-RAW重放与处理版本选择.md) |
| Build + Reuse（DuckDB、pytest、Python 标准库） | quality：导入与汇总质量统计；合成规模工具与基线 | 区分身份、版本、缺失时间及不支持内容；三档规模各运行三次，见 [基线](benchmarks/README.md) 与 [ADR-010](adr/ADR-010-导入质量报告与合成规模基线.md) |
| Build + Reuse（现有 collector、CLI、pytest） | 来源注册表：`sync/collectors/__init__.py` 按 source_type 路由 collector（make_collector / metadata_for / detect_collector），pipeline / CLI / rebuild 不再硬编码 ChatGPTCollector | 行为不变；单 collector 时未知前缀回退，多 collector 时报错；9 项注册表测试覆盖，第二来源可插拔接入 |

最近本地验证（2026-10-05，conda `lifebase` 环境，Windows 原生）：`uv run ruff check .`
通过，`uv run pytest` **89 项通过、4 项跳过**（4 项符号链接测试因 Windows 无创建
权限跳过，Linux/CI 上全量执行 93 项）。本次同步修复 Windows 原生兼容问题：vault
发布时只读临时文件删除失败（`vault/store.py`）、测试 fixture 读取编码、符号链接
测试跳过守卫；conda 环境补齐 certifi 后 `uv sync` 无需手动解除 SSL 变量。
CI 已配置同样检查，包含 RAW 哈希与导入幂等测试；此处记录本地结果，不声称已核对
每次远端 CI 运行。完整规模基准按需执行，CI 仅运行小样例正确性检查。

### 待验证事项与阻塞

- **真实导出兼容性待验证**：尚未进行本地真实 ChatGPT 官方 ZIP 验收。用户此前报告
  官方导出正在生成；该验收需等待可用文件，合成测试不能替代。
- **格式覆盖有限**：目前解析 ZIP 根目录唯一的 conversations.json 数组；编号会话
  文件、加密 ZIP 与非文本内容理解尚不支持。
- **规模边界**：query / quality 当前将选中 Parquet 分区载入内存。已有基线仅覆盖
  合成输入，真实导出、更长正文、媒体密集数据及更多快照的资源消耗仍待验证。
- **恢复边界**：rebuild 依赖完整 RAW 和 manifest；不修复损坏文件，也不等同于备份恢复。

### 下一步与暂缓范围（未执行）

| 分类 | 后续工作 | 理由与完成条件 |
| --- | --- | --- |
| Build + Reuse（现有 CLI、collector、pytest） | 官方导出到达后，在仓库外验证 ingest → verify → quality → query → rebuild | 用真实格式检验当前映射；保留 RAW，核对首次入库时间与重建逻辑结果，进度记录仅保存计数和问题类型 |
| Build + Reuse（pytest、合成 fixture） | 按真实验收发现的问题修正解析器并补充合成回归样例 | 根据实际失败扩展格式覆盖；同处理版本逻辑变化需按既有版本设计处理；没有发现问题前不预先扩展实现 |
| Reuse（restic） | 后续单独评估备份与恢复验收 | RAW 重放解决派生数据重建，原始证据的备份恢复仍需独立验证；目前尚未集成 |
| Integrate | 本阶段尚未接入外部服务 | Nango 仅为待评估候选，待多个 OAuth 来源产生实际维护成本后再评估 |
| Defer | 自动监听、多平台、媒体理解、LifeGraph、LLM 与 HumanOS UI | 优先完成首条来源的真实兼容性和可靠性验证，再扩大范围 |

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
- `src/lifebase/sync/` — LifeSync 层：Collector 契约（base.py）、Source Registry（registry.py）、collectors/（来源注册表 + ChatGPT Export）
- `src/lifebase/vault/` — LifeVault 层：RAW 归档、manifest、silver/（规范化 Parquet）
- `src/lifebase/graph/`、`src/lifebase/humanos/` — 边界占位，当前阶段禁止在此写代码
- `schemas/` — JSON Schema，与代码同仓库同版本
- `docs/adr/` — 架构决策记录（ADR）
- `docs/context.md` — 完整项目规格（背景资料，非 canonical）

## 5. 待评估的架构猜想（非既定决策）

本栏目复用为项目灵感入口，记录尚未验证的思路；记录不代表已选型或已实现。

- [Nango：LifeSync API 接入候选](design/nango-integration-hypothesis.md) — **Defer**。当多个 OAuth 来源的持续同步产生重复维护成本时，再评估以 **Integrate** 方式接入 Nango；记录适用场景、部署取舍、证据保留问题和重新评估条件，尚未选型或接入。

### 浏览器辅助采集：从已登录的 App 获取可归档数据

- 记录日期：**2026-10-05**。
- 状态：**待验证灵感 / Defer**；本次只分析源码，未安装扩展、访问实际账户或实现豆包接入。
- 灵感来源：[chensanle/doubao-helper](https://github.com/chensanle/doubao-helper)。

**核心思路**：部分 App 没有方便的导出入口，但网页展示历史内容时仍会请求数据。
可评估由用户主动触发浏览器采集，利用现有登录状态取得消息并生成本地文件，再交给
Lifebase 的 Data Inbox、RAW 归档和 Python 解析器处理。浏览器负责获取，Lifebase
负责长期保存、标准化与查询；无需让模型复述历史来代替来源记录。

候选数据流（尚未实现）：

```text
已登录的 App 网页 → 用户触发采集 → 原始分页响应 + 采集说明 → 本地采集包
    → Data Inbox → RAW 归档 → 来源解析器 → 标准记录与证据 → 查询
```

**源码观察**（2026-10-05 所见，正式验证时重新核对）：doubao-helper 通过观察页面
请求取得会话与分页参数，调用网页的 `/im/chain/single` 接口获取当前会话消息；
默认接口模式，滚动方式需另行选择；JSON 保留入选消息的原始对象。该接口属于网页
内部接口，兼容性与维护成本待验证。

**适合借鉴的地方**：浏览器登录态与本地归档分工、优先获取结构化数据、用户触发
导出、分页停止原因和来源模式记录。对 Lifebase，应优先评估保存完整响应后再解析，
让暂时不支持的内容仍有后续重建机会。

**尚不能直接采用的假设**：导出成功不等于会话完整。当前工具会过滤未提取到文本的
消息，没有单独提取消息时间字段，也未保存完整分页响应；分支覆盖不能仅凭消息列表
确认。导出时间与消息发生时间需分别理解；原始对象是否含可用时间字段仍需实测。

| 分类 | 候选做法 | 理由 |
| --- | --- | --- |
| Reuse | 将 doubao-helper 作为导出工具与格式研究样例，直接复用前核实许可和兼容性 | 减少接口探索与重复开发 |
| Integrate | 验证通过后，将其本地 JSON 导出作为 LifeSync 的可选输入 | 先通过文件连接浏览器与 Python，无需直接写中央库 |
| Build | 设计来源解析与证据映射；必要时补充完整采集包 | 保留原始响应、来源身份、工具版本、停止原因和处理依据 |
| Defer | 全部会话自动遍历、持续后台采集、通用跨 App 扩展 | 先验证一个会话的完整获取，不改变当前开发主线 |

**重新评估与最小验证**：选择一个可控测试会话，覆盖长历史、重复文本、回复分支、
图片或其他非文本内容；检查分页是否完整、当前会话身份是否一致、原始时间字段含义，
以及中断后是否明确报告部分结果。用合成采集包验证重复导入、版本保留、证据回溯和
RAW 重放。取得验证证据后再提出正式 ADR、契约设计及实施范围。

源码定位：[页面请求观察](https://github.com/chensanle/doubao-helper/blob/main/page-hook.js)、
[分页采集与导出](https://github.com/chensanle/doubao-helper/blob/main/content.js)、
[用户触发与进度控制](https://github.com/chensanle/doubao-helper/blob/main/popup.js)。
