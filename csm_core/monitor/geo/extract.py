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
    # ⚠ 必须是「品牌」粒度：LLM 默认会回产品全名（戴森V8 Cyclone / 希亦 V800 / 小米无线吸尘器2 Lite），
    # 同一品牌在不同平台写法还不一致，导致竞品榜按字符串分组时同一品牌裂成多行（重复竞品）。
    "⚠ recommended 的 name 只写**品牌名**，去掉型号/系列/品类词："
    "「戴森V8 Cyclone」→「戴森」，「希亦 V800」→「希亦」，「小米无线吸尘器2 Lite」→「小米」，"
    "「CEWEY（希喂）DS18」→「希喂」。"
    "同一品牌只出现一次；按回答推荐的先后顺序，position 从 1 起连续编号；"
    "target_rank 与目标品牌在该去重列表里的 position 一致。"
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


def _brand_in_text(text: str, brand: str, aliases: list[str]) -> bool:
    """品牌名或任一别名是否作为子串出现在回答正文里（归一化：小写、去空格）。"""
    hay = _norm(text)
    if not hay:
        return False
    pool = [_norm(brand), *(_norm(a) for a in aliases)]
    return any(p and p in hay for p in pool)


def _reco_key(name: str) -> str:
    """竞品/品牌名归一化键（与前端 geoDetail.competitorKey 同口径）：小写 + 去所有空白。"""
    return re.sub(r"\s+", "", (name or "").lower())


def _dedupe_recommended(items: list[RecommendedEntity]) -> list[RecommendedEntity]:
    """按归一化名合并 recommended，并按位次重排、连续重编号。

    prompt 已要求 LLM「只写品牌名 + 同一品牌只出现一次 + position 连续编号」，但那是**软
    约束**（弱抽取模型经常半合规）。这里做一层**确定性**兜底，让下游（竞品榜/热力矩阵/
    target_rank）不依赖 LLM 是否听话：
    - 同一归一化名的多条合并成一条，保留**最靠前**（position 最小且 >0）的那条；
      任一条是 target，合并结果就是 target。
    - 有位次的按位次升序连续重编号 1..N；LLM 没给位次（<=0）的保持 0（未上榜），排在后面。
    注：只合并「同名/仅空格大小写不同」，**不做**品牌 vs 型号的模糊前缀合并（那会误并不同
    品牌），型号→品牌的收敛交给 prompt。
    """
    best: dict[str, RecommendedEntity] = {}
    for r in items:
        k = _reco_key(r.name)
        if not k:
            continue
        cur = best.get(k)
        if cur is None:
            best[k] = r
            continue
        cur_pos = cur.position if cur.position > 0 else 10**9
        new_pos = r.position if r.position > 0 else 10**9
        keep = r if new_pos < cur_pos else cur
        best[k] = keep.model_copy(update={"is_target": cur.is_target or r.is_target})
    ranked = sorted((r for r in best.values() if r.position > 0), key=lambda r: r.position)
    out = [r.model_copy(update={"position": i + 1}) for i, r in enumerate(ranked)]
    out.extend(r for r in best.values() if r.position <= 0)
    return out


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

    # 把别名一并喂给 LLM —— 否则它只认中文主名，回答里「只以别名出现」的目标（如
    # 品牌希喂的英文别名 CEWEY）会被判未提及、还会被当成竞品列进 recommended。
    brand_desc = brand
    if aliases:
        brand_desc = f"{brand}（别名：{'、'.join(aliases)}；回答里出现主名或任一别名，都算提及并卡位到该品牌）"
    user = f"用户问题：{answer.keyword}\n\nAI 回答：\n{answer.answer_text}\n\n目标品牌：{brand_desc}"
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
        # 降级：品牌名/别名在文本里出现就算 mentioned（与主路径同一「品牌是否在正文」判据）
        mentioned = _brand_in_text(answer.answer_text, brand, aliases)
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
    # 确定性兜底：同一品牌合并成一条 + 位次连续重编号（不依赖 LLM 是否遵守 prompt）。
    recommended = _dedupe_recommended(recommended)

    mentioned = bool(obj.get("mentioned", False))
    target_rank = int(obj.get("target_rank", -1) or -1)
    senti = obj.get("sentiment", "na")
    if senti not in ("pos", "neu", "neg", "na"):
        senti = "na"
    # 一致性校正：LLM 的 mentioned/target_rank 是自由字段，且 LLM 只知道中文主名、**不知道
    # 别名**，会两头出错——既可能把没提到的品牌判成提及（幻觉），也可能把「只以别名出现」
    # 的目标漏判成未提及。用「正文是否出现品牌/别名」+「LLM 是否把某条推荐判成目标」双证据校正：
    in_text = _brand_in_text(answer.answer_text, brand, aliases)
    target_reco = next((r for r in recommended if r.is_target), None)
    if in_text and target_reco is not None:
        # ① 上调——双证据一致：品牌/别名字面出现在正文，且 LLM 把某条推荐认成了目标
        #    （is_target）。挡住 LLM 的别名盲区漏判（实测：品牌希喂/别名 CEWEY，回答写
        #    「CEWEY DS18」被 LLM 判未提及、还被当竞品）。要求「进了 recommended」而非只看
        #    正文子串，避免品牌名恰是常用词（完美/自然）混在描述里被哑子串误判成提及。
        mentioned = True
    elif mentioned and not in_text and target_reco is None:
        # ② 撤销幻觉——正文没有品牌/别名、recommended 也没有目标条目，LLM 却说提及。
        mentioned = False
    # 顺位以**去重重编号后**的 recommended 里目标条目的 position 为准 —— 它与竞品行/热力矩阵
    # 读的是同一份列表，口径必须一致；LLM 的 target_rank 是自由字段（去重后常忘了同步，会出现
    # 「你 #3」与某个竞品同列也是 #3」的自相矛盾），只在没有目标条目时才回退用它。
    if mentioned and target_reco is not None and target_reco.position > 0:
        target_rank = target_reco.position
    # 未提及 → 顺位与情感都无意义，一并归零（与投票路径 sampling.vote_cell 同一不变量：
    # mentioned=False ⇒ rank=-1、senti=na；否则明细卡会「未提及」却又显示「口碑正面」）。
    if not mentioned:
        target_rank = -1
        senti = "na"
    return GeoExtraction(
        mentioned=mentioned,
        target_rank=target_rank,
        sentiment=senti,
        recommended=recommended,
        citations=citations,
        summary=str(obj.get("summary", "")),
    )
