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

（待实现）

## 安全红线

- 所有真实个人数据仅存于本地（默认 `~/Lifebase/`），永不进入 git。
- 本仓库只包含代码、schema、文档与合成测试数据。

## 更多

- 完整规格：`docs/context.md`
- Agent 规则：`CLAUDE.md`
- 架构决策：`docs/adr/`
