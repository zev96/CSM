from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MINI_VAULT = FIXTURES_DIR / "mini_vault" / "营销资料库"


@pytest.fixture(autouse=True)
def _reset_shared_comment_store():
    """评论区共享快照仓是进程级单例——每测重置,防跨测试串快照/串 vid 缓存。"""
    from csm_core.monitor.platforms import _comment_shared
    _comment_shared.reset_shared_store()
    yield


@pytest.fixture
def mini_vault_path() -> Path:
    """``营销资料库`` 那一层 —— 直接按模块相对路径取笔记的测试用它。"""
    return MINI_VAULT


@pytest.fixture
def mini_vault_root() -> Path:
    """**整个资料库根**（``营销资料库`` 的父目录）—— 跑真实模板的测试用它。

    模板里的目录有的带 ``营销资料库/`` 前缀有的不带（``by_module`` 是子序列
    匹配，两种写法都能命中）。root 指进 ``营销资料库`` 里面的话，这一层就成了
    root 自己、不再出现在笔记的相对路径里，带前缀的那些块**永远匹配不到** ——
    整条链 EmptyPoolError。生产里 root 是用户的 DATA 目录、``营销资料库`` 是
    它的子目录，这个 fixture 与之对齐。
    """
    return FIXTURES_DIR / "mini_vault"
