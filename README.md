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

## 安全红线

真实个人数据与密钥永不进入 git（数据只存本地，默认 `~/Lifebase/`）；本仓库只包含代码、schema、文档与合成测试数据。完整红线与规则以 [AGENTS.md](./AGENTS.md) 为唯一事实源。

## 更多

- Agent 规则与红线（唯一事实源）：`AGENTS.md`
- 架构决策：`docs/adr/`
