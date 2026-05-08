"""Auto-generate article titles from a keyword + template type.

Pipeline:
    vault scan
        → pick formula notes whose ``适用模板类型`` matches the template
        → build a few-shot prompt (with hard rule: keyword preserved verbatim)
        → ask the LLM for a JSON list of 3 candidates
        → validate (keyword preserved, length, no banned chars)
        → on persistent failure, fall back to a mechanical fill that
          ALWAYS preserves the keyword (contextual suffix when the
          keyword is already a question/decision phrase)

The public entry-point is :func:`generate_titles`. It always returns at
least one usable title — UI code never has to special-case "LLM failed".

vault layout convention
-----------------------
``<vault>/营销资料库/标题模块/<模板类型>/<标题类型>.md`` with frontmatter::

    ---
    标题类型: 一问一答型
    适用模板类型: [导购文]      # 字符串或列表都行
    公式: "[关键词] [疑问词]好用？推荐+[利益]+[关键词]牌子分享"
    示例:
      - "无线吸尘器哪款好用？实测分享几款真正能打的"
      - "扫地机器人哪种值得买？看完这篇不踩坑"
    ---

Notes outside this convention are simply ignored.
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from csm_core.llm.client import LLMClient
from csm_core.vault.scanner import VaultIndex, scan_vault

logger = logging.getLogger(__name__)


# 标题模块在 vault 里的位置 — 与 引言模块/科普模块/产品模块 同级。
TITLE_MODULE = "营销资料库/标题模块"

# 让 LLM 一次出几条候选。
DEFAULT_N_CANDIDATES = 3

# 标题生成专用的采样温度。比润色（默认 0.7+）显著低 — 标题对结构服从、
# 关键词原样保留是硬要求，温度过高会让 LLM "发挥创意"擅自改写关键词。
# 0.4 在保留少量风格变化（3 条候选不会撞车）和服从约束之间是个稳态。
DEFAULT_TEMPERATURE = 0.4

# Prompt 里给 LLM 的"目标字数"窗口（紧）。
PROMPT_MIN_CHARS = 24
PROMPT_MAX_CHARS = 32

# 校验时的"可接受字数"窗口（宽，给 LLM 一点偏差余量；超出就拒收）。
ACCEPT_MIN_CHARS = 18
ACCEPT_MAX_CHARS = 36

# 触发拒收的字符（智能引号会破坏复制粘贴体验；后续可按需扩 Emoji 范围）。
_BANNED_CHARS = "“”‘’"


@dataclass
class TitleFormula:
    """One title-formula note loaded from the vault."""

    note_id: str
    title_kind: str             # 标题类型：一问一答型 / 避坑型 / 疑问评测型 / ...
    template_types: list[str]   # 适用模板类型 (e.g. ["导购文"])
    formula: str                # 原始公式串（带 [关键词] [疑问词] 等占位符）
    examples: list[str]         # 真实样例标题，做 few-shot


# ── Vault loading ──────────────────────────────────────────────────────


def _normalize_list(val: object) -> list[str]:
    """Frontmatter list/string → list[str]; everything else → []."""
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        return [val.strip()] if val.strip() else []
    return []


def load_formulas(
    index: VaultIndex,
    *,
    template_type: str | None = None,
) -> list[TitleFormula]:
    """Pick formula notes that apply to *template_type*.

    Vault frontmatter convention is intentionally lax: ``适用模板类型`` may
    be a single string or a list. Notes with no value at all are kept and
    treated as "applies to every template type" — this lets the user drop
    a generic catch-all formula in without ceremony.
    """
    notes = index.by_module(TITLE_MODULE)
    out: list[TitleFormula] = []
    for n in notes:
        fm = n.frontmatter
        applicable = _normalize_list(fm.get("适用模板类型"))
        if template_type and applicable and template_type not in applicable:
            continue
        examples = _normalize_list(fm.get("示例"))
        formula = str(fm.get("公式", "")).strip()
        title_kind = str(fm.get("标题类型", n.id)).strip() or n.id
        out.append(TitleFormula(
            note_id=n.id,
            title_kind=title_kind,
            template_types=applicable,
            formula=formula,
            examples=examples,
        ))
    return out


# ── Prompt building ────────────────────────────────────────────────────


def build_title_prompt(
    keyword: str,
    template_type: str | None,
    formulas: Sequence[TitleFormula],
    *,
    n_candidates: int = DEFAULT_N_CANDIDATES,
    target_chars_min: int = PROMPT_MIN_CHARS,
    target_chars_max: int = PROMPT_MAX_CHARS,
) -> tuple[str, str]:
    """Return (system, user) prompts for the title-gen LLM call.

    Long-tail keywords (>= 6 chars) get extra emphasis — without it the
    LLM tends to treat them as separable phrases ("无线吸尘器哪款好用"
    becomes "无线吸尘器" + "哪款" + "好用" rearranged), which breaks the
    substring-match validation downstream and forces a fallback.
    """
    type_label = template_type or "通用"
    is_long_tail = len(keyword) >= 6

    # ── Public formula list (visible structure for the LLM to mirror) ──
    formula_lines = [
        f"- [{f.title_kind}] {f.formula}"
        for f in formulas if f.formula
    ]
    formulas_block = (
        "\n".join(formula_lines)
        if formula_lines else "（无显式公式，按下面的样例风格自由发挥）"
    )

    # ── Few-shot examples grouped by 标题类型 ──────────────────────────
    sample_blocks: list[str] = []
    for f in formulas:
        if not f.examples:
            continue
        head = f"[{f.title_kind}]"
        body = "\n".join(f"- {ex}" for ex in f.examples[:3])
        sample_blocks.append(f"{head}\n{body}")
    samples_block = (
        "\n\n".join(sample_blocks)
        if sample_blocks else "（暂无样例，可参考公式自行生成）"
    )

    # ── Keyword-preservation rule with concrete ✓/✗ contrast ───────────
    # The contrast pair is dynamically constructed from the user's actual
    # keyword so the LLM sees its real input, not a generic placeholder.
    bad_sample = _construct_bad_example(keyword)
    keyword_rule = (
        f'1. 标题里必须包含 **一字不差、连续完整** 的字符串 "{keyword}"。\n'
        f'   ✓ 正确：…… {keyword}…… 或 …… {keyword}？……（连续未拆分）\n'
        f'   ✗ 错误：{bad_sample}（关键词被拆开/插入字符/部分替换）\n'
    )
    if is_long_tail:
        keyword_rule += (
            f'   ⚠ 注意：本次的关键词"{keyword}"是 **长尾关键词**（{len(keyword)} 字），'
            f'不是一个可以重组的短语集合。它就是一个完整的搜索词，必须当作不可分割的整体使用。\n'
        )

    system = (
        "你是一名擅长写中文营销标题的资深编辑。"
        "你的输出永远是合法的 JSON，不要附加 markdown 围栏、注释或解释。"
        "你最重要的纪律是：用户给你的关键词必须一字不差地原样保留。"
    )
    user = (
        f"任务：为关键词【{keyword}】生成 {n_candidates} 个【{type_label}】文章标题。\n"
        f"\n参考标题公式：\n{formulas_block}\n"
        f"\n参考真实样例（仅作风格借鉴，不要照抄）：\n{samples_block}\n"
        f"\n硬性要求：\n"
        f"{keyword_rule}"
        f"2. 每个标题字数控制在 {target_chars_min}–{target_chars_max} 字。\n"
        f"3. {n_candidates} 条标题尽量分布到不同公式风格，不要全部用同一种结构。\n"
        f"4. 不要使用 Emoji、英文/智能引号、Markdown 标记。\n"
        f"\n输出格式（只返回 JSON，不要任何其它字符）：\n"
        f'{{"candidates": ["标题1", "标题2", "标题3"]}}'
    )
    return system, user


def _construct_bad_example(keyword: str) -> str:
    """Build a plausible "wrong" example for the keyword-rule contrast.

    For long-tail keywords we splice in a separator at the midpoint so the
    LLM sees concretely what "broken" looks like. For short keywords we
    fall back to a generic warning string.
    """
    if len(keyword) < 4:
        return f"{keyword[:1]}…{keyword[1:]}（中间插入了字符）"
    mid = len(keyword) // 2
    head, tail = keyword[:mid], keyword[mid:]
    return f"{head}选购{tail}（关键词被切开后中间塞了字）"


# ── Response parsing & validation ──────────────────────────────────────


def parse_title_response(raw: str) -> list[str]:
    """Best-effort parse of the LLM's JSON output.

    Tolerates markdown fences (```` ```json ... ``` ````) and extracts the
    first list-of-strings if direct JSON parsing fails. Returns the raw
    candidate strings — caller is responsible for validation.
    """
    text = (raw or "").strip()
    if not text:
        return []

    # Strip ```json / ``` fences if present.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # Try direct JSON parse.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to extracting the first bracketed list anywhere.
        m = re.search(r"\[[^\[\]]*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            data = {"candidates": json.loads(m.group(0))}
        except json.JSONDecodeError:
            return []

    cands = data.get("candidates") if isinstance(data, dict) else data
    if not isinstance(cands, list):
        return []
    return [str(x).strip() for x in cands if isinstance(x, (str, int, float)) and str(x).strip()]


def validate_title(
    t: str,
    keyword: str,
    *,
    min_chars: int = ACCEPT_MIN_CHARS,
    max_chars: int = ACCEPT_MAX_CHARS,
) -> bool:
    """Cheap acceptance check — keyword preserved, length sane, no junk chars."""
    if not t:
        return False
    if keyword and keyword not in t:
        return False
    n = len(t)
    if not (min_chars <= n <= max_chars):
        return False
    if any(ch in t for ch in _BANNED_CHARS):
        return False
    return True


# Patterns that signal the keyword is already a question / decision phrase —
# appending "怎么选？" on top would produce something like "无线吸尘器哪款好用
# 怎么选？" which is awkward Chinese. When we detect any of these we skip the
# question suffix and just append a benefit clause.
_QUESTION_SUFFIXES = (
    "好用", "好不好", "怎么选", "怎么挑", "哪款好", "哪个好", "哪种好",
    "推荐", "买什么", "值不值", "值得买", "选哪个", "选哪款",
)


def fallback_title(keyword: str) -> str:
    """Mechanical fill of last resort when the LLM keeps failing.

    Always preserves the keyword verbatim (this is the primary contract).
    Picks a suffix tail that reads naturally given what's already in the
    keyword — long-tail phrases that already contain a question word
    (好用 / 怎么选 / 推荐 / …) get a benefit-only tail; bare nouns get
    the canonical "怎么选？……" question suffix.
    """
    kw = (keyword or "").strip() or "这件事"

    if any(suffix in kw for suffix in _QUESTION_SUFFIXES):
        # 关键词已经是问句/决策短语 — 接评测/分享类后缀，不再叠加问句。
        candidate = f"{kw}？2026年实测分享给你"
    else:
        candidate = f"{kw}怎么选？看完这篇就不踩坑"

    # Defensive — guarantee the result lands inside the validation window.
    if len(candidate) > ACCEPT_MAX_CHARS:
        # Try a shorter tail before giving up entirely.
        candidate = f"{kw}选购指南"
        if len(candidate) > ACCEPT_MAX_CHARS:
            # Keyword alone is already past the limit — the validator will
            # still accept this if it sneaks in (the keyword is preserved),
            # but realistically this shouldn't happen.
            candidate = kw
    return candidate


# ── Public entry-point ────────────────────────────────────────────────


def generate_titles(
    *,
    keyword: str,
    template_type: str | None,
    vault_root: Path,
    llm_client: LLMClient,
    n_candidates: int = DEFAULT_N_CANDIDATES,
    max_retries: int = 2,
    vault_index: VaultIndex | None = None,
    temperature: float | None = DEFAULT_TEMPERATURE,
) -> list[str]:
    """End-to-end title generation.

    Always returns a non-empty list — falls back to a mechanical title if
    the vault lookup, LLM call, or validation all fail. ``vault_index`` is
    accepted so callers that already cache a scanned vault don't have to
    re-scan; passing ``None`` triggers a fresh scan.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return [fallback_title("文章")]

    if vault_index is None:
        vault_index = scan_vault(Path(vault_root))

    formulas = load_formulas(vault_index, template_type=template_type)
    if not formulas and template_type:
        # Filter knocked everything out — try again without a type filter
        # so the user always gets *some* prompt context. Better a generic
        # title than no title.
        formulas = load_formulas(vault_index, template_type=None)

    system, user = build_title_prompt(
        keyword, template_type, formulas, n_candidates=n_candidates,
    )

    surviving: list[str] = []
    last_rejected: list[str] = []
    for attempt in range(max_retries + 1):
        try:
            raw = llm_client.complete(
                system=system, user=user, temperature=temperature,
            )
        except Exception as exc:
            logger.warning("title LLM call failed: %s — using fallback", exc)
            break
        candidates = parse_title_response(raw)
        if not candidates:
            logger.debug(
                "title attempt %d: parse failed (raw=%r)", attempt + 1, raw[:200]
            )
            continue
        surviving = [t for t in candidates if validate_title(t, keyword)]
        if surviving:
            if len(surviving) < len(candidates):
                # Some passed, some didn't — log the rejected ones so the
                # user can see if the LLM is mangling their keyword.
                rejected = [c for c in candidates if c not in surviving]
                logger.info(
                    "title: dropped %d/%d invalid candidates for keyword %r: %r",
                    len(rejected), len(candidates), keyword, rejected,
                )
            break
        last_rejected = candidates
        logger.info(
            "title attempt %d: all %d candidates failed validation for keyword %r: %r",
            attempt + 1, len(candidates), keyword, candidates,
        )

    if not surviving:
        if last_rejected:
            logger.warning(
                "title: LLM never produced a valid candidate for keyword %r — "
                "falling back to mechanical title. Last rejected batch: %r",
                keyword, last_rejected,
            )
        surviving = [fallback_title(keyword)]
    return surviving
