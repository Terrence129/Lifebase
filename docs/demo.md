# 双来源图谱终端演示

更新日期：2026-10-20。当前可以体验采集、存储、自动关键词图谱和 HumanOS 只读工具。
Harness 联调见 [ADR-020](adr/ADR-020-Harness联调与合成库云端放行.md)。规则见 [AGENTS.md](../AGENTS.md)，接口见
[Harness 接入说明](harness-interface.md)。先用合成数据，约需 10–15 分钟。

本机演示库已迁至独立 private 数据仓库的 `libraries/demo/`，`~/Lifebase-demo`
保留为兼容链接，因此下列命令继续可用。其他设备的 clone、LFS 恢复和固定库选择
入口见 [数据仓库说明](data-repository.md)。

## 1. 准备合成库

从仓库根目录执行，依赖包含已锁定的 jieba：

```bash
conda activate lifebase
uv sync --locked --extra dev --inexact

lifebase_demo() {
  lifebase --data-dir "$HOME/Lifebase-demo" "$@"
}

lifebase_demo ingest --source chatgpt:synthetic-account tests/fixtures/chatgpt/export-a.zip
lifebase_demo ingest --source doubao:synthetic-account tests/fixtures/doubao/export-a.json
lifebase_demo graph build
lifebase_demo graph status
```

原始样例包含两个来源、三个会话、八条消息和十一条证据。
默认提取器形成 24 个关键词主题、32 条主题关联；关键词主题也可能包含普通词，
不是模型归纳的语义分类。重复导入返回 unchanged，重复构图返回 created=false。
构图输出在 `~/Lifebase-demo/vault/gold/`；原有 Silver 和索引保持原状。

## 2. 查看主题和跨来源检索

```bash
lifebase_demo topics
lifebase_demo search "野餐"
lifebase_demo search "野餐" --source doubao:synthetic-account --role user
lifebase_demo search "野餐" --since 2026-01-01 --until 2026-01-02
```

“野餐”召回五条消息，来自 ChatGPT 和豆包；每条包含角色、消息时间、片段、会话 ID、
图谱路径和证据 ID。筛选来源和角色不会改变图谱。日期按 UTC 解释，结束点不包含。
未知发生时间不参与范围命中，有对应提醒。无日期筛选时保留时间未知的消息。

## 3. 阅读会话并查看证据

先列出全部会话：按最近活动排序，显示标题、时间跨度、消息数和主题词，不显示正文。
三个合成会话一页列完；真实库可用 `--limit 100` 加上一页返回的 `--offset` 翻页。

```bash
lifebase_demo conversations
lifebase_demo conversations --limit 2 --offset 2
```

下面的命令自动从合成检索结果取得 ID，也可以手动复制终端显示的 ID：

```bash
demo_conversation_id=$(lifebase_demo search "野餐" --source chatgpt:synthetic-account --format json | python -c 'import json,sys; print(json.load(sys.stdin)["data"]["matches"][0]["conversation_id"])')
lifebase_demo timeline --conversation "$demo_conversation_id"

demo_evidence_id=$(lifebase_demo search "野餐" --format json | python -c 'import json,sys; print(json.load(sys.stdin)["data"]["matches"][0]["evidence"][0]["evidence_id"])')
lifebase_demo evidence "$demo_evidence_id"
```

ChatGPT 野餐会话包含一个用户问题和两条并列助手回复，均保留。豆包没有解析父关系，
不会补造回复树。证据命令返回规范化片段、RAW 哈希、ZIP 成员或 JSON 文件定位。
已有内容版本均可返回；无法按 known_at 排序的版本会提醒冲突。

消息长于三百字时显示命中附近片段，并标明 truncated。需要完整 Silver 原文时仍可用
现有本地 `query` 命令；它不属于未来提供给 Harness 的工具集合。

## 4. 准备 Harness 上下文

```bash
lifebase_demo context "我在两个平台讨论过野餐的哪些安排？"
lifebase_demo context "野餐有哪些讨论？" --format json | python -m json.tool --no-ensure-ascii
lifebase_demo search "synthetic-unmatched-topic"
```

上下文包最多十条、每条三百字，有两个来源命中时优先各取一条。
`generated_answer` 为 null；此时交付的是证据，不是 AI 回答。无命中会返回 empty
与证据不足提醒，退出码仍为零。统计关键词不会识别所有同义词或复杂自然语言条件。

检查云端目的地请求：

```bash
lifebase_demo context "野餐" --destination cloud --format json
lifebase context "野餐" --destination cloud --format json
```

两条都预期返回 ok：聊天来源默认 cloud_ok（[ADR-021](adr/ADR-021-聊天来源恢复云端可用与真实库试运行.md)），合成库另有 fixture 哈希白名单。
来源被降为 local_only 时，cloud 请求以退出码一、error.code=EGRESS_BLOCKED 拒绝，不返回消息。接口不提供策略覆盖或脱敏选项。

## 5. 完整性与更新

```bash
lifebase_demo verify
lifebase_demo graph status
lifebase_demo graph build
```

verify 验证 RAW、Silver 和证据；graph status 验证 Gold 的哈希、结构、证据引用与输入
是否更新。正常合成库两项均为 ok。未知时间的 quality 提醒是合成样例的预期行为。

可选：导入重叠样例验证版本与过期图谱。

```bash
lifebase_demo ingest --source chatgpt:synthetic-account tests/fixtures/chatgpt/export-b.zip
lifebase_demo graph status
lifebase_demo graph build
lifebase_demo search "野餐" --format json
```

导入后旧图谱变成 stale，检索会拒绝；显式构图后恢复。此时基础样例消息数量会变化，
不能再按八条验收。旧 Gold 快照保留，新输入生成新的快照身份。

## 6. 使用你的真实本地库

默认 `~/Lifebase` 已包含两种来源的导入数据：

```bash
lifebase graph status
lifebase topics
lifebase conversations --limit 100
lifebase search "替换成你关心的主题"
lifebase context "替换成包含主题词的问题" --format json
```

如果 graph status 显示缺失或过期，先执行 `lifebase graph build`。输出仅在本地终端查看。
聊天来源默认 cloud_ok，真实库可在 cloud 目的地下使用（[ADR-021](adr/ADR-021-聊天来源恢复云端可用与真实库试运行.md)）。
