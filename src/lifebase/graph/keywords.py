"""本地 TF-IDF 关键词提取；不加载用户词表或调用模型。"""

from __future__ import annotations

import logging
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Self

import jieba
import jieba.analyse

from lifebase.core.hashing import sha256_file
from lifebase.core.records import identity_hash

ALGORITHM_VERSION = "jieba-tfidf@0.1.0"
STOP_WORDS = frozenset({
    "什么", "怎么", "如何", "可以", "这个", "那个", "我们", "你们", "自己", "现在",
    "需要", "一下", "一个", "一些", "问题", "回复", "谢谢", "请问", "还有", "以及",
})


def extractor_metadata() -> dict[str, Any]:
    """提取器及词典内容身份；不初始化分词缓存。"""
    package = Path(jieba.__file__).parent
    return {"algorithm_version": ALGORITHM_VERSION, "jieba_version": version("jieba"),
            "dictionary_hash": sha256_file(package / "dict.txt"),
            "idf_hash": sha256_file(package / "analyse" / "idf.txt"),
            "stop_words_hash": identity_hash(sorted(STOP_WORDS | jieba.analyse.TFIDF.STOP_WORDS))}


class KeywordExtractor:
    """独立分词器使用本次创建的临时缓存；关闭后只清理自己的目录。"""

    def __init__(self) -> None:
        self._temporary = TemporaryDirectory(prefix="lifebase-jieba-")
        tokenizer = jieba.Tokenizer()
        tokenizer.tmp_dir = self._temporary.name
        jieba.setLogLevel(logging.WARNING)
        self._extractor = jieba.analyse.TFIDF()
        self._extractor.tokenizer = tokenizer
        self._extractor.stop_words.update(STOP_WORDS)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self._temporary.cleanup()

    def extract(self, text: str, count: int = 5) -> tuple[tuple[str, float], ...]:
        if not text.strip():
            return ()
        tags = self._extractor.extract_tags(text.casefold(), topK=None, withWeight=True)
        values = [(term, round(weight, 12)) for term, weight in tags
                  if not term.isdecimal() and weight > 0]
        return tuple(sorted(values, key=lambda item: (-item[1], item[0]))[:count])
