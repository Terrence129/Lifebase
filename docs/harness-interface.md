# Harness 就绪接口 v1

更新日期：2026-10-07。Lifebase 提供只读 JSON CLI；Harness 侧的只读插件已实现并通过
端到端验收，见下文「Harness 侧实现」。依赖方向见
[ADR-013](adr/ADR-013-Agent运行时集成边界.md)，图谱与工具行为见
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

目的地门禁在 Lifebase 侧执行：cloud 要求整份图谱的输入来源全部为 cloud_ok。
local_only、未知策略和没有脱敏器的 redact_before_cloud 都拒绝云端请求。
`--source` 不缩小快照身份和全局统计的派生来源范围，因此不能绕过门禁。
当前 ChatGPT、豆包的默认策略为 cloud_ok（ADR-018），云端模型可直接消费这些工具；
改回 local_only 即恢复拒绝。

这里检查的是调用方声明的目的地，不是操作系统网络隔离。Harness 即使运行在本机，
调用云端 DeepSeek API 仍是 cloud；不能为获取数据而填写 local。
插件须按实际模型路由指定目的地，并在路由变化时重新校验。当前没有来源策略覆盖配置、
脱敏器或模型 SDK。

## Harness 侧实现

插件 `dsh-lifebase` 位于 fork 仓库 `Terrence129/deepseek-harness-yaqi` 的
`feat/lifebase-readonly-plugin` 分支（`plugins/lifebase/`），按 ADR-013 留在运行时
自己的仓库，不进本仓库。它是纯 ESM 的零构建包：`index.js` 直接运行，没有编译步骤，
也不需要安装依赖；`package.json` 用 `dsh.bundle.patch` 声明 bundle，并把
`@deepseek-ai/dsh-llm`、`@deepseek-ai/dsh-tools`、`@deepseek-ai/schemastery` 声明为
peer，Harness 才把这三个名字路由到自己的副本。

| 工具 | 对应命令 | 说明 |
| --- | --- | --- |
| `lifebase_topics` | `topics` | 主题列表 |
| `lifebase_search` | `search` | 消息检索，返回片段与证据定位 |
| `lifebase_timeline` | `timeline` | 单会话按发生顺序展开 |
| `lifebase_evidence` | `evidence` | 证据 id 指向的规范化记录 |
| `lifebase_context` | `context` | 按问题收集证据，跨来源均衡 |

配置字段为 `command`（默认 `lifebase`，本机填绝对路径）、`dataDir`（必填）、
`destination`（默认 `cloud`）、`timeoutMs`（默认 20000）。工具返回值是 CLI 的 v1 信封
原样透传，插件不重写字段；信封因此是唯一契约来源，不存在第二份会漂移的类型定义。
每次调用启动新进程，冷启动需数秒。`destination` 由配置原样传给 `--destination`，插件
不检查模型路由——CLI 默认 `local`，插件默认 `cloud`，两者不同，改路由时必须手动改回
并重新校验；理由见 [ADR-019](adr/ADR-019-只读插件的交付形态与目的地声明.md)。

fork 是公开仓库，因此仓库内的 patch 文件只带可移植的占位值，不含本机路径与数据目录名。
真值放在 profile 自己的 patch 层（harness home 下的 `profiles/<profile>/cordis.patch.yml`，
不在任何检出目录内）：同 id 的行应用在所有 bundle 层之后，并整块替换该条目的配置。
开发层另从 `LIFEBASE_EXE` 与 `LIFEBASE_DEMO_DIR` 取路径，与端到端测试读同一对变量。

退出码映射：exit 0 的 `ok` 与 `empty` 都算成功；exit 1 的 JSON 错误信封原样保留
`error.code`；exit 2 单独分类为插件自身的参数构造缺陷；输出超过 1 MiB 捕获上限时
拒绝解析截断内容，而不是当成更小的结果。错误码通过 `HarnessError` 抛出，因此 Harness
把 `{name, code}` 放进结构化错误字段，而不只是消息文本。

验收与未验证项：

- 自动化端到端（假模型驱动）覆盖三件：三次工具调用并把前一次结果里的 `evidence_id`
  带回下一次调用；空数据目录返回 `GRAPH_MISSING` 且回合正常结束；`destination: local`
  原样透传并由信封回显。信封长度断言低于 Harness 的 8192 字符裁剪阈值，warnings 因此
  仍在模型可见文本内。
- 真实云端模型在合成演示库上跑通两次：一次给出跨两个来源、带 `record_id` /
  `evidence_id` 的引用回答（并自行追加调用了 `lifebase_timeline`）；一次查询不存在的
  词，模型报告「没有找到相关讨论」并说明空结果是正常返回，同时正确读出
  `INSUFFICIENT_EVIDENCE` 这一 warning。
- 已装入 `web` profile（`dsh plugin --profile web add`），组合层与工具注册均已核对，
  五个工具在 web 树中全部注册成功。**未经浏览器核对的部分**：插件行的标题、描述与
  图标只核对了导出资源与 `meta.*` 字段，没有核对渲染结果。
- 真实库尚未进入云端模型；本轮只跑合成库。回答质量只有人工观察，没有评测集。

## 联调交接清单

**Build / Reuse** 已交付：图谱、终端工具、JSON v1 契约、合成样例和独立验收。
**Integrate** 首个切片已交付：本地 DeepSeek Harness fork 中的只读插件与 profile 安装，
工具调用、目的地透传与引用回答均已端到端验证。**Integrate 续**：真实库端到端，以及
回答质量与引用支持度的可复查记录。**Defer**：模型生成回答的 Gold 保存、Agent 会话
回采、自动上下文与 Past Me。

先用合成库联调；真实来源能否进入模型由实际路由及来源策略共同决定。
消费方不获得 graph build、ingest、query 或 RAW 文件访问工具。
