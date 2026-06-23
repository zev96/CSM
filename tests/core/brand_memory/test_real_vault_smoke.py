import pytest
from pathlib import Path
from csm_core.vault.scanner import scan_vault
from csm_core.brand_memory.resolver import resolve_memory

VAULT = Path(r"D:\家电组共享\DATA\营销资料库")


@pytest.mark.integration
@pytest.mark.skipif(not VAULT.exists(), reason="真实 vault 不在本机")
def test_cewey_ds18_resolves_from_real_vault():
    index = scan_vault(VAULT)
    mem = resolve_memory("CEWEY", "DS18", "吸尘器", index, own_brands={"CEWEY"})
    assert mem.role == "主推"
    assert mem.specs.get("吸力(AW)") and mem.specs["吸力(AW)"].numbers == [220.0]
    assert mem.scripts, "希喂推荐内容 话术应被解析到"
    assert mem.endorsements, "品牌背书应被解析到"
