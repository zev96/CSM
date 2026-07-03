"""AI 味启发式（全确定性正则/词表，零 LLM）。每信号一个 ScorePart（有扣分才产出）。

阈值/权重是启发式（v1 手调）：干净人稿总扣 ≲6，重度 AI 稿各信号普遍命中。
"""
from __future__ import annotations

import re
import statistics

from .model import ScorePart

AI_CONNECTIVES: tuple[str, ...] = (
    "首先", "其次", "再者", "再次", "接着", "总的来说", "综上所述", "总而言之",
    "值得一提的是", "值得注意的是", "不难发现", "不难看出", "众所周知",
    "显而易见", "与此同时", "除此之外", "一方面", "另一方面", "综合来看", "整体而言",
)
_TRIPLET_RE = re.compile(r"首先[\s\S]{0,200}?其次[\s\S]{0,200}?最后")
_PARALLEL_RES = (
    re.compile(r"不是[^。！？\n]{1,30}而是"),
    re.compile(r"不仅[^。！？\n]{1,30}更"),
)
_SUMMARY_STARTS = ("总之", "综上", "总的来说", "综合来看")
_SENT_SPLIT = re.compile(r"[。！？!?\n]+")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]


def ai_flavor_parts(text: str, *, extra_words: list[str] | None = None) -> list[ScorePart]:
    text = (text or "").strip()
    if not text:
        return []
    parts: list[ScorePart] = []
    kchars = max(1.0, len(text) / 1000.0)

    # 1) 套话连接词密度：每千字加权 ×3，上限 15
    vocab = tuple(AI_CONNECTIVES) + tuple(extra_words or [])
    n_conn = sum(text.count(w) for w in vocab)
    if n_conn:
        pts = min(15.0, round(n_conn / kchars * 3.0, 1))
        parts.append(ScorePart(
            key="ai_connectives", label="套话连接词",
            points=pts, detail=f"命中 {n_conn} 处（首先/综上所述 等）"))

    # 2) 三段式：8 分/次，上限 16
    n_tri = len(_TRIPLET_RE.findall(text))
    if n_tri:
        parts.append(ScorePart(
            key="ai_triplet", label="三段式模板",
            points=min(16.0, n_tri * 8.0), detail=f"「首先…其次…最后」×{n_tri}"))

    # 3) 否定排比：2.5 分/处，上限 10
    n_par = sum(len(r.findall(text)) for r in _PARALLEL_RES)
    if n_par:
        parts.append(ScorePart(
            key="ai_parallel", label="否定排比",
            points=min(10.0, round(n_par * 2.5, 1)), detail=f"「不是…而是/不仅…更」×{n_par}"))

    # 4) 万能总结段：4 分/段，上限 12
    n_sum = sum(1 for p in _paragraphs(text) if p.startswith(_SUMMARY_STARTS))
    if n_sum:
        parts.append(ScorePart(
            key="ai_summary", label="万能总结句",
            points=min(12.0, n_sum * 4.0), detail=f"段首「总之/综上」×{n_sum}"))

    # 5) 同质化：句长变异系数过低（≥8 句才判），上限 12
    sents = _sentences(text)
    mono = 0.0
    detail_bits: list[str] = []
    if len(sents) >= 8:
        lens = [len(s) for s in sents]
        cv = statistics.pstdev(lens) / max(1.0, statistics.mean(lens))
        if cv < 0.35:
            mono += min(8.0, round((0.35 - cv) * 40.0, 1))
            detail_bits.append(f"句长 CV={cv:.2f}")
    paras = _paragraphs(text)
    if len(paras) >= 4:
        plens = [len(p) for p in paras]
        pcv = statistics.pstdev(plens) / max(1.0, statistics.mean(plens))
        if pcv < 0.3:
            mono += min(4.0, round((0.3 - pcv) * 40.0, 1))
            detail_bits.append(f"段长 CV={pcv:.2f}")
    if mono:
        parts.append(ScorePart(
            key="monotony", label="句段同质化",
            points=min(12.0, round(mono, 1)), detail="、".join(detail_bits)))

    return parts
