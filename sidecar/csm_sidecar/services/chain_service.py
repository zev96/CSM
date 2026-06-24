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
) -> ChainState:
    eff = steps or [ChainStepInput(None, "persona", "", None)]
    state = ChainState(
        job_id=job_id, draft=draft, keyword=keyword, title=title,
        angle_directive=angle_directive, brand_facts=brand_facts,
        provider=provider, model=model, steps=eff,
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
    _cache_put(state)
    return state
