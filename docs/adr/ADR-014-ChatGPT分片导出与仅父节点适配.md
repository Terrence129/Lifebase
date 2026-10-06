# ADR-014：ChatGPT 分片导出与仅父节点适配

- 状态：Accepted，用户于 2026-10-06 批准实施方案并委派实现。
- 日期：2026-10-06

## 背景

本地官方导出使用编号会话 JSON、仅含 parent 的节点和没有消息 update_time 的记录。
此前 collector 检测到编号文件后拒绝解析，并要求每个节点都有 children。部分
multimodal_text 消息同时含字符串和媒体对象，全部作为非文本处理会漏掉可查询文本。

## 决策

1. **Build + Reuse（zipfile、json）**：ZIP 读取独立在 collector 的 export.py 中。
   同时支持根目录 conversations.json 或从 0 起连续且唯一编号的会话文件；两种
   布局同时存在时拒绝。存在 export_manifest.json 时核对逻辑文件列表、分片数量、
   sharded 标记，以及可选库存中的会话成员长度；缺失、重复或矛盾时保留归档并报错。
   缺少 manifest 的编号文件按数字顺序读取，并诊断无法证明导出完整性。
2. **Build**：内部 RawExport 持有多个 RawMember。每个成员保留原始文件名、字节
   哈希及自己的会话数组；Evidence 的 raw_pointer 使用成员内索引。跨成员重复
   会话 ID 拒绝解析；其他身份和版本规则沿用 [ADR-006](ADR-006-首个采集切片的最小输出契约.md)。
3. **Build**：节点的 parent 为关系来源，在内存建立孩子集合；输入显式提供 children
   时仍校验类型、重复与双向一致性。循环、断链和非法节点 ID 继续报错。空节点沿用
   最近消息祖先映射；current_node 只做有效性检查，不筛掉其他回复分支。
4. **Build**：text 消息逐段保留；multimodal_text 的 parts 必须由字符串或对象组成，
   仅按原顺序提取字符串，保留空字符串、空白和换行，不将对象转成文字。没有字符串
   时 text_parts=null；对象与其他未支持内容仍通过 RAW 定位。来源 content_format
   保持原值；thoughts、reasoning_recap 等类型只生成元数据记录。
5. **Reuse（canonical v1、既有质量报告）**：Event / Artifact / Evidence 的字段、
   Envelope 和 schema_version 不变。时间映射沿用 [输出契约](../design/chatgpt-minimal-contract-draft.md#5-时间规则与空值)。
   质量报告的 text_versions 仍只计 text 类型；multimodal_text 即使提取到字符串，
   仍计入 unsupported_content_versions，表示未完整解析该类型。报告字段不变。
6. **Build**：collector/parser 版本升级为 chatgpt@0.2.0，派生分区按新处理版本发布，
   既有分区保留。复用 [RAW 重放机制](ADR-009-RAW重放与处理版本选择.md) 和通用逐
   成员证据校验；已有 verify 不需要增加来源专用逻辑。
7. **Reuse（有界读取）**：会话成员及其总解压字节上限均为 128 MiB；manifest 单独
   限制为 1 MiB。不解压到文件系统，仅读取会话成员及 manifest，不解析账户、媒体
   或 Sites。全部 ZIP 字节仍由现有 RAW 存储保存。
8. **Integrate**：本轮没有接入外部服务或增加依赖。
9. **Defer**：媒体理解、Sites 导入、账户自动识别、历史知识检索和流式大规模处理。

## 被否方案

- 将分片拼成新 conversations.json 或重新打包：会使来源成员名与指针失去原始定位，
  并增加一份人为派生的输入。当前逐成员读取直接引用原始 ZIP。
- 只移除编号文件拒绝条件：仍无法处理缺失 children，也不能保证第二个成员的证据
  指针正确。
- 只导入 current_node 所在分支：会丢掉已导出的其他回复。
- 将 multimodal_text 的所有 parts 转成字符串：媒体对象的序列化文字不是消息正文。
- 用 create_time、会话 update_time 或导入时间填消息 known_at：缺少来源版本时间
  证据，且违背已批准的时间映射。
- 每个分片分别放宽到 128 MiB、总量不限：分片可以绕开原型的内存边界。

## 后果

单文件合成输入继续兼容；分片与仅 parent 输入进入同一套 RAW → Silver → 查询链路。
本地 conda lifebase 环境 ruff 检查通过，141 项测试全部通过。40 项新增回归样例由
已有合成 fixture 派生到测试临时目录，覆盖清单不一致、JSON 上限、
分支、混合内容、逐成员证据、十次导入/重放稳定性及缺失派生数据恢复。

2026-10-06，本地单份官方导出验收完成：125 个会话、5,882 条消息、6,007 条证据。
ingest → verify → quality → 聚合 query → 重复 ingest → rebuild → verify 全部成功；
原始 ZIP、已归档 RAW 与 manifest 的哈希、权限及 mtime 保持不变。重复导入和重放
未改变持久化文件。真实数据的缺失派生分区恢复没有执行，恢复路径由合成样例覆盖。

所有消息都有合法 create_time，但消息 known_at 全部为空。109 条 multimodal_text
记录提取到字符串。quality 为 warning：缺失消息版本时间、14 条空文本版本及未完整
支持的内容类型。此验收只证明该份导出的可处理性，不证明账户导出覆盖完整、媒体理解
或未来其他导出格式的兼容性。约束见 [AGENTS.md](../../AGENTS.md)。
