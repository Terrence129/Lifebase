# Lifebase

**Local-first 个人数据基础设施**：持续采集、保存、规范化你分散在微信、照片、GPS、邮件、ChatGPT、GitHub、银行等各处的数字生活痕迹，形成有证据支撑、带时间语义的个人知识图谱，并在此之上构建个人 AI 应用。

> Own your data first. Intelligence comes later.

伞形名称 **Lifebase**；四层分别为 LifeSync / LifeVault / LifeGraph / HumanOS（命名决策见 `docs/adr/ADR-002`）。

## 架构

```
LifeSync（采集）→ LifeVault（不可变存储）→ LifeGraph（知识图谱）→ HumanOS（AI 应用）
```

## 当前状态

首个 **Weekend Prototype** 已打通合成数据链路：ChatGPT ZIP → RAW 归档 →
canonical v1 → Parquet → DuckDB 查询。真实官方导出的兼容性待本地验收。

## 快速开始

### 开发环境

在已安装 conda 的设备上，从仓库根目录执行（macOS / Linux）：

```bash
conda env create --file environment.yml
conda activate lifebase
conda env config vars set --name lifebase "UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX"
conda deactivate
conda activate lifebase
uv sync --locked --extra dev --inexact
```

退出后重新激活，用于加载刚保存的环境变量。Windows PowerShell 用户将第三条命令改为：

```powershell
conda env config vars set --name lifebase "UV_PROJECT_ENVIRONMENT=$env:CONDA_PREFIX"
```

之后每次开发只需 `conda activate lifebase`。`UV_PROJECT_ENVIRONMENT` 指向这台设备上
的专用 conda 环境，让 uv 将项目及其依赖安装在其中。同步时保留 `--inexact`，以保留
conda 安装的工具包。

配置文件分工：

- `environment.yml`：环境名称、Python 3.12、pip 和固定版本的 uv。
- `pyproject.toml`：项目依赖与开发依赖的声明。
- `uv.lock`：锁定 Python 库版本和分发文件哈希，供其他设备及 CI 安装同一组库版本。

这些文件不包含本机环境路径；conda 的底层系统包会按设备平台解析，并非逐字节复制
整套环境。已有环境在拉取依赖变更后，重新执行 `uv sync --locked --extra dev --inexact`。
有意升级依赖时执行 `uv lock --upgrade`，再同步并验证。

### 本地验证

```bash
uv run ruff check .
uv run pytest
```

### 导入与查询

进入开发环境后，先用仓库内的合成样例试跑；输出目录放在仓库外：

```bash
lifebase --data-dir ~/Lifebase-demo ingest --source chatgpt:synthetic-account tests/fixtures/chatgpt/export-a.zip
lifebase --data-dir ~/Lifebase-demo list
lifebase --data-dir ~/Lifebase-demo query "SELECT role, text_parts, occurred_at FROM artifacts ORDER BY occurred_at"
```

再导入同一文件，结果显示 `unchanged`；导入 `export-b.zip` 可以验证重叠来源与内容版本。

真实导出到达后，将 ZIP 放进 `~/Lifebase/inbox/`，执行：

```bash
lifebase ingest --source chatgpt:personal
lifebase list
lifebase query "SELECT count(DISTINCT record_id) AS messages FROM artifacts"
```

`--source` 必须区分不同账户，不填写密钥。未提供文件路径时手动扫描 inbox；原文件
留在原处，RAW 内容归档到 `vault/objects/`，首次来源入库信息保存在
`vault/manifest.sqlite`，Source Registry 位于 `registry.sqlite`。

Silver 按来源、RAW 哈希与处理版本发布完整 Parquet 快照分区；查询合并这些分区，
对相同身份及版本去重。逻辑表为 `events`、`artifacts`、`evidence`；保留不同回复
分支和内容版本，因此 `count(*)` 是版本数，`count(DISTINCT record_id)` 是身份数。
`record_conflicts` 视图列出拥有多个版本且版本时间不足以确定次序的记录。

证据引用查询示例：

```bash
lifebase query "SELECT a.role, a.text_parts, e.content_hash, e.raw_member, e.raw_pointer FROM artifacts a JOIN evidence e USING (record_id, revision_id) WHERE e.record_kind = 'artifact' LIMIT 20"
```

命令输出 JSON；单个文件失败会保留 RAW、记录原因并返回非零退出码，批量导入继续
处理其他文件。`query` 只接受单条 SELECT / WITH SELECT，对 SQL 禁用外部文件和
网络访问；`list` / 空库查询不会创建数据目录。

本版支持 ZIP 根目录中唯一的 `conversations.json` 数组；编号会话文件、加密 ZIP、
非文本内容理解仍待扩展。JSON 成员上限为 128 MiB，整个 ZIP 仍完整归档。结构错误
会报告，缺失或异常时间保留空值并附诊断；未知内容类型仅保留消息元数据与 RAW 引用。
查询目前将登记的 Parquet 分区载入内存，适合原型规模数据。

契约见 [canonical v1](docs/design/chatgpt-minimal-contract-draft.md)，具体行为由合成
端到端测试覆盖。后续真实数据验证只在仓库外进行。

### 只读完整性检查

停止向数据目录写入后执行：

```bash
lifebase --data-dir ~/Lifebase-demo verify
# 默认检查 ~/Lifebase
lifebase verify
```

输出 JSON：`status`、`counts` 和 `issues`。检查包括 RAW 内容地址与归档长度、
两个 SQLite 索引、全部已发布 Silver 分区的哈希/schema/行数/处理身份、规范化
记录关联，以及证据的 ZIP 成员哈希、JSON Pointer 和来源记录 ID。问题包含稳定
`code`、相对数据目录的 `path`，证据问题还包含 `evidence_id`；不输出消息正文。

