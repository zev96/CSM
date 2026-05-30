# csm_core/monitor/geo/metrics.py
"""四大 KPI 聚合（纯函数，零 I/O）。

输入一次运行的全部 GeoCell，输出仪表盘用的 KPI 汇总块。口径见 spec §7：
- 曝光度 SoC = 提及/总；band: <0.2 hidden / <0.5 weak / else strong
- 首推率 = rank==1 / 总（绝对）；另出 /提及（条件）
- 情感得分 = pos+1/neu0/neg-1 对提及取均值
- 顶层代表顺位 = 提及 cell 顺位中位数（-1 if none）
"""
from __future__ import annotations
from statistics import median
from typing import Any

from .models import GeoCell

_SENTI = {"pos": 1.0, "neu": 0.0, "neg": -1.0}


def band(soc: float) -> str:
    if soc < 0.2:
        return "hidden"
    if soc < 0.5:
        return "weak"
    return "strong"


def _block(cells: list[GeoCell]) -> dict[str, Any]:
    total = len(cells)
    mentioned = sum(1 for c in cells if c.mentioned)
    first = sum(1 for c in cells if c.mentioned and c.rank == 1)
    senti_vals = [_SENTI.get(c.sentiment, 0.0) for c in cells if c.mentioned]
    soc = (mentioned / total) if total else 0.0
    return {
        "total": total,
        "mentioned": mentioned,
        "soc": soc,
        "status_band": band(soc),
        "first_rank_rate": (first / total) if total else 0.0,
        "first_rank_rate_mentioned": (first / mentioned) if mentioned else 0.0,
        "sentiment_score": (sum(senti_vals) / len(senti_vals)) if senti_vals else 0.0,
    }


def aggregate(cells: list[GeoCell]) -> dict[str, Any]:
    agg = _block(cells)
    # Sentiment distribution
    dist = {"pos": 0, "neu": 0, "neg": 0}
    for c in cells:
        if c.mentioned and c.sentiment in dist:
            dist[c.sentiment] += 1
    agg["sentiment_dist"] = dist
    # Rank distribution
    agg["rank_dist"] = {
        "first": sum(1 for c in cells if c.mentioned and c.rank == 1),
        "top3": sum(1 for c in cells if c.mentioned and 1 <= c.rank <= 3),
        "top5": sum(1 for c in cells if c.mentioned and 1 <= c.rank <= 5),
        "mentioned_unranked": sum(1 for c in cells if c.mentioned and c.rank <= 0),
        "absent": sum(1 for c in cells if not c.mentioned),
    }
    # Dimension breakdown
    by_plat: dict[str, list[GeoCell]] = {}
    by_kw: dict[str, list[GeoCell]] = {}
    for c in cells:
        by_plat.setdefault(c.platform, []).append(c)
        by_kw.setdefault(c.keyword, []).append(c)
    agg["by_platform"] = {k: _block(v) for k, v in by_plat.items()}
    agg["by_keyword"] = {k: _block(v) for k, v in by_kw.items()}
    return agg


def representative_rank(cells: list[GeoCell]) -> int:
    ranks = [c.rank for c in cells if c.mentioned and c.rank > 0]
    return int(median(ranks)) if ranks else -1
