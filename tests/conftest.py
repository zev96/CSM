from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MINI_VAULT = FIXTURES_DIR / "mini_vault" / "营销资料库"


@pytest.fixture
def mini_vault_path() -> Path:
    return MINI_VAULT
