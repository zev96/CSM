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
    return MINI_VAULT
