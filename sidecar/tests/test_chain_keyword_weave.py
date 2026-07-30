"""关键词植入指令在链上的接线 —— 每个 pass 都要带，别只管 step0。

链的精修 pass（step1+）拿到的是上段输出：如果只有 step0 下了植入指令，
后面的「去AI味/平台适配」pass 很容易把引言/结尾里刚织进去的关键词又
润掉。所以 _prompt_for 必须把 state.keyword 一路传给 build_refine_prompt。
"""
from csm_sidecar.services import chain_service


class _Client:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, *, system, user):
        self.calls.append((system, user))
        return self.outputs[len(self.calls) - 1]


def _steps(n):
    return [
        chain_service.ChainStepInput(f"s{i}", "persona", f"S{i}", "风格")
        for i in range(n)
    ]


def _run(keyword, outputs, steps=2):
    chain_service.reset_for_test()
    c = _Client(outputs)
    chain_service.run_chain(
        "job-weave", _steps(steps), draft="## 章节\n毛坯", keyword=keyword,
        title=None, angle_directive=None, brand_facts=None,
        provider=None, model=None, client=c, cache=True,
    )
    return c


def test_every_pass_carries_weave_clause():
    c = _run("空气净化器", ["## 章节\n第一轮", "## 章节\n第二轮"])
    assert all("【关键词植入】" in user for _, user in c.calls)
    assert all("「空气净化器」" in user for _, user in c.calls)


def test_empty_keyword_no_clause_anywhere():
    c = _run("", ["## 章节\n第一轮", "## 章节\n第二轮"])
    assert all("【关键词植入】" not in user for _, user in c.calls)


def test_rerun_refine_pass_keeps_the_clause():
    _run("空气净化器", ["## 章节\n第一轮", "## 章节\n第二轮"])

    class _Rerun:
        def __init__(self):
            self.calls = []

        def complete(self, *, system, user):
            self.calls.append(user)
            return "## 章节\n重跑输出"

    rc = _Rerun()
    chain_service.rerun("job-weave", 1, client=rc)
    assert "【关键词植入】" in rc.calls[0]
