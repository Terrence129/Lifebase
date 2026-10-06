# ChatGPT 合成导出样例

这些文件全部由手工构造的 ID、日期和文字组成，不来自真实导出。
项目规则以 [AGENTS.md](../../../AGENTS.md) 为准。

- `export-a/conversations.json`：两段对话、五条消息；包含两条并列回复、空根节点、
  分段文本、2026 年写下的虚构 2022 年回忆，以及一条时间缺失的回复。
- `export-b/conversations.json`：两段对话、六条消息；交换对话数组顺序，保留
  重叠内容，新增一条消息，并给同一消息 ID 设置不同内容和合法更新时间。
- `export-a.zip` / `export-b.zip`：各包含对应 JSON 的原始字节；固定 ZIP 元数据，
  便于未来 CLI 直接导入和读回校验。
- `expectations.json`：ZIP / 成员 SHA-256、场景数量与时间预期，供端到端测试使用；
  正式 schema 位于 schemas/，实际输出由 collector 生成。

这里的 mapping 结构是候选测试输入，不代表所有官方导出版本的完整契约。
同 ID 内容变化是合成冲突场景，不声称是真实平台的必然编辑行为。

`tests/unit/test_chatgpt_exports.py` 从 export-a 的合成 JSON 派生分片 ZIP 到测试临时
目录：移除 children 与消息 update_time，加入混合字符串/占位媒体、manifest，并覆盖
清单矛盾、逐成员证据定位、十次导入/重放稳定性及缺失派生数据恢复。该路径不读取真实
导出，也不新增真实聊天样例。

设计与验收规则见 [输出契约 v1](../../../docs/design/chatgpt-minimal-contract-draft.md)。
