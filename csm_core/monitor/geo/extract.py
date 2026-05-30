"""把一条 GeoAnswer 抽成结构化 GeoExtraction（LLM 一次调用）。

信源不靠 LLM：直接对 answer.citations 跑 classify（确定性、省 token）。
LLM 只产出 mentioned/rank/recommended/sentiment/summary。坏 JSON 重试
一次（更严格的 system），仍失败则降级（mentioned 启发式 + rank=-1）。
"""
from __future__ import annotations
import json
import logging
import re

from csm_core.llm.client import LLMClient, make_client
from csm_core.config import read_api_key
from .models import GeoAnswer, GeoExtraction, RecommendedEntity
from .classify import classify_citations

logger = logging.getLogger(__name__)

_SYSTEM = (
    "你是品牌监测分析助手。给定一个用户问题和某 AI 的回答，判断目标品牌在回答中的情况。"
    "只输出 JSON，不要解释。字段："
    '{"mentioned":bool,"target_rank":int,"sentiment":"pos|neu|neg|na",'
    '"recommended":[{"name":str,"position":int}],"summary":str}。'
    "target_rank 是目标品牌在回答推荐序列中的 1-based 位置，未提及或未进序列填 -1。"
    "recommended 按回答里出现/推荐的顺序列出所有品牌。"
)
_SYSTEM_STRICT = _SYSTEM + " 上一次输出不是合法 JSON，请严格只输出一个 JSON 对象。"


def build_extract_client(provider: str) -> LLMClient:
    """按 provider 名建 LLM client（key 走 keyring/config）。"""
    if provider == "mock":
        return make_client(provider="mock")
    key = read_api_key(provider)
    if not key:
        raise ValueError(f"抽取 provider '{provider}' 未配置 API key")
    return make_client(provider=provider, api_key=key)


def _norm(s: str) -> str:
    return (s or "").lower().replace(" ", "").strip()


def _is_target(name: str, brand: str, aliases: list[str]) -> bool:
    n = _norm(name)
    pool = {_norm(brand), *(_norm(a) for a in aliases)}
    return any(p and (p in n or n in p) for p in pool)


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    # 容忍 ```json ... ``` 包裹
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def extract(answer: GeoAnswer, *, brand: str, aliases: list[str], client: LLMClient) -> GeoExtraction:
    citations = classify_citations(answer.citations)

    # 空答案不调 LLM
    if not answer.answer_text.strip():
        return GeoExtraction(mentioned=False, target_rank=-1, sentiment="na",
                             recommended=[], citations=citations, summary="")

    user = f"用户问题：{answer.keyword}\n\nAI 回答：\n{answer.answer_text}\n\n目标品牌：{brand}"
    obj = None
    for sys_prompt in (_SYSTEM, _SYSTEM_STRICT):
        try:
            raw = client.complete(system=sys_prompt, user=user, temperature=0.0)
        except Exception as e:
            # 网络/超时类失败：换严格 prompt 重试也无济于事，直接跳出走启发式降级。
            logger.warning("[geo.extract] LLM 调用失败 kw=%s: %s", answer.keyword, e)
            break
        obj = _parse_json(raw)
        if obj is not None:
            break

    if obj is None:
        # 降级：品牌名/别名在文本里出现就算 mentioned
        mentioned = _is_target(answer.answer_text, brand, aliases)
        return GeoExtraction(mentioned=mentioned, target_rank=-1, sentiment="na",
                             recommended=[], citations=citations,
                             summary="[抽取失败，已降级为启发式]")

    recommended = []
    for item in obj.get("recommended") or []:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        recommended.append(RecommendedEntity(
            name=name, position=int(item.get("position", 0) or 0),
            is_target=_is_target(name, brand, aliases)))

    senti = obj.get("sentiment", "na")
    if senti not in ("pos", "neu", "neg", "na"):
        senti = "na"
    return GeoExtraction(
        mentioned=bool(obj.get("mentioned", False)),
        target_rank=int(obj.get("target_rank", -1) or -1),
        sentiment=senti,
        recommended=recommended,
        citations=citations,
        summary=str(obj.get("summary", "")),
    )
