"""GEO 多次采样投票(§4.6)—— 每 (关键词,平台) 采 K 次,投票产出一个 GeoCell。

在 **cell 级**投票 → runner「每关键词一 cell」契约天然保持。默认 K=1 = 单样本
原样返回,逐字节等价单采样(零成本向后兼容)。

投票**只用于判定**(mention/rank/sentiment);信源/答案/recommended/summary
取**首个成功样本**(§4.6 致命修复④:并集会把 geo_citations 行数×K 放大,污染
信源榜权重 storage.weight=count×平台×权威 与卡片「引用 N」)。
"""
from __future__ import annotations
from collections import Counter
from statistics import median
from typing import Any, Callable

from ..base import maybe_cancel
from .models import GeoCell


def majority_sentiment(sentiments: list[str]) -> str:
    """情感多数票;空、或并列最高(平局)→ na。"""
    votes = [s for s in sentiments if s in ("pos", "neu", "neg")]
    if not votes:
        return "na"
    counts = Counter(votes).most_common()
    top = counts[0][1]
    winners = [s for s, n in counts if n == top]
    return winners[0] if len(winners) == 1 else "na"


def samples_digest(samples: list[GeoCell]) -> list[dict[str, Any]]:
    """每样本的投票相关字段摘要(进 raw["samples"],供追溯/调试,不含大文本)。"""
    return [{"status": s.status, "mentioned": s.mentioned, "rank": s.rank,
             "sentiment": s.sentiment, "fail_reason": s.fail_reason} for s in samples]


def vote_cell(samples: list[GeoCell], prev_mentioned: "bool | None" = None) -> GeoCell:
    """K 个样本 GeoCell → 一个投票 GeoCell(纯函数)。

    - ``len==1``:原样返回(K=1 零成本向后兼容,不动 rank/raw/任何字段)。
    - 只对 ``status=='ok'`` 样本投票;全失败 → 返回首个失败样本(附 samples 摘要)。
    - **mention**:ok 样本多数;平局 → ``prev_mentioned``(缺省 False)。
    - **rank**:命中(mentioned 且 rank>0)样本的 rank 中位 ``int()``;无命中 → -1。
    - **sentiment**:ok 且 mentioned 样本的多数;平局/空 → na。
    - **信源/答案/recommended/summary**:首个 ok 样本(绝不并集)。
    - voted mentioned=False → 强制 rank=-1、senti=na(一致性;仅 ≥2 样本新路径)。
    """
    if not samples:
        raise ValueError("vote_cell: 至少需要一个样本")
    if len(samples) == 1:
        return samples[0]

    ok = [s for s in samples if s.status == "ok"]
    if not ok:
        # 全失败:保留首个失败样本(status/fail_reason 原样),附样本摘要供追溯。
        base = samples[0]
        return base.model_copy(update={"raw": {**base.raw, "samples": samples_digest(samples)}})

    yes = sum(1 for s in ok if s.mentioned)
    no = len(ok) - yes
    if yes > no:
        mentioned = True
    elif no > yes:
        mentioned = False
    else:                                        # 平局(常见于翻转补采后的 1-1)
        mentioned = bool(prev_mentioned) if prev_mentioned is not None else False

    first_ok = ok[0]
    raw = {**first_ok.raw, "samples": samples_digest(samples)}
    if mentioned:
        hit = sorted(s.rank for s in ok if s.mentioned and s.rank > 0)
        rank = int(median(hit)) if hit else -1
        senti = majority_sentiment([s.sentiment for s in ok if s.mentioned])
    else:
        rank, senti = -1, "na"

    return GeoCell(
        platform=first_ok.platform, keyword=first_ok.keyword,
        mentioned=mentioned, rank=rank, sentiment=senti,
        answer_text=first_ok.answer_text, status="ok", fail_reason="",
        raw=raw, citations=first_ok.citations,
        recommended=first_ok.recommended, summary=first_ok.summary)


def sampled_cell(sample_fn: "Callable[[], GeoCell]", *, k: int = 1,
                 flip_recheck: bool = True, prev_mentioned: "bool | None" = None,
                 cancel_token=None) -> GeoCell:
    """跑 K 次 ``sample_fn`` 投票产出一个 cell;翻转复核时补采 1 次确认。

    - 每次 ``sample_fn`` 前 ``maybe_cancel``(用户 Stop 不必等满 K 次;取消由
      ``sample_fn`` 或此处 ``maybe_cancel`` 上抛,不吞)。
    - **翻转复核**:``voted.status=='ok'`` 且 ``voted.mentioned != prev``(prev 已知)
      → 补采 1 次再投票。翻转复核 = 确认:补采后若 1-1 平局回落 prev(翻转未确认
      则维持上轮结论,抑制单次采样误翻转)。
    """
    k = max(1, k)
    samples: list[GeoCell] = []
    for _ in range(k):
        maybe_cancel(cancel_token)
        samples.append(sample_fn())
    voted = vote_cell(samples, prev_mentioned)
    if (flip_recheck and prev_mentioned is not None
            and voted.status == "ok" and voted.mentioned != prev_mentioned):
        maybe_cancel(cancel_token)
        samples.append(sample_fn())
        voted = vote_cell(samples, prev_mentioned)
    return voted
