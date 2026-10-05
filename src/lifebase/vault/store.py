"""LifeVault 内容寻址存储（Bronze）。

原则（docs/context.md §8）：
    immutable / versioned / content hashed / never modified / re-parseable

实现要点：
    sha256(字节) → objects/ab/cdef...（前两位作目录前缀）
    只追加写入；提供读回校验（hash verify）。
"""
