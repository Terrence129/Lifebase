"""RAW 归档 manifest —— 只追加的索引。

每条记录对应一次入库：文件路径、hash、来源、时间、collector 版本。
未来 parser 升级时，依据 manifest 从 RAW 重建 Silver/Gold。
"""
