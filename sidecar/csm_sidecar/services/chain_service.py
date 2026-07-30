"""skill 链多-pass 执行 + 缓存 + 逐 pass 重跑（仿 assembler_service）。

step[0] = 组装 pass（build_prompt：毛坯+事实+角度+标题）；
step[k≥1] = 精修 pass（build_refine_prompt：上段输出+skill+保守约束）。
链状态按 job_id LRU 缓存，供 POST /api/chain/rerun 逐 pass 重跑。
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable

from csm_core.llm import layout_guard, pricing, title_guard
from csm_core.llm.prompts import PromptInputs, build_prompt, build_refine_prompt

from . import llm_factory

logger = logging.getLogger(__name__)


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
    # 守卫说明：本轮输出被排版守卫整轮回退 / 标题守卫纠正时的人话说明；
    # None = 干净通过。挂在 pass 上（随 SSE pass / done 透传前端）——
    # 回退只写后端日志的话，用户拿回和输入几乎一样的成稿，只会以为
    # 「润色没干活」。rerun 重建 pass 对象，note 天然只反映本轮。
    guard_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index, "skill_id": self.skill_id, "role": self.role,
            "skill_name": self.skill_name,
            "input_chars": len(self.input), "output_chars": len(self.output),
            "input_tokens": pricing.estimate_tokens(self.input),
            "output_tokens": pricing.estimate_tokens(self.output),
            "output": self.output,
            "guard_note": self.guard_note,
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
    # 榜单卡片区的结构特征（标题/小节名）。非空 = prompt 加排版硬约束 +
    # 逐 pass 卡片区指纹校验。空 = 今天行为。
    card_signature: Any = None
    # 被结构校验拦下并回退的 pass 说明 —— 链级聚合，供 generate_service 的
    # warning 日志用；面向用户的透传走每个 ChainPass.guard_note（SSE/done）。
    layout_rejections: list[str] = field(default_factory=list)
    # 被标题守卫纠正的 pass 说明（同上）。
    title_corrections: list[str] = field(default_factory=list)

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
            preserve_layout=bool(state.card_signature),
        ))
        return system, user, state.draft
    # 与 step0 同口径：判据是「用户有没有定标题」，不是「上段输出里有没有
    # 标题行」。毛坯文不产 H1，所以「用户有标题 + 上段无 H1」恰恰是主路径 ——
    # 只看上段的话这里会下成 keyword_title_clause，反过来邀请 LLM 加个标题，
    # 而链输出本不该带标题（硬塞 H1 会让字数/查重/事实核对的输入全变样）。
    if (state.title or "").strip() or title_guard.leading_h1(prev_output) is not None:
        title_rule = title_guard.TITLE_CLAUSE
    elif state.keyword:
        title_rule = title_guard.keyword_title_clause(state.keyword)
    else:
        title_rule = ""
    system, user = build_refine_prompt(
        step.body, prev_output, preserve_layout=bool(state.card_signature),
        title_rule=title_rule, keyword=state.keyword,
    )
    return system, user, prev_output


def _guard_layout(state: ChainState, idx: int, before: str, after: str) -> tuple[str, str | None]:
    """卡片区结构校验 —— 破坏结构的这一 pass 直接回退到输入文本。

    prompt 里已经下了排版硬约束，但 LLM 不保证遵守；榜单卡片被润成流水文
    用户就拿不到榜单了。保结构优先于保润色：这一 pass 的成果作废，链继续
    往下走（后面的 pass 仍有机会在结构完好的文本上润色）。

    返回 ``(文本, 守卫说明|None)`` —— 说明挂到 ChainPass.guard_note 透传前端。
    """
    if not state.card_signature:
        return after, None
    violation = layout_guard.check(before, after, state.card_signature)
    if violation is None:
        return after, None
    state.layout_rejections.append(f"pass {idx}: {violation} —— 已回退本轮润色")
    logger.warning(
        "chain job %s pass %s 破坏卡片排版（%s），回退到输入文本",
        state.job_id, idx, violation,
    )
    return before, f"{violation} —— 本轮润色已回退，保持上一轮正文"


def _guard_title(state: ChainState, idx: int, before: str, after: str) -> tuple[str, str | None]:
    """标题守卫 —— 润色不得新增/改写/删除文章标题，只纠正标题那一行。

    prompt 里已经下了标题硬约束，但 LLM 不保证遵守。正文首行的 H1 就是全链路
    认定的文章标题（ensure_title/extract_title/前端 effectiveTitle 同口径），
    被 LLM 换掉的话，用户选的标题（以及标题里那个必须原样保留的关键词）就
    悄悄没了。和排版守卫的整轮回退不同，这里只动标题行 —— 正文的润色成果
    照常保留。

    返回 ``(文本, 守卫说明|None)`` —— 说明挂到 ChainPass.guard_note 透传前端。
    """
    fixed, note = title_guard.enforce(
        before, after, title=state.title, keyword=state.keyword,
    )
    if note is None:
        return after, None
    state.title_corrections.append(f"pass {idx}: {note}")
    logger.warning("chain job %s pass %s 标题守卫：%s", state.job_id, idx, note)
    return fixed, note


def run_chain(
    job_id: str, steps: list[ChainStepInput], *,
    draft: str, keyword: str, title: str | None, angle_directive: str | None,
    brand_facts: str | None, provider: str | None, model: str | None,
    client: Any | None = None,
    checkpoint: Callable[[], None] = lambda: None,
    on_pass: Callable[[ChainPass], None] = lambda p: None,
    contract_mode: str = "conservative", cache: bool = True,
    card_signature: Any = None,
) -> ChainState:
    eff = steps or [ChainStepInput(None, "persona", "", None)]
    state = ChainState(
        job_id=job_id, draft=draft, keyword=keyword, title=title,
        angle_directive=angle_directive, brand_facts=brand_facts,
        provider=provider, model=model, steps=eff,
        contract_mode=contract_mode,
        card_signature=card_signature,
    )
    if client is None:
        client = llm_factory.build_client(provider=provider, model=model)
    prev = ""
    for idx, step in enumerate(eff):
        checkpoint()
        system, user, input_text = _prompt_for(state, idx, prev)
        out = client.complete(system=system, user=user)
        out, layout_note = _guard_layout(state, idx, input_text, out)
        out, title_note = _guard_title(state, idx, input_text, out)
        note = "；".join(n for n in (layout_note, title_note) if n)
        p = ChainPass(index=idx, skill_id=step.skill_id, role=step.role,
                      skill_name=step.name, input=input_text, output=out,
                      guard_note=note or None)
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
        # 「重跑这一段」同样要过排版 / 标题守卫 —— 它恰恰是最容易把卡片揉平、
        # 把标题改掉的入口。
        out, layout_note = _guard_layout(state, idx, input_text, out)
        out, title_note = _guard_title(state, idx, input_text, out)
        note = "；".join(n for n in (layout_note, title_note) if n)
        old = state.passes[idx]
        p = ChainPass(
            index=idx, skill_id=old.skill_id, role=old.role,
            skill_name=old.skill_name, input=input_text, output=out,
            guard_note=note or None)
        state.passes[idx] = p
        on_pass(p)
        prev = out
    _cache_put(state)
    return {"passes": [p.to_dict() for p in state.passes], "final_text": state.final_text}
