# AGENTS.md

本仓库的 Agent 规则与上下文请阅读 **CLAUDE.md**（完整版）。核心红线速览：

1. **真实个人数据永不进入 git**（数据只在本地 `~/Lifebase/`）。
2. **RAW 数据不可变**；LLM 输出不是事实，必须附带 provenance。
3. 本地优先、隐私优先；不提交任何密钥。
4. 每个方案必须标注 **Build / Reuse / Integrate / Defer**。
5. 用户是唯一开发者，Agent 默认顾问角色：未经批准不要写实现代码。
6. git 提交禁止任何 AI 署名（Co-Authored-By 等），贡献者只能是用户本人。
7. 完整规格见 `docs/context.md`。
