"""skill 链多-pass 执行 + 缓存 + 逐 pass 重跑（仿 assembler_service）。

step[0] = 组装 pass（build_prompt：毛坯+事实+角度+标题）；
step[k≥1] = 精修 pass（build_refine_prompt：上段输出+skill+保守约束）。
链状态按 job_id LRU 缓存，供 POST /api/chain/rerun 逐 pass 重跑。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from csm_core.llm import pricing
from csm_core.llm.prompts import PromptInputs, build_prompt, build_refine_prompt

from . import llm_factory


@dataclass
class ChainStepInput:
    skill_id: str | None
    role: str
    name: str
    body: str | None


@dataclass
class ChainPass:
    index: int
    skill_id: str | None
    role: str
    skill_name: str
    input: str
    output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "skill_id": self.skill_id, "role": self.role,
            "skill_name": self.skill_name,
            "input_chars": len(self.input), "output_chars": len(self.output),
            "input_tokens": pricing.estimate_tokens(self.input),
            "output_tokens": pricing.estimate_tokens(self.output),
            "output": self.output,
        }


@dataclass
class ChainState:
    job_id: str
    draft: str
    keyword: str
    title: str | None
    angle_directive: str | None
    brand_facts: str | None
    provider: str | None
    model: str | None
    steps: list[ChainStepInput]
    passes: list[ChainPass] = field(default_factory=list)
    contract_mode: str = "conservative"   # rerun 复用缓存值，保持同契约重跑

    @property
    def final_text(self) -> str:
        return self.passes[-1].output if self.passes else ""


_cache: "OrderedDict[str, ChainState]" = OrderedDict()
_lock = threading.Lock()
MAX_CACHE = 50


def reset_for_test() -> None:
    with _lock:
        _cache.clear()


def get_state(job_id: str) -> ChainState | None:
    with _lock:
        st = _cache.get(job_id)
        if st is not None:
            _cache.move_to_end(job_id)
        return st


def _cache_put(state: ChainState) -> None:
    with _lock:
        _cache[state.job_id] = state
        _cache.move_to_end(state.job_id)
        while len(_cache) > MAX_CACHE:
            _cache.popitem(last=False)


def _prompt_for(state: ChainState, idx: int, prev_output: str) -> tuple[str, str, str]:
    """返回 (system, user, input_text) for pass idx。idx==0 用 build_prompt；否则精修。"""
    step = state.steps[idx] if idx < len(state.steps) else ChainStepInput(None, "persona", "", None)
    if idx == 0:
        system, user = build_prompt(PromptInputs(
            user_skill_prompt=step.body, keyword=state.keyword, draft=state.draft,
            brand_facts=state.brand_facts, title=state.title,
            angle_directive=state.angle_directive,
            contract_mode=state.contract_mode,
        ))
        return system, user, state.draft
    system, user = build_refine_prompt(step.body, prev_output)
    return system, user, prev_output


def run_chain(
    job_id: str, steps: list[ChainStepInput], *,
    draft: str, keyword: str, title: str | None, angle_directive: str | None,
    brand_facts: str | None, provider: str | None, model: str | None,
    client: Any | None = None,
    checkpoint: Callable[[], None] = lambda: None,
    on_pass: Callable[[ChainPass], None] = lambda p: None,
    contract_mode: str = "conservative", cache: bool = True,
) -> ChainState:
    eff = steps or [ChainStepInput(None, "persona", "", None)]
    state = ChainState(
        job_id=job_id, draft=draft, keyword=keyword, title=title,
        angle_directive=angle_directive, brand_facts=brand_facts,
        provider=provider, model=model, steps=eff,
        contract_mode=contract_mode,
    )
    if client is None:
        client = llm_factory.build_client(provider=provider, model=model)
    prev = ""
    for idx, step in enumerate(eff):
        checkpoint()
        system, user, input_text = _prompt_for(state, idx, prev)
        out = client.complete(system=system, user=user)
        p = ChainPass(index=idx, skill_id=step.skill_id, role=step.role,
                      skill_name=step.name, input=input_text, output=out)
        state.passes.append(p)
        on_pass(p)
        prev = out
    if cache:
        _cache_put(state)
    return state


def rerun(
    job_id: str, pass_index: int, *, client: Any | None = None,
    checkpoint: Callable[[], None] = lambda: None,
    on_pass: Callable[[ChainPass], None] = lambda p: None,
) -> dict[str, Any]:
    """从 pass_index 起重跑（级联 pass_index..N），更新缓存，返回 {passes, final_text}。

    on_pass 逐段回调（流式）；checkpoint 每段前调（可取消）。两者默认 no-op =
    同步调用零回归。"""
    state = get_state(job_id)
    if state is None:
        raise KeyError(f"unknown job_id: {job_id} (chain cache miss)")
    if not (0 <= pass_index < len(state.passes)):
        raise IndexError(f"pass_index {pass_index} out of range (0..{len(state.passes)-1})")
    if client is None:
        client = llm_factory.build_client(provider=state.provider, model=state.model)
    # 末段之前的输出即 pass_index 的 prev（step0 的 prev 不参与，_prompt_for 自取 draft）
    prev = state.passes[pass_index - 1].output if pass_index >= 1 else ""
    for idx in range(pass_index, len(state.passes)):
        checkpoint()
        system, user, input_text = _prompt_for(state, idx, prev)
        out = client.complete(system=system, user=user)
        old = state.passes[idx]
        p = ChainPass(
            index=idx, skill_id=old.skill_id, role=old.role,
            skill_name=old.skill_name, input=input_text, output=out)
        state.passes[idx] = p
        on_pass(p)
        prev = out
    _cache_put(state)
    return {"passes": [p.to_dict() for p in state.passes], "final_text": state.final_text}
