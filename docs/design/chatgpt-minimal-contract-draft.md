# ChatGPT 首个垂直切片：最小输入与输出契约 v1

- 状态：Accepted；用户于 2026-10-05 批准，已落实为 canonical v1。
- 日期：2026-10-05
- 相关决策：[ADR-006（Accepted）](../adr/ADR-006-首个采集切片的最小输出契约.md)。
- 项目约束以 [AGENTS.md](../../AGENTS.md) 为准。

本契约已落实为 `core/records.py` 中的 dataclass 与 `schemas/*.v1.schema.json`，
现有 `Envelope` 保持不变。RAW 存储、ChatGPT collector、Parquet 与 CLI 查询已实现。
文件名保留初始草案名称以保持已有引用有效；当前状态以本页说明为准。

## 1. 范围与实现选择

| 分类 | 内容 | 理由 |
| --- | --- | --- |
| Build | 来源映射、稳定身份、版本保留、证据关联 | 这些是 Lifebase 的数据语义，需要明确约定 |
| Reuse | Python 标准库的 JSON、ZIP、SHA-256、UTC 日期处理；现有 Envelope | 无需增加依赖即可完成第一条采集链路 |
| Reuse | 已有 PyArrow / Parquet、DuckDB | 负责类型化存储与查询，不另造存储引擎 |
| Integrate | 本轮不接外部服务 | 单个本地导出即可验证数据链路 |
| Defer | 实体识别、文本事实抽取、LLM、向量、图谱、界面 | 本轮只验证来源记录可保存、可查询、可追溯 |

Silver 保存的是“来源记录了这段内容”。用户的计划、回忆与助手的回答都是消息内容，
不自动成为关于现实世界的事实、已发生事件或 AI 断言。

## 2. 输入样例与兼容性边界

样例目录：[tests/fixtures/chatgpt](../../tests/fixtures/chatgpt/README.md)。所有 ID、
时间与文字均为手工合成，不来自用户导出。ZIP 只含 `conversations.json`，旁边保留
可审阅的同名字节文件；ZIP 时间与文件属性固定，以便比对哈希。

| 样例 | 对话数 | 有内容的消息节点数 | 场景 |
| --- | --- | --- | --- |
| export-a | 2 | 5 | 回复分支、空根节点、分段文本、回忆文字、缺失时间 |
| export-b | 2 | 6 | 重叠消息、数组重排、新消息、同来源 ID 内容变更、额外元数据 |

`mapping` 的 key / node.id 故意与 message.id 不同，避免解析器混淆节点 ID 和消息 ID。
会话 1 的两条助手回复来自同一父消息，均应保留；`current_node` 不能作为丢弃其他
分支的依据。会话 2 的用户消息发表于 2026 年，文字提到 2022 年；另一条回复的
创建与更新时间均为空。

其他消息的初始 update_time 显式等于 create_time；这只是合成数据提供的证据，
不代表真实导出必然提供更新时间。

export-b 中“同一消息 ID 内容变化”是用于验证冲突处理的合成压力场景，不代表
官方导出一定这样表达编辑历史。

官方说明确认 ZIP 中可以有 `conversations.json`，也可能有编号的会话文件；它没有
在该说明中定义这里使用的完整字段契约。这里的 mapping 结构仅为手工测试候选，
不声称已覆盖所有真实导出版本。实际使用时，仍需在本地核对实际导出的结构，
无需把真实内容放进仓库或发送到外部服务。

