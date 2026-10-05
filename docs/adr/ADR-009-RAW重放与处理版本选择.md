# ADR-009：RAW 重放与处理版本选择

- 状态：Accepted，用户于 2026-10-05 明确委派从 RAW 重建派生数据。
- 日期：2026-10-05

## 决策

1. **Build**：`lifebase rebuild [--source SOURCE]` 从只读 RAW manifest 枚举归档，
   使用当前安装的 ChatGPT collector/parser/schema 重放。来源、原始文件名和首次
   入库时间沿用已有条目，不从文件名猜测，不使用重建时间替代 ingested_at。
2. **Reuse（已有 collector、PyArrow、SQLite）**：正常导入和重建共用同一解析、
   发布及 Source Registry 登记流程。重建直接读内容地址对象，不读取 inbox，不调用
   RAW 归档写入，不修改 manifest；没有引入第三方依赖或修改 canonical v1/Envelope。
3. **Build**：缺失完整分区和 registry 可以重建；现存分区先校验哈希，再将三张表
   与本次确定性规范化结果比较。相同处理版本的逻辑结果不同就报告失败，不能静默
   复用或覆盖。缺失分区以已有原子发布机制生成，损坏的现存分区保留供核查。
4. **Build**：每个来源/RAW 独立重放，单条失败继续处理其他条目。保留错误状态并
   返回非零退出码；后续重试成功更新该处理版本的登记。已有 RAW 及分区文件不删除。
5. **Build + Reuse（Source Registry + DuckDB）**：query 增加 source、collector、
   parser 和 schema 版本的可选显式筛选。默认仍选择全部成功分区，保持现有查询
   行为；不自动选择“最新”版本，不猜版本字符串的排序，不更改消息历史版本语义。
6. **Integrate**：本阶段无外部服务。
7. **Defer**：历史 parser 自动安装、自动切换默认处理版本、schema 迁移、覆盖或
   清理损坏分区、备份恢复及并发重建与导入的协调。

## 行为与边界

- JSON 报告当前处理版本及每条归档的来源、哈希、原始文件名、状态和结果/错误。
  单项状态为 rebuilt / unchanged / error；整体 partial / error 返回 1，ok 返回 0。
- 归档索引以 SQLite immutable 只读连接读取，发现 WAL/恢复日志就拒绝。数据目录
  要求停止写入；重建不提供跨 RAW、manifest 和 registry 的并发快照。
- 读取 RAW 前验证内容哈希和归档长度；读写数据路径拒绝目录内的符号链接。
- manifest 不在且仍有 RAW 时拒绝重建；未知 collector 不由 ChatGPT parser 猜测处理。
  空库和未匹配来源不创建文件，报告空结果。
- parser 升级会新增处理分区和对应证据，旧产物保留。query 的版本筛选只选择产物，
  不表示能在同一环境执行任意历史 parser。
- 失败时 registry 可更新该处理版本的错误状态；文件未被修改不代表它仍可参与查询。
  发生错误的处理分区不进入默认成功分区集合，其他成功来源继续可查询。
- 同处理版本比较的是逻辑行；不要求不同 PyArrow 版本生成逐字节相同的 Parquet。

## 验收

合成端到端测试将 inbox、Silver 与 registry 暂存到数据目录之外，再仅凭 RAW 与
manifest 重建，比较三张逻辑表（包括首次入库时间），并验证 RAW 与 manifest 的
字节、权限及 mtime 不变。另覆盖十次重放幂等、账户过滤、parser 升级的版本筛选、
同版本结果变化、失败重试、RAW 缺失/损坏、Silver 损坏、manifest/WAL 和符号链接。

约束见 [AGENTS.md](../../AGENTS.md)，分区发布见 [ADR-007](ADR-007-RAW归档与Silver快照发布.md)。
