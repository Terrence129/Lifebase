# ADR-005：conda 开发环境与 uv 依赖锁定

- 状态：Accepted
- 日期：2026-10-05

## 背景

用户要求创建项目专用 conda 环境，并保存配置，方便其他开发设备快速配好环境。
项目已使用 `pyproject.toml` 声明 Python 依赖，并约定由 uv 管理依赖。

## 决策

1. **Reuse（conda）**：`environment.yml` 定义 `lifebase` 环境，包含 Python 3.12、pip
   和固定版本的 uv；conda 管理解释器及其系统包，pip 仅用于安装 uv 工具。
2. **Reuse（uv）**：继续以 `pyproject.toml` 声明项目依赖，提交 `uv.lock` 锁定库版本；
   本地与 CI 都使用 `uv sync --locked --extra dev` 安装，CI 使用固定版本的 uv。
3. 本地通过 conda 环境变量配置，将 `UV_PROJECT_ENVIRONMENT` 保存为该设备的环境
   路径，激活时自动加载；本地同步添加 `--inexact` 保留 conda 安装的工具包。
4. **Build**：只补充配置与使用说明，不引入自研环境管理工具。
5. **Integrate**：本任务不接入外部服务。
6. **Defer**：完整的跨平台 conda 系统包锁定；当前环境文件约束 Python 主次版本，
   系统包由各设备上的 conda 按平台解析。

## 理由与影响

- 保留既定的 Python、uv 和数据存储技术栈，项目依赖无需在多个文件中重复维护。
- 环境配置不包含本机绝对路径或特定平台的 build 字符串；uv 锁文件保存库版本、
  分发文件哈希与平台选择信息，其他设备可从配置重建环境。
- conda 环境配置中的绝对路径只保存在对应设备，README 提供初始化命令。
- 完整环境不是逐字节相同：Python 补丁版本及底层系统包可能随设备和解析时间变化。

## 参考

- [conda 环境管理](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html)
- [uv 项目环境路径](https://docs.astral.sh/uv/concepts/projects/config/#project-environment-path)
- [uv 锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/)
