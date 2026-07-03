from typing import Any

import pytest

from csm_core.config import AppConfig, BrandMemoryConfig, ContractConfig
from csm_sidecar.services import chain_service, generate_service


class _FakeClient:
    def __init__(self, out: str):
        self.out = out
        self.prompts: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str, temperature=None) -> str:
        self.prompts.append((system, user))
        return self.out


@pytest.fixture(autouse=True)
def _chain_reset():
    chain_service.reset_for_test()
    yield
    chain_service.reset_for_test()


def test_run_chain_threads_contract_mode():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j1", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client,
        contract_mode="aggressive")
    assert "精炼模式" in client.prompts[0][1]
    st = chain_service.get_state("j1")
    assert st is not None and st.contract_mode == "aggressive"


def test_run_chain_default_conservative_and_cached():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j2", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client)
    assert "润色模式" in client.prompts[0][1]


def test_run_chain_cache_false_not_cached():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j3", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client, cache=False)
    assert chain_service.get_state("j3") is None


def test_rerun_reuses_contract_mode():
    client = _FakeClient("out")
    chain_service.run_chain(
        "j4", [], draft="d", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider=None, model=None, client=client,
        contract_mode="aggressive")
    client2 = _FakeClient("out2")
    chain_service.rerun("j4", 0, client=client2)
    assert "精炼模式" in client2.prompts[0][1]
