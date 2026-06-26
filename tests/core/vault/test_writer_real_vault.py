"""真实库只读回归：仅验证 body_shape 探测，绝不 commit/写盘。"""
from pathlib import Path
import pytest
from csm_core.vault.scanner import scan_vault
from csm_core.vault import folder_profile as fp

_VAULT = Path(r"D:\家电组共享\DATA")

pytestmark = pytest.mark.skipif(
    not _VAULT.exists(), reason="真实 vault 不可用（CI/他机）")


def test_real_vault_body_shape_detection():
    idx = scan_vault(_VAULT)
    profiles = {p.rel_folder: p for p in fp.list_writable_folders(idx)}
    挑选 = next((p for r, p in profiles.items() if r.endswith("挑选攻略")), None)
    参数 = next((p for r, p in profiles.items() if r.endswith("产品参数")), None)
    assert 挑选 is not None and 挑选.body_shape == "variants"
    assert 参数 is not None and 参数.body_shape == "spec_table"
