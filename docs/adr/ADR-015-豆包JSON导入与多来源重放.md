# ADR-015：豆包 JSON 导入与多来源重放

- 状态：Accepted，用户于 2026-10-06 委派接入 doubao-helper 导出，并复用 ChatGPT 数据链路。
- 日期：2026-10-06

## 背景

doubao-helper 每个会话导出一个 JSON，包含 source、chatId、meta 和 messages。
messages 同时保存工具提取的 text 与可选 raw 消息对象；消息时间位于 raw 中。
现有 RAW、Silver、查询和质量统计可复用，但只有 ChatGPT ZIP 解析器，证据校验
也只读取 ZIP。增加第二来源后，全部来源重放不能再假设只有一个 collector。

输入行为核对了用户的本地导出及工具的
[导出源码](https://github.com/chensanle/doubao-helper/blob/main/content.js)。
工具的 API 模式筛选有文本的消息并去重；导出保留入选消息的 raw 对象，没有保存
全部分页响应。rawCount 与导出消息数的差值不能直接解释为缺失消息数量。

## 决策

1. **Build**：新增 doubao@0.1.0 collector/parser。直接读取 source=doubao 的
   JSON 对象和 messages 数组；每个文件生成一个会话 Event、逐条消息 Artifact
   和对应 Evidence。显式文件先归档再解析，解析失败沿用现有登记与错误处理。
2. **Reuse（json、Decimal、datetime、hashlib）**：有界读取单文件，128 MiB 上限；
   拒绝重复 JSON key、非法记录结构、缺失身份和同文件重复消息身份，无新增依赖。
3. **Build**：会话身份依次取 meta.conversationId、一致的 raw.conversation_id、
   chatId；raw 中提供的会话 ID 必须一致。URL 路由的 chatId 可以与 API 会话 ID
   不同。消息优先取 messageId，再取 raw.message_id / id / server_message_id；
   包装层与 raw 同时给出消息身份时必须一致。数组位置只用于证据定位。
4. **Reuse（canonical v1、Envelope）**：字段、类型及 schema_version 不变。
   消息 raw.create_time → occurred_at，raw.update_time → known_at，按 Unix 秒
   转为 UTC，保留微秒。缺失或异常时间为空；更新时间早于创建时间时 known_at
   为空并报告。会话时间为空，不以 exportedAt 或消息边界推算会话时间。
5. **Build**：完整保留导出的 text，包括空字符串、空白和换行，作为一个 text_parts
   元素，content_format=text。不重新实现浏览器的文本提取，也不从媒体对象造文字。
   parent_record_id 为空；消息列表与 bot_reply_message_id 不足以证明完整回复树。
6. **Build + Reuse（既有证据哈希及 JSON Pointer）**：RAW 保存原文件字节，不生成 ZIP。
   raw_member="" 表示整个 JSON，raw_member_hash 等于 RAW 内容哈希；会话
   raw_pointer=""，消息为 /messages/{数组位置}。这些值符合现有 Evidence schema。
   verify 按 collector 类型读取 JSON 或 ZIP，并核对指针对应的会话、消息身份。
7. **Build**：新导入按已登记的来源前缀选择 collector，例如 doubao:personal。
   重放按 manifest 保存的 collector_version 类型选择当前安装的 parser，保留
   历史无前缀 ChatGPT 来源的可恢复性；已登记的来源前缀与归档类型冲突时报错。
8. **Build + Reuse（CLI、现有 RAW 重放）**：ingest 接受一个或多个文件、目录；
   目录仅扫描直接子文件，用选定 collector 检测，其他文件列入 skipped。不递归，
   不按文件推测账户。默认 inbox 使用同一行为。rebuild 默认逐条处理全部来源，
   每个 rebuilds 项报告自身 collector/parser 版本；混合版本时顶层两字段为 null。
   单一版本仍报告原来的顶层值，错误仍逐项隔离。
9. **Build**：诊断会话时间缺失、关系未映射、仅有已导出文本、覆盖范围未确认、
   rawCount 差异与可能提前停止。source coverage 保持 null；stopReason=no-more
   只表示工具停止状态，不能证明账户完整。quality 继续统计已导出的记录与空值，
   不统计工具未导出的消息或未保存的媒体。
10. **Integrate（本地文件接口）**：接入用户已生成的 doubao-helper 文件，复用既有
    SQLite、Parquet、DuckDB、registry、quality 与 query；未接浏览器或远端服务。
11. **Defer**：自动浏览器采集、全部会话遍历、原始分页响应归档、媒体解析、回复关系
    映射和覆盖范围证明。当前文件足以验证第二来源，后续能力需独立采集证据。

## 被否方案

- 将 JSON 重打包为 ChatGPT ZIP：制造新的输入字节和成员路径，且来源结构不同。
- 将所有来源交给默认 ChatGPT collector：多来源路由不明确，无法正确重放 JSON。
- 只依赖 source 前缀重放：接入第二来源后，历史无前缀来源会失去可恢复性。
- 改 Evidence 或 Envelope 字段来表达 JSON：现有空成员和根 JSON Pointer 已能定位，
  无需契约升级。
- 根据数组顺序生成父消息、以 exportedAt 填补消息时间、将 rawCount 当作完整覆盖：
  都会添加缺少来源依据的解释。
- 复刻扩展的 raw 文本提取逻辑：本轮输入已包含 text；重复处理增加格式维护成本。

## 后果与验证

2026-10-06，conda lifebase 环境 ruff 通过，176 项测试通过。新增 33 项豆包合成
验收覆盖身份与时间校验、原字节及证据指针、十次重复导入、重叠版本与账户隔离、
RAW 恢复、目录与 inbox、混合来源重放、历史来源和证据篡改检查。

本地真实 JSON 完成 ingest → quality → 聚合 query → 重复 ingest → 来源
rebuild → 全来源 rebuild → verify。
消息 creation/update 时间均有值，无空文本；会话两个时间字段为空，quality=warning。
每份文件均出现 rawCount 差异诊断，覆盖范围仍未知。

合并 ChatGPT 后，RAW、Silver 及证据检查没有错误；verify=warning，原因仅为对象目录和 Silver
目录已有的两个 Finder .DS_Store 文件（raw_path_invalid / silver_path_invalid）。
这些文件保持原状，没有放宽校验器。原始输入与既有 ChatGPT RAW、Silver 未改变；
重复导入及两种 rebuild 保持持久化文件哈希、权限及 mtime 不变。
真实数据的缺失派生数据恢复没有执行，由合成测试覆盖。

后续仍需验证真实重叠快照、工具版本变化、回复关系与完整采集。项目约束见
[AGENTS.md](../../AGENTS.md)，共用存储及重放机制见
[ADR-007](ADR-007-RAW归档与Silver快照发布.md)、
[ADR-009](ADR-009-RAW重放与处理版本选择.md)。
