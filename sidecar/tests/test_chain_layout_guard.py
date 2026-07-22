"""卡片排版守卫在链里的行为：破坏结构的 pass 回退，措辞润色照常放行。"""
from __future__ import annotations

from csm_core.llm import layout_guard
from csm_core.llm.layout_guard import CardSignature
from csm_sidecar.services import chain_service

_SIG = CardSignature(
    titles=("霍尼韦尔 H-Max", "欧瑞达X9"),
    labels=("市场口碑数据",),
)

_CARD = """### 综合性能首选 TOP1. 霍尼韦尔 H-Max

**市场口碑数据** ：全球500强，天猫五项TOP1。

### 热门品牌 TOP2. 欧瑞达X9

**市场口碑数据** ：销量稳步增长。"""


class _Client:
    def __init__(self, outputs: list[str]):
        self.outputs = outputs
        self.seen: list[str] = []

    def complete(self, *, system: str, user: str) -> str:
        self.seen.append(user)
        return self.outputs[len(self.seen) - 1]


def _steps(n: int):
    return [
        chain_service.ChainStepInput(f"s{i}", "persona", f"S{i}", "写作风格")
        for i in range(n)
    ]


def _run(client, *, preserve: bool, steps=1, cache=False):
    chain_service.reset_for_test()
    return chain_service.run_chain(
        "job", _steps(steps), draft=_CARD, keyword="空气净化器",
        title=None, angle_directive=None, brand_facts=None,
        provider=None, model=None, client=client,
        card_signature=_SIG if preserve else None, cache=cache,
    )


def test_structure_destroying_pass_is_rolled_back():
    flattened = _CARD.replace("### ", "").replace("\n\n", "\n")
    state = _run(_Client([flattened]), preserve=True)
    assert state.final_text == _CARD              # 回退到输入
    assert state.layout_rejections
    assert "已回退本轮润色" in state.layout_rejections[0]


def test_wording_polish_passes_through():
    polished = _CARD.replace("销量稳步增长", "销量一路走高，口碑扎实")
    state = _run(_Client([polished]), preserve=True)
    assert state.final_text == polished
    assert state.layout_rejections == []


def test_guard_off_keeps_today_behaviour():
    """没有卡片区的文章：守卫不启用，链输出原样通过（零回归）。"""
    flattened = _CARD.replace("### ", "")
    state = _run(_Client([flattened]), preserve=False)
    assert state.final_text == flattened
    assert state.layout_rejections == []


def test_layout_clause_injected_into_every_pass():
    good = _CARD.replace("销量稳步增长", "销量走高")
    client = _Client([good, good])
    _run(client, preserve=True, steps=2)
    assert all(layout_guard.LAYOUT_CLAUSE in u for u in client.seen)


def test_later_pass_still_polishes_after_a_rollback():
    """一轮被拦下，链不中断 —— 后续 pass 仍在完好结构上继续润色。"""
    broken = _CARD.replace("### ", "")
    good = _CARD.replace("全球500强", "全球五百强")
    state = _run(_Client([broken, good]), preserve=True, steps=2)
    assert state.final_text == good
    assert len(state.layout_rejections) == 1


def test_rerun_is_guarded_too():
    """「重跑这一段」是最容易把卡片揉平的入口，同样要过守卫。"""
    good = _CARD.replace("销量稳步增长", "销量走高")
    state = _run(_Client([good]), preserve=True, cache=True)
    assert state.final_text == good

    broken = _Client(["全部揉成一段流水文，没有标题也没有加粗。"])
    out = chain_service.rerun("job", 0, client=broken)
    assert out["final_text"] == _CARD          # 回退到 pass 输入
    assert chain_service.get_state("job").layout_rejections
