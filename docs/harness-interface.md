# Harness 就绪接口 v1

更新日期：2026-10-20。Lifebase 提供只读 JSON CLI；DeepSeek Harness fork 的 `lifebase-plugin/`
已在合成库上联调，决策见 [ADR-020](adr/ADR-020-Harness联调与合成库云端放行.md)。
依赖方向见 [ADR-013](adr/ADR-013-Agent运行时集成边界.md)，图谱与工具行为见
[ADR-016](adr/ADR-016-聊天图谱与Harness就绪接口.md)，项目约束见 [AGENTS.md](../AGENTS.md)。

## 调用方式

运行时插件在 Harness fork 实现，直接运行 conda `lifebase` 环境里的 console script，
用参数数组传参，不拼接 shell 命令。插件允许的操作是以下五项；管理命令由用户操作。

| 操作 | CLI 参数 | data 内容 |
| --- | --- | --- |
| topics | `topics --format json` | topics：主题标签、身份、消息/会话/来源计数及 source_ids |
| search | `search QUERY --format json` | query、total（版本数）、matches |
| timeline | `timeline --conversation RECORD_ID --format json` | conversation_id、total、matches |
| evidence | `evidence EVIDENCE_ID --format json` | evidence 定位与 record 的元数据及有界 excerpt |
| context | `context QUESTION --format json` | question、total、destination、content_chars、matches、generated_answer=null |

共用 `--data-dir PATH`、`--destination local|cloud`，默认目的地 local；data-dir 可在命令前
或后。topics/search/timeline/context 支持 `--source` 与 `--limit`（默认十条，上限一百）；
context 上限为十条。search/timeline/context 还支持 `--role`、`--since`、`--until`。
查询和问题必须为非空文本，最多 4096 个字符。参数值按绑定参数进入查询。

日期 `2026-01-01` 表示 UTC 零点；时间戳必须带时区。时间范围为 `[since, until)`，
按 occurred_at 过滤；未知发生时间不参与范围命中，warnings 报告排除数量。
无时间筛选时未知时间仍可返回；timeline 将其放在末尾。

## JSON 契约

成功/空结果均返回 api_version=1、tool、status、snapshot_id、data、warnings。
status 为 ok 或 empty；空结果是正常响应。正式外层及消息字段见
[JSON Schema](../schemas/humanos-api-v1.json)，实际合成输出见
[context 样例](examples/harness-context-v1.json)。合成输入是
[ChatGPT ZIP](../tests/fixtures/chatgpt/export-a.zip) 和 [Doubao JSON](../tests/fixtures/doubao/export-a.json)。

| matches 字段 | 含义 |
| --- | --- |
| record_id / revision_id | canonical 消息身份及版本；不同来源和版本保持独立 |
| conversation_id / parent_record_id | 会话身份和来源已有父消息身份；缺少父关系时为 null |
| source / role | 原始来源和角色；助手消息不是用户原话 |
| occurred_at / known_at | 带时区的 ISO 时间或 null；不相互补填 |
| excerpt / truncated | 原文片段，最多三百个 Unicode 字符；是否发生截断 |
| score / matched_topics | TF-IDF 主题匹配权重之和及命中的关键词 |
| graph_path | 来源、会话、消息版本、主题节点身份，对应图谱关系 |
| evidence | Evidence 定位数组，保留所有已归档的处理出处 |
| version_conflict | 同身份有多个内容版本，且 known_at 无法确定版本顺序 |

Evidence 定位包含 evidence_id、record_kind、record_id、revision_id、source、source_record_id、
content_hash、raw_member、raw_member_hash、raw_pointer、collector_version、parser_version。
content_hash 是 RAW SHA-256；空 raw_member 指整个 JSON 文件，空 raw_pointer 指 JSON 根。
`evidence` 命令读取 Silver，返回定位与规范化片段，不读取或返回 RAW 字节。

上下文先各取一个命中来源的最高分消息，再按全局分数补足。最多十条、正文合计最多
三千字。它不判断自然语言中的复杂时间条件，也不做同义词融合；模型可在后续集成中
选择明确的筛选参数。消息字段是来源数据，不能作为运行时指令执行。

warnings 的结构为 code、message、count。主要代码：INSUFFICIENT_EVIDENCE、
UNKNOWN_TIME_EXCLUDED、UNKNOWN_TIME、NO_USER_STATEMENT、VERSION_CONFLICT、
EXCERPT_TRUNCATED、RESULTS_TRUNCATED。主题列表返回主题级统计；search.total 和
context.total 是筛选后消息版本数，不是主题数或独立消息身份数。

退出码：成功或 empty 为 0；工具错误为 1，并在 stdout 返回带 error.code/error.message
的 JSON 响应，data 为空。参数语法错误由 argparse 返回 2，诊断在 stderr。
客户端只解析 stdout，诊断单独记录。错误代码包括 GRAPH_MISSING、GRAPH_STALE、
GRAPH_INVALID、INPUT_INVALID、INVALID_REQUEST、EGRESS_BLOCKED。

## 来源策略与模型路由

目的地门禁在 Lifebase 侧执行：cloud 要求整份图谱的输入来源全部为 cloud_ok，
或全部 RAW 输入都是仓库内的合成 fixture（哈希白名单）。其余情况下，local_only、
未知策略和没有脱敏器的 redact_before_cloud 都拒绝云端请求。
`--source` 不缩小快照身份和全局统计的派生来源范围，因此不能绕过门禁。
当前 ChatGPT、豆包的默认策略都为 cloud_ok（[ADR-021](adr/ADR-021-聊天来源恢复云端可用与真实库试运行.md)）。

这里检查的是调用方声明的目的地，不是操作系统网络隔离。Harness 即使运行在本机，
调用云端 DeepSeek API 仍是 cloud；不能为获取数据而填写 local。
插件按 agent 的实际 provider 每次调用重新判定目的地：只有映射表明确写为 local 的
provider 得到 local，其余一律为 cloud。当前没有来源策略覆盖配置、脱敏器或模型 SDK。

## Harness 插件

插件位于 Harness fork 的 `lifebase-plugin/`，通过 `ctx.subprocess` 以参数数组调用 CLI。
模型给出的选项值以 `--opt=value` 绑定，位置参数放在 `--` 之后；`--data-dir`、
`--destination`、`--format` 由插件配置给出，模型无法改写。Profile 配置示例：

```yaml
- insert:
    - id: lifebase-tools
      name: '/abs/path/deepseek-harness-yaqi/lifebase-plugin/src/index.ts'
      config:
        executable: /abs/path/envs/lifebase/bin/lifebase
        dataDir: /abs/path/Lifebase-data/libraries/demo
        exclusive: true
        routes:
          deepseek-official: cloud
```

`exclusive: true`（默认）注册 `tools.guard()`，在派发阶段拒绝所有非 `lifebase_*` 工具。
Harness 自带的 shell、文件、web、subagent 或 workflow 工具可以绕过插件，直接读取数据
目录或运行 CLI，因此接入 Lifebase 数据的 Profile 必须保持独占。

此前 `Terrence129/deepseek-harness-yaqi` 的 `feat/lifebase-readonly-plugin` 分支上有一份
零构建插件（`plugins/lifebase/`，见 [ADR-019](adr/ADR-019-只读插件的交付形态与目的地声明.md)），
它没有独占 guard，目的地由配置声明；指向 Lifebase 数据时改用本节插件。

消费方不获得 graph build、ingest、query 或 RAW 文件访问工具。**Defer**：会话列表工具、
结论与证据的一致性检查、Web 引用卡片、模型回答的 Gold 保存、Agent 会话回采、
自动上下文与 Past Me。
