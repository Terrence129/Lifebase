"""约束门禁测试：文档链接、红线唯一归属、gitignore 覆盖与层级边界。

这些测试是 `AGENTS.md` 约束的执行门禁，随 pytest 在本地收工校验与 CI 中强制运行。
每个门禁只证明它写明的事：链接门禁只证「本地链接目标存在」而不证锚点精确；短语门禁
按中英特征短语匹配 `.md` 文件，防无意识复制红线，不防刻意改写措辞。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 不进入扫描的目录（虚拟环境、缓存与 git 元数据）
EXCLUDED_DIRS = {".git", ".venv", ".pytest_cache", ".ruff_cache", "__pycache__"}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# 红线特征短语（与 AGENTS.md §2 红线一一对应，含英文变体以拦截复制）。
# 唯一合法存放处是 AGENTS.md 本身，其余 .md 文件出现即失败。
RED_LINE_PHRASES = (
    "永不进入 git",
    "RAW 数据不可变",
    "LLM 输出不是事实",
    "最小云端暴露",
    "不提交密钥",
    "聊天记录属于第三方",
    "commit personal data",
    "commit API keys",
    "public raw datasets",
    "upload entire vault",
)

# 显式豁免（豁免本身必须可见、可审）：
# - README.md：面向人的安全摘要，红线一句话总结后紧跟唯一事实源指针；
# - ADR-003：历史决策记录中的撤销说明，引用被恢复规则的原文。
PHRASE_WHITELIST: dict[str, tuple[str, ...]] = {
    "README.md": ("永不进入 git",),
    "docs/adr/ADR-003-开发数据例外.md": ("永不进入 git",),
}

GITIGNORE_MUST_COVER = ("data/", "inbox/", "*.db", "*.parquet", ".env")


def _md_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.md"):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def test_local_md_links_resolve() -> None:
    """仓库内 .md 的本地链接目标必须存在（只证存在，不证锚点）。"""
    broken: list[tuple[Path, str]] = []
    for md in _md_files():
        for target in LINK_RE.findall(md.read_text(encoding="utf-8")):
            target = target.strip()
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path = (md.parent / target.split("#", 1)[0]).resolve()
            if not path.exists():
                broken.append((md, target))
    assert not broken, f"断链 {len(broken)} 处：{broken}"


def test_red_line_phrases_stay_in_agents_md() -> None:
    """红线特征短语只允许出现在 AGENTS.md（白名单显式豁免，见文件头部注释）。"""
    hits: list[tuple[Path, str]] = []
    for md in _md_files():
        if md == ROOT / "AGENTS.md":
            continue
        whitelist = PHRASE_WHITELIST.get(md.relative_to(ROOT).as_posix(), ())
        for phrase in RED_LINE_PHRASES:
            if phrase in whitelist:
                continue
            if phrase in md.read_text(encoding="utf-8"):
                hits.append((md, phrase))
    assert not hits, f"红线复制 {len(hits)} 处（单一事实源见 AGENTS.md）：{hits}"


def test_gitignore_covers_local_data_and_env() -> None:
    """AGENTS.md §3 要求的忽略模式必须真实存在（按行精确匹配）。"""
    lines = [
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    missing = [pattern for pattern in GITIGNORE_MUST_COVER if pattern not in lines]
    assert not missing, f".gitignore 缺少模式：{missing}"


def test_boundary_layers_have_no_code() -> None:
    """graph/ 与 humanos/ 是边界占位层，禁止出现 Python 代码。"""
    offenders = [
        path
        for sub in ("graph", "humanos")
        for path in (ROOT / "src" / "lifebase" / sub).rglob("*.py")
    ]
    assert not offenders, f"边界层出现代码：{offenders}"


def test_no_project_level_venv() -> None:
    """开发与校验一律用 conda lifebase 环境；项目级 .venv 会让 uv 绕过 conda。

    CI 通过 `UV_PROJECT_ENVIRONMENT` 把 uv 环境放到仓库外（见 ci.yml），
    因此「仓库内无 .venv」在本地与 CI 都成立，本门禁无条件执行。
    """
    assert not (ROOT / ".venv").exists(), "项目级 .venv 不应存在（用 conda `lifebase` 环境）"


def test_vault_does_not_import_graph() -> None:
    """vault/ 不 import graph/（分层约束）。"""
    offenders: list[tuple[Path, str]] = []
    for py in (ROOT / "src" / "lifebase" / "vault").rglob("*.py"):
        for line_no, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "lifebase.graph" in line or "from lifebase import graph" in line:
                offenders.append((py, f"{line_no}: {line.strip()}"))
    assert not offenders, f"vault 引用了 graph：{offenders}"