参考：[OpenAI 导出文件说明](https://help.openai.com/en/articles/9106926-transfer-exported-conversations-between-chatgpt-accounts)。

初版 parser chatgpt@0.1.0 仅支持此样例中的单个 JSON 数组及文本消息。现行
chatgpt@0.2.0 的来源格式适配见 [ADR-014](../adr/ADR-014-ChatGPT分片导出与仅父节点适配.md)：
支持编号文件、仅 parent 的节点，以及 multimodal_text 中的字符串提取；下文 canonical
v1 字段与时间语义保持不变。未知内容类型不强转为字符串：保留来源引用的元数据记录，
`text_parts=null`，并报告尚未支持其解析。

## 3. 身份、版本与逻辑输出包

`source` 是 Source Registry 中区分账户的数据源 ID，例如合成数据使用
`chatgpt:synthetic-account`。它不能只是一个全局 `chatgpt`，否则不同账户的来源 ID
可能混淆；实际值由本地来源配置提供，不使用邮箱或 token 作为 ID。

`Envelope.source_record_id` 是可无歧义解码的 JSON 数组字符串：

- 会话：`["event", conversation.id]`。
- 消息：`["artifact", conversation.id, message.id]`。

这样会话与消息 ID 不混淆，相同 message.id 出现在不同会话也不碰撞。原始来源 ID
逐项保留；不使用数组位置、标题、mapping key、消息正文或导入时间充当来源身份。
缺失必需 ID 时，归档保留、报告问题，不随机生成 ID 冒充来源身份。

`J(value)` 表示 UTF-8 编码的 JSON：`ensure_ascii=False`、`sort_keys=True`、
`separators=(",", ":")`、`allow_nan=False`；数组顺序保持，文本不做 Unicode、
空白或换行清洗。datetime 在计算哈希前统一为 UTC ISO 8601 字符串，固定六位
微秒并以 `Z` 结尾；下文时间示例为便于阅读省略零微秒。

```text
record_id   = "sha256:" + SHA256(J([source, source_record_id]))
revision_id = "sha256:" + SHA256(J([schema_version, record_kind, payload]))
```

`payload` 恰好是下节 Event / Artifact 表中除前三个共同字段以外的字段。它包含
内容、关系与来源时间，不包含 ZIP 哈希、原始文件位置、导入时间、collector/parser
版本或尚未映射的来源元数据。只有规范化内容变化才产生新 revision；parser 升级后
输出未变化，可以沿用同一 revision，但保留新的处理证据。

逻辑上每个来源记录的输出包包含原有 `Envelope`、`record_kind`、`record_id`、
`revision_id`、`schema_version`、`payload` 与 RAW 定位信息。这些是包的独立字段，
不向 `Envelope` 添加字段。逻辑存储拆成以下三张平台无关的表；每个版本至少有
一条 Evidence，完整 Envelope 保存在 Evidence 中。

## 4. 最小表与字段

以下是已发布 v1 的字段。所有 datetime 使用带 UTC 时区、
微秒精度；字符串不截断；必需字段缺失或类型错误应报告，不能静默填值。

### Event：会话事件，存为 events.parquet

| 字段 | 类型 / 空值 | 意义 |
| --- | --- | --- |
| record_id | string，必需 | 跨导出的会话身份 |
| revision_id | string，必需 | 本版本的规范化内容哈希 |
| schema_version | integer，必需 | v1 为 1 |
| event_type | string，必需 | 本切片为 conversation |
| title | string，可空 | 来源标题，缺失保持 null |
| occurred_at | UTC datetime，可空 | 来源会话 create_time |
| known_at | UTC datetime，可空 | 本会话版本的来源记录时间，见下一节 |

唯一键为 `(record_id, revision_id)`。会话只是平台记录的交流事件，不从其中生成
野餐、旅行或回忆中的现实事件。会话节点结构与 `current_node` 完整留在 RAW 中；
本轮不做默认分支选择，查询可以同时返回不同回复分支。

### Artifact：消息内容，存为 artifacts.parquet

| 字段 | 类型 / 空值 | 意义 |
| --- | --- | --- |
| record_id | string，必需 | 跨导出的消息身份 |
| revision_id | string，必需 | 本消息版本的规范化内容哈希 |
| schema_version | integer，必需 | v1 为 1 |
| artifact_type | string，必需 | 本切片为 message |
| context_record_id | string，必需 | 所属会话的 Event.record_id |
| parent_record_id | string，可空 | 最近一个含消息的祖先的 Artifact.record_id |
| role | string，必需 | 原始 author.role，不把不同未知角色合并 |
| content_format | string，必需 | 来源 content_type；本样例为 text |
| text_parts | list[string]，可空 | 按顺序保留文本分段；空数组与不支持内容的 null 区分 |
| occurred_at | UTC datetime，可空 | 来源 message.create_time |
| known_at | UTC datetime，可空 | 本消息版本的来源记录时间，见下一节 |

唯一键同样为 `(record_id, revision_id)`。每个 `message != null` 的节点保留一条
逻辑消息，包括非当前分支；空根节点不生成 Artifact。parent 关系从节点树映射到
消息身份，不按时间或字典迭代顺序拼出一条虚构的线性对话。检测到循环、断链或
互相矛盾的节点关系时，保留 RAW 并报告，不静默修复。不同版本的父子关系需要
查询同一份 RAW 对应的 Evidence 才能精确还原一个来源快照。

不预先合并 `text_parts`；展示或搜索文本可以在查询时生成。未知元数据仍保存在
RAW；不为每个来源字段增加 canonical 列。

### Evidence：来源引用，存为 evidence.parquet

| 字段 | 类型 / 空值 | 意义 |
| --- | --- | --- |
| evidence_id | string，必需 | 下述证据身份哈希 |
| record_kind | string，必需 | event / artifact，决定关联表 |
| record_id / revision_id | string，必需 | 指向精确的规范化版本 |
| 原有 Envelope 全部字段 | 沿用当前 dataclass | 保留 source、source_record_id、content_hash、处理版本及时间 |
| raw_member | string，必需 | ZIP 内成员名，本样例为 conversations.json |
| raw_member_hash | string，必需 | 解压后的成员原始字节 SHA-256 |
| raw_pointer | string，必需 | 相对于成员 JSON 根的 RFC 6901 JSON Pointer |

Envelope 的 `content_hash` 指向整个原始 ZIP 字节的 SHA-256，不指向重序列化的
消息。`raw_member_hash` 用于校验解压字节。ZIP 或成员可以共享，但每份证据记录
保持独立的来源账户、来源身份与解析版本。

```text
evidence_id = "sha256:" + SHA256(J([
  record_id, revision_id, Envelope.content_hash,
  raw_member, raw_pointer, collector_version, parser_version
]))
```

`record_id` 已包含 source；`ingested_at` 不参与此哈希。Evidence 唯一键为
`evidence_id`；其 `occurred_at` / `known_at` 必须与关联 payload 一致。

例：样例 a 的消息 1 的定位是：

```text
content_hash = SHA256(export-a.zip 的原始字节)
raw_member   = conversations.json
raw_pointer  = /0/mapping/node-1-user/message
```

样例 b 将会话数组重排，定位变为 `/1/mapping/node-1-user/message`；消息身份
和内容版本不变，新增的是指向另一份 RAW 的证据。Pointer 的 key 按 RFC 6901
转义 `~` 和 `/`，不能直接拼接任意来源 ID。

## 5. 时间规则与空值

- `occurred_at` 只来自该会话 / 消息自己的合法 create_time，不解析正文中的日期。
- `known_at` 使用该来源对象自己的合法 update_time，表达这个**内容版本在来源中
  的记录时间**，不证明用户实际阅读了内容。不从正文或初始 create_time 推测
  当前版本何时已存在；来源更新时间可能只是元数据更新，因此这个时间是保守的
  来源版本记录时间，不等同于正文的精确修改时间。
- 无合法 create_time 时 `occurred_at=null`；无合法 update_time，或 update_time
  早于合法 create_time 时 `known_at=null` 并报告诊断。不使用父消息时间、会话
  时间或导入时间补造消息时间。
- 源时间按 Unix seconds 转为 UTC datetime，保留到微秒；非有限数字、布尔值或
  超出可表示范围的值视为时间异常并报告，RAW 仍保留。
- `ingested_at` 由 vault 的归档索引记录来源首次入库时间，必须复用已保存的
  元数据；已有同一证据不会因为再次导入而改成“现在”。派生数据重建时也使用
  保存的归档元数据，不重新生成这类时间。
- 本切片不表达持续状态，`valid_from` / `valid_to` 保持 null。

| 例子 | occurred_at | known_at |
| --- | --- | --- |
| 消息 4：2026 年写下提到 2022 年的回忆 | 2026-01-02T00:00:00Z | 2026-01-02T00:00:00Z |
| 消息 5：没有 create_time / update_time | null | null |
| 消息 2：b 中同 ID 内容变更 | 原 create_time：2026-01-01T00:01:00Z | update_time：2026-01-02T23:59:00Z |

这条规则仅依赖当前来源对象，不因先导入哪一份文件而改变。代价是：真实导出若
只提供 create_time，该消息的 occurred_at 有值，但 known_at 保持 null；不能
凭孤立快照保证正文从初始创建起从未改变。未来如果有可靠的来源格式契约证明
某类记录不可变，可以单独提议该来源的 create_time 回退策略。

未知 known_at 的记录仍可查询，但不进入未来 Past Me 的有时间截止检索。
Past Me 功能本身仍在范围之外。

## 6. 去重、冲突与再解析

| 情况 | 实现行为 |
| --- | --- |
| 同一 ZIP 重复导入 | 复用 RAW 对象；按唯一键复用版本及证据；首次入库时间不变 |
| 不同 ZIP 含相同身份、相同规范化内容 | 复用 Event / Artifact 版本，增加新 RAW 定位证据 |
| 不同 ZIP 含相同身份、不同规范化内容 | 保留多个 revision；不覆盖、也不静默选“最后导入的” |
| 相同正文但消息 ID 不同 | 保留不同消息，不能按正文去重 |
| 来源未提供更新次序、多个版本时间相同或未知 | 全部保留，标记冲突；不以文件名或导入顺序决定事实 |
| parser 升级 | 同一 RAW 可以重解析；按内容复用或新增版本，并保存对应处理版本证据 |

“首次入库时间”在后续实现中由 `(source, content_hash)` 对应的归档元数据提供。
同一物理 RAW 从不同 source 导入可以复用对象，但分别保留来源归档元数据。

验收清单：[expectations.json](../../tests/fixtures/chatgpt/expectations.json)。以下
数量假定同一个 source、collector 版本、parser 版本及 schema v1；只数
内容对象、规范化版本与证据，不把一次命令运行的操作日志当作新来源记录。

| 导入场景 | RAW 对象 | Event 身份 / 版本 | Artifact 身份 / 版本 | Evidence |
| --- | --- | --- | --- | --- |
| a 一次 | 1 | 2 / 2 | 5 / 5 | 7 |
| a 十次 | 1 | 2 / 2 | 5 / 5 | 7 |
| a 然后 b | 2 | 2 / 3 | 6 / 7 | 15 |
| b 然后 a | 2 | 2 / 3 | 6 / 7 | 15 |

会话 1 的来源更新时间变化，因此 Event 多一个版本；消息 2 内容变化产生一个
额外版本，消息 6 是新增身份。会话 2 内容及时间不变，只增加新 RAW 证据。
对于这组时间完整的变更，交换导入顺序后的身份、规范化版本与证据集合应相同；
实际首次入库时间取决于执行时间，不要求不同运行的归档元数据逐字节一致。

这些场景由 `tests/unit/test_pipeline.py` 的端到端测试覆盖，包括十次重复导入
后整个数据目录的文件哈希不变，以及交换导入顺序后逻辑记录和证据集合一致。

## 7. 已批准的设计选择

用户已确认：

1. Event / Artifact / Evidence 三张最小表，以及逻辑 Envelope 包的拆表方式。
2. 保留全部消息分支和全部内容版本，默认不将多个版本压成“最新一条”。
3. known_at 使用来源 update_time；缺失时不回退 create_time，因此会保守排除一部分
   记录的历史知识检索。

物理写入按来源、RAW 哈希与处理版本建立不可替换的完整快照分区。三个 Parquet
文件全部写好后原子发布目录，并登记成功分区；查询通过 `SELECT DISTINCT` 合并
相同身份及版本。重叠消息可能存在于多个物理分区，但逻辑查询中只有一条版本记录。
详见 [ADR-007](../adr/ADR-007-RAW归档与Silver快照发布.md)。
