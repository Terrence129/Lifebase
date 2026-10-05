# Architecture Decision Records

- 命名：`ADR-NNN-主题.md`（NNN 三位递增编号）。
- 状态流转：Proposed → Accepted → Superseded（被新 ADR 取代时标注取代它的编号）。
- 每个重要决策都写一条：技术选型、schema 变更、架构边界等。
- 写 ADR 的理由：单人长期项目，三个月后的你需要知道当时的你为什么这么选。

## ADR 骨架（新 ADR 必须包含）

```
# ADR-NNN-主题

- 状态：Proposed / Accepted / Superseded
- 日期：YYYY-MM-DD

## 背景
<动机，独立成文，不依赖方案也能读懂>

## 决策
<已落地的现实，现在时；不写「应该/计划」等 spec 语气>

## 被否方案
<必填：每个真实被考虑过的方案 + 落选原因>

## 后果
<代价与收益，各是什么>
```

其他约定：

- 已落地（Accepted）的 ADR 只写现在时事实，不残留 spec 语气。
- 绝不把旧 ADR 改写成相反的决策：新决策 = 新 ADR + 交叉链接；历史 ADR 保留不删。
- 「被否方案」缺失的决策会招致重新争论，必须如实记录。
