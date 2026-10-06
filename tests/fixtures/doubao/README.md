# doubao-helper 合成导出样例

`export-a.json` 的身份、时间和正文均为手工构造，不来自真实导出。
项目规则见 [AGENTS.md](../../../AGENTS.md)。

- 一个会话、三条消息，保留独立消息 ID、raw 对象和秒级/微秒级时间。
- URL chatId 与 meta.conversationId 不同，用于验证 API 会话身份优先。
- 用户文本包含空白和换行；两条助手消息与占位媒体仅模拟来源格式。
- bot_reply_message_id 保存在原对象中，不声明其构成完整父子关系。

[豆包测试](../../unit/test_doubao.py) 从此文件生成临时合成变体，覆盖重叠快照、
时间与身份异常、目录导入、重复导入、RAW 重放及证据定位；不读取用户实际导出。
映射与范围见 [ADR-015](../../../docs/adr/ADR-015-豆包JSON导入与多来源重放.md)。
