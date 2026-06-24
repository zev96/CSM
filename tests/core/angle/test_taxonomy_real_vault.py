import os
from pathlib import Path
import pytest
from csm_core.vault.scanner import scan_vault
from csm_core.brand_memory.resolver import resolve_memory
from csm_core.angle.taxonomy import SELLPOINT_DIMENSIONS

VAULT = os.environ.get("CSM_REAL_VAULT")  # e.g. D:\家电组共享\DATA\营销资料库


@pytest.mark.skipif(not VAULT, reason="set CSM_REAL_VAULT to run")
def test_sellpoint_keys_exist_in_real_scripts():
    index = scan_vault(Path(VAULT))
    mem = resolve_memory("CEWEY", "DS18", "吸尘器", index, own_brands={"CEWEY"})
    real_dims = set(mem.scripts.keys())
    declared = {d["key"] for d in SELLPOINT_DIMENSIONS}
    missing = declared - real_dims
    assert not missing, f"词表维度键在真实话术里找不到：{missing}（对齐 resolver 维度名）"
