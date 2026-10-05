"""内容寻址工具。

sha256(字节) → hex digest；存储路径取前两位前缀（objects/ab/cdef...）。
所有 RAW 对象、媒体文件都走这里，数据库只保存 hash 引用（docs/context.md §21）。
"""
