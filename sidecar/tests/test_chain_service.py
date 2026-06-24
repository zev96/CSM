from csm_sidecar.services import chain_service
from csm_core.llm.prompts import build_prompt, PromptInputs


class FakeClient:
    def __init__(self): self.calls = []
    def complete(self, *, system, user, temperature=None):
        self.calls.append((system, user))
        return f"OUT[{len(self.calls)}]"


def _steps(*specs):
    return [chain_service.ChainStepInput(skill_id=s[0], role=s[1], name=s[2], body=s[3]) for s in specs]


def test_single_step_is_build_prompt(monkeypatch):
    chain_service.reset_for_test()
    c = FakeClient()
    state = chain_service.run_chain(
        "job1", _steps(("persona", "persona", "人设", "人设BODY")),
        draft="毛坯", keyword="无线吸尘器", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=c,
        checkpoint=lambda: None, on_pass=lambda p: None,
    )
    # step0 用 build_prompt：system/user 与 build_prompt 一致
    exp_sys, exp_user = build_prompt(PromptInputs(
        user_skill_prompt="人设BODY", keyword="无线吸尘器", draft="毛坯",
        brand_facts=None, title=None, angle_directive=None))
    assert c.calls[0] == (exp_sys, exp_user)
    assert state.final_text == "OUT[1]"
    assert len(state.passes) == 1


def test_multi_step_feeds_prev_and_emits():
    chain_service.reset_for_test()
    c = FakeClient(); seen = []
    state = chain_service.run_chain(
        "job2", _steps(("p","persona","人设","P"), ("h","humanize","去AI味","H")),
        draft="毛坯", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=c,
        checkpoint=lambda: None, on_pass=lambda p: seen.append(p.index),
    )
    # step1 是精修：user 含 step0 输出
    assert "OUT[1]" in c.calls[1][1]
    assert state.final_text == "OUT[2]"
    assert seen == [0, 1]
    assert chain_service.get_state("job2") is state


def test_empty_steps_runs_one_compose_pass():
    chain_service.reset_for_test()
    c = FakeClient()
    state = chain_service.run_chain(
        "job3", [], draft="毛坯", keyword="k", title=None, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=c,
        checkpoint=lambda: None, on_pass=lambda p: None)
    assert len(state.passes) == 1 and c.calls[0][0] == ""  # 空 body → system 空