状态 `ok` 返回 0；错误返回 1。未登记的对象、分区和临时目录作为 `warning`
报告，同样返回 1，供人工检查；不会修复、重新登记或清理。正常归档但解析失败的
输入只检查归档完整性，解析失败原因仍由 `list` 查看。

不存在的数据目录视为空库，返回 0 且不创建文件。为避免 SQLite 创建辅助文件或
恢复日志，检查使用只读 immutable 连接；发现 WAL/恢复日志时返回
`database_not_quiescent`，要求停止写入后重试。本版检查要求静止的数据目录，
不提供并发写入期间的一致性快照。文件内容、mtime 和权限保持不变；操作系统
可能因读取更新 atime。实现与边界见 [ADR-008](docs/adr/ADR-008-只读完整性检查.md)。

### 从 RAW 重建派生数据

保留 `vault/objects/` 和 `vault/manifest.sqlite`，即使 inbox 原文件不在，也可以执行：

```bash
lifebase --data-dir ~/Lifebase-demo rebuild
# 只重建某个账户来源
lifebase --data-dir ~/Lifebase-demo rebuild --source chatgpt:synthetic-account
lifebase --data-dir ~/Lifebase-demo verify
```

`rebuild` 使用当前安装的 ChatGPT collector/parser 和 schema 版本，从只读 manifest
恢复来源、原始文件名及首次入库时间，再读取并校验 RAW，重新解析、发布 Silver
和登记 Source Registry。它不会重新归档 inbox 文件，也不会修改 RAW 或 manifest。
缺失的完整分区和 registry 可重新生成；完整的已有分区在哈希与逻辑结果校验后复用。
已有分区或文件损坏时报告失败并保留现场，不覆盖或清理；manifest 丢失时无法推测
来源和首次入库时间。操作前停止向数据目录写入，manifest 有 WAL/恢复日志时拒绝重建。

输出 JSON 包含当前 `collector_version`、`parser_version`、`schema_version` 和逐条
`rebuilds`，状态为 `rebuilt`、`unchanged` 或 `error`。单条失败仍处理其他归档，整体
`partial` / `error` 返回 1，全部成功返回 0。空库或未匹配来源返回空列表，不创建目录。

处理版本升级会新增分区，旧分区保留。默认 query 继续合并全部成功分区；需要核对
某次重建结果时，使用 rebuild 输出的版本显式筛选，例如当前版本：

```bash
lifebase --data-dir ~/Lifebase-demo query --source chatgpt:synthetic-account --parser-version chatgpt@0.1.0 --schema-version 1 "SELECT count(*) FROM artifacts"
```

还可使用 `--collector-version`；多个筛选条件同时满足才会选入分区。筛选仅选择已有
产物，不安装或执行历史解析器。若同一个处理版本生成不同逻辑数据，重建会报错，
应先核对变化原因并升级 parser 版本。决策见 [ADR-009](docs/adr/ADR-009-RAW重放与处理版本选择.md)。

### 导入质量与规模基线

ingest 和 rebuild 的单条成功结果包含 `quality`；也可以汇总已登记的成功分区：

```bash
lifebase --data-dir ~/Lifebase-demo quality
lifebase --data-dir ~/Lifebase-demo quality --source chatgpt:synthetic-account --parser-version chatgpt@0.1.0 --schema-version 1
```

报告区分会话和消息的 `identities`（身份数）与 `versions`（内容版本数），统计
`missing_occurred_at_versions`、`missing_known_at_versions`、文本版本、空文本版本、
不支持的内容类型及数量，并列出证据数。时间缺失、异常或不可靠而变成 NULL 的
版本都计入缺失时间；具体解析原因仍在单次导入 `issues` / 来源 `diagnostics` 中。
空文本仅指空数组或全部为空字符串，空白字符保持原样。非文本内容保留 RAW 和
消息元数据，报告中的“不支持”表示本版没有规范化其内容，不表示 RAW 丢失。

`quality.status` 为 empty / ok / warning；warning 是质量提醒，成功生成报告仍返回
0，不会把有效归档改判为导入失败。存储损坏导致查询失败则返回 1，可用 verify 定位。
汇总只覆盖 `selected_partitions` 指定的成功分区，按逻辑行去重；失败导入由 list 查看。
报告仅输出统计，不输出消息正文；ok 不等于已覆盖整个账户或理解全部媒体。

完整规模基准仅使用生成的合成数据，在仓库根目录按需执行：

```bash
uv run python -m benchmarks.run --sizes 1000 10000 50000 --repeats 3 --output docs/benchmarks/quality-scale-baseline.json
```

每档包含两个重叠导出：第二份新增约 5% 消息，修改每第 101 条旧消息，并包含
分支、缺失时间与非文本。分别测量首次导入、重复导入、聚合查询和质量报告的
操作耗时与进程峰值 RSS；导出生成不计入测量，各阶段使用独立进程。
全部输入和仓库均位于工具自己的临时目录，结束后清理。CI 只验证小样例正确性，
不运行完整基准，也不设机器相关的耗时阈值。

方法、结果及限制见 [规模基线](docs/benchmarks/README.md)，决策见
[ADR-010](docs/adr/ADR-010-导入质量报告与合成规模基线.md)。

## 安全红线

真实个人数据与密钥永不进入 git（数据只存本地，默认 `~/Lifebase/`）；本仓库只包含代码、schema、文档与合成测试数据。完整红线与规则以 [AGENTS.md](./AGENTS.md) 为唯一事实源。

## 更多

- Agent 规则与红线（唯一事实源）：`AGENTS.md`
- 架构决策：`docs/adr/`
