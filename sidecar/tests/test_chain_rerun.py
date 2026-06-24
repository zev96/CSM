import pytest
from csm_sidecar.services import chain_service


class SeqClient:
    def __init__(self, start=100): self.n = start
    def complete(self, *, system, user, temperature=None):
        self.n += 1; return f"R{self.n}"


# FakeClient / _steps are shared via conftest fixtures (fake_chain_client /
# chain_steps): sidecar/tests has no __init__, so the cross-file relative
# import `from .test_chain_service import ...` doesn't resolve under the
# repo's rootdir-based pytest config — the convention is conftest fixtures.
def _run_two(client, steps):
    chain_service.reset_for_test()
    chain_service.run_chain("j", steps(("p","persona","人设","P"), ("h","humanize","去AI味","H")),
        draft="d", keyword="k", title=None, angle_directive=None, brand_facts=None,
        provider="mock", model=None, client=client, checkpoint=lambda: None, on_pass=lambda p: None)


def test_rerun_cascades_from_k(monkeypatch, fake_chain_client, chain_steps):
    _run_two(fake_chain_client, chain_steps)
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: SeqClient())
    res = chain_service.rerun("j", 1)            # 重跑 pass1（末段）
    assert res["passes"][1]["output"].startswith("R")
    assert res["final_text"] == res["passes"][-1]["output"]


def test_rerun_pass0_recascades_all(monkeypatch, fake_chain_client, chain_steps):
    _run_two(fake_chain_client, chain_steps)
    monkeypatch.setattr(chain_service.llm_factory, "build_client", lambda **k: SeqClient())
    res = chain_service.rerun("j", 0)            # 重跑 step0 → pass1 也跟着重跑
    assert res["passes"][0]["output"].startswith("R")
    assert res["passes"][1]["output"].startswith("R")  # 级联


def test_rerun_unknown_job():
    chain_service.reset_for_test()
    with pytest.raises(KeyError):
        chain_service.rerun("nope", 0)


def test_rerun_index_out_of_range(fake_chain_client, chain_steps):
    _run_two(fake_chain_client, chain_steps)
    with pytest.raises(IndexError):
        chain_service.rerun("j", 9)
