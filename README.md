# Lifebase

**Local-first 个人数据基础设施**：持续采集、保存、规范化你分散在微信、照片、GPS、邮件、ChatGPT、GitHub、银行等各处的数字生活痕迹，形成有证据支撑、带时间语义的个人知识图谱，并在此之上构建个人 AI 应用。

> Own your data first. Intelligence comes later.

伞形名称 **Lifebase**；四层分别为 LifeSync / LifeVault / LifeGraph / HumanOS（命名决策见 `docs/adr/ADR-002`）。

## 架构

```
LifeSync（采集）→ LifeVault（不可变存储）→ LifeGraph（知识图谱）→ HumanOS（AI 应用）
```

## 当前状态

项目启动阶段。第一个里程碑：**Weekend Prototype** —— export.zip 丢进 inbox → 可查询数据。

## 快速开始

### 开发环境

在已安装 conda 的设备上，从仓库根目录执行（macOS / Linux）：

```bash
conda env create --file environment.yml
conda activate lifebase
conda env config vars set --name lifebase "UV_PROJECT_ENVIRONMENT=$CONDA_PREFIX"
conda deactivate
conda activate lifebase
uv sync --locked --extra dev --inexact
```

退出后重新激活，用于加载刚保存的环境变量。Windows PowerShell 用户将第三条命令改为：

```powershell
conda env config vars set --name lifebase "UV_PROJECT_ENVIRONMENT=$env:CONDA_PREFIX"
```

之后每次开发只需 `conda activate lifebase`。`UV_PROJECT_ENVIRONMENT` 指向这台设备上
的专用 conda 环境，让 uv 将项目及其依赖安装在其中。同步时保留 `--inexact`，以保留
conda 安装的工具包。

配置文件分工：

- `environment.yml`：环境名称、Python 3.12、pip 和固定版本的 uv。
- `pyproject.toml`：项目依赖与开发依赖的声明。
- `uv.lock`：锁定 Python 库版本和分发文件哈希，供其他设备及 CI 安装同一组库版本。

这些文件不包含本机环境路径；conda 的底层系统包会按设备平台解析，并非逐字节复制
整套环境。已有环境在拉取依赖变更后，重新执行 `uv sync --locked --extra dev --inexact`。
有意升级依赖时执行 `uv lock --upgrade`，再同步并验证。

### 本地验证

```bash
uv run ruff check .
uv run pytest
```

CLI 目前仍是骨架，导入与查询功能待实现。

## 安全红线

真实个人数据与密钥永不进入 git（数据只存本地，默认 `~/Lifebase/`）；本仓库只包含代码、schema、文档与合成测试数据。完整红线与规则以 [AGENTS.md](./AGENTS.md) 为唯一事实源。

## 更多

- Agent 规则与红线（唯一事实源）：`AGENTS.md`
- 架构决策：`docs/adr/`
