# 独立私有数据仓库

更新日期：2026-10-06。用户授权的独立数据同步范围见
[AGENTS.md](../AGENTS.md)，选择与代价见
[ADR-017](adr/ADR-017-独立私有数据仓库与无损迁移.md)。

本机数据仓库为 `../Lifebase-data`，真实库在 `libraries/personal/`，合成库在
`libraries/demo/`。原 `~/Lifebase` 与 `~/Lifebase-demo` 是兼容链接；现有默认命令
继续可用。新设备通过数据仓库的入口显式选择库：

```bash
conda activate lifebase
../Lifebase-data/bin/lifebase-data graph status
../Lifebase-data/bin/lifebase-data --library demo search "野餐"
../Lifebase-data/bin/lifebase-data --library demo context "野餐有哪些讨论？" --format json
```

也可以 `lifebase --data-dir ../Lifebase-data/libraries/personal list`。
来源导出位于 `exports/`，导入后仍归档到库内 RAW；移走导出不会改变已归档证据。

## 路径选择加入

普通 Git 工作树仍拒绝存库。独立数据仓库根需包含 `.lifebase-data.json`：

```json
{
  "schema_version": 1,
  "purpose": "lifebase-private-data",
  "visibility": "private",
  "repository": "Terrence129/Lifebase-data",
  "libraries": {
    "personal": "libraries/personal",
    "demo": "libraries/demo"
  }
}
```

实际 origin 须与 repository 相符（GitHub SSH 或 HTTPS 的完整 `.git` URL）。库根
必须在 `libraries/` 下，不接受 exports、仓库根、未登记目录、路径穿越或嵌套 Git
工作树。配置是本地选择加入声明；应用不在每次查询时访问 GitHub。私有仓库的维护
脚本在推送前独立核对可见性。

## 另一台设备

先安装 [Git LFS](https://git-lfs.com/)，clone 数据仓库后执行 `git lfs pull`，按仓库
README 恢复库权限并运行 validate。LFS 未 hydrate 的指针不是真实数据，不能导入
或构图。Git 不保存原 Unix 权限和修改时间；迁移报告用于审计，本地验收以哈希和
规范化身份为准。

Git / LFS 是本次授权的同步方式。独立备份恢复、Harness、模型回答及真实外发验证
继续等待后续阶段。迁移本身未改动来源策略；当前策略见
[ADR-020](adr/ADR-020-Harness联调与合成库云端放行.md)：真实库保持 `local_only`。
