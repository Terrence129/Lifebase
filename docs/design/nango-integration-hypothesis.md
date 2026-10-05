# Nango：LifeSync API 接入候选

- 状态：待评估的架构猜想，尚未选型或接入。
- 记录日期：2026-10-05。
- 当前分类：**Defer**；若验证收益，再考虑 **Integrate**。
- 项目约束统一见 [AGENTS.md](../../AGENTS.md)；本记录不改变既定技术栈、数据契约或架构边界。

## 猜想与适用场景

当 LifeSync 持续接入多个需要 OAuth 的 API 来源（如 Gmail、日历、GitHub），
并出现重复的授权、token 刷新、连接失效处理和 API 调用维护工作时，Nango 可能
作为独立服务减少这部分成本。其价值需要与直接使用官方 SDK 或成熟 OAuth 库比较。

当前 ChatGPT 官方 ZIP 导入路径以文件解析和归档为主，接入 Nango 的收益有限。
本地照片、GPS 文件等来源也不依赖它。Nango 的 API 支持范围不等于相关个人历史
数据都能采集，实际覆盖仍取决于来源平台的端点、权限和历史数据可用性。

## 候选接入位置

优先评估 Auth / Proxy 的最小接入方式，保留 Python Collector 和现有数据流：

```text
文件导出 ───────────────────────→ LifeSync 文件 Collector ──┐
                                                           ↓
平台 API → Nango（Auth / Proxy）→ LifeSync API Collector → LifeVault RAW
                                                           ↓
                                                     Normalizer → Silver
```

Nango 承担来源授权、凭证管理及 API 代理等公共接入能力；LifeSync 仍负责来源语义、
采集范围与标准化映射，LifeVault 仍负责归档与证据引用。Nango 的连接标识可作为
未来来源配置的外部引用，具体映射留待正式设计，不在本记录中新增字段。

如进一步使用 Nango Sync，需要单独评估其缓存、字段映射、更新与删除行为。
同步缓存中的最新记录不自动等价于可重建的来源证据；评估应确认能否取得并保存
所需的原始 API 响应、来源 ID、采集时间及必要上下文。来源状态变化如何表达为
Lifebase 的历史记录，仍需由采集契约定义。

## 部署与能力取舍

以下为 2026-10-05 查阅官方资料的快照，正式评估时需重新核实：

| 方式 | 相关能力 | 对 Lifebase 的代价与待确认点 |
| --- | --- | --- |
| 免费自托管 | Auth、Proxy；不含托管 Sync、预置同步、Webhooks、Triggers 和 MCP server | 可在自有环境运行，但仍需自建同步流程；增加 Nango 服务及其数据库等运维工作 |
| Nango Cloud | 提供完整平台能力，具体额度与功能取决于方案 | 凭证由托管服务管理，经 Proxy / Sync 的数据涉及第三方处理；需评估数据路径、缓存、日志、费用及可接受范围 |
| Enterprise BYOC / Self-Managed | 提供完整平台能力，运行于自有基础设施 | 需要 Enterprise 订阅；完整平台包含多个 Node 服务、PostgreSQL、Redis、对象存储和 Elasticsearch，运维成本较高 |

免费自托管的官方 Docker Compose 包含 Nango 服务、PostgreSQL 和 Redis。
Python 主程序可通过 API 与 Nango 集成；使用 Nango 集成函数运行能力时，还会
涉及 TypeScript 函数代码及其部署维护。

## Build / Reuse / Integrate / Defer

- **Build**：维护 Lifebase 的来源适配、证据映射和标准化逻辑，因为这些表达项目自身的数据语义。
- **Reuse**：少量 API 来源优先评估官方 SDK、成熟 OAuth 库与既有 Collector 契约，以较小运维成本验证需求；具体组件随来源选定。
- **Integrate**：若收益得到验证，将 Nango 作为 LifeSync 的可选独立服务，通过适配器接入，避免文件导入和存储层依赖其运行。
- **Defer**：当前暂缓引入 Nango，也暂缓设计统一凭证平台或迁移现有采集流程；先完成当前来源的实际兼容性验证。

## 重新评估的触发条件

出现以下实际需求时重新比较方案，而不是仅按潜在平台数量预先引入：

1. 已确定多个需要持续同步的 OAuth 来源，并明确所需端点与采集权限。
2. token 刷新、重新授权、限流或同步失败处理出现可记录的重复维护成本。
3. 有需要统一连接管理的多个账户，或需要可靠的后台同步与 webhook 接收能力。

届时用合成数据或测试账户验证一条最小 API 链路，比较直接调用与 Nango 接入的
实现量、维护成本、数据完整性、重放能力、部署负担和费用；评估所选方式的数据
流向、凭证管理及退出迁移路径。若证据支持接入，再提出正式 ADR 和实施范围。

## 官方资料

- [Nango 项目介绍与集成函数](https://github.com/NangoHQ/nango)
- [Auth 能力](https://nango.dev/platform/auth/)
- [自托管方式与功能对照](https://nango.dev/docs/guides/platform/self-hosting/self-hosting)
- [免费自托管 Docker Compose](https://github.com/NangoHQ/nango/blob/master/docker-compose.yaml)
- [Data Sync 与云端缓存说明](https://nango.dev/platform/data-sync)
