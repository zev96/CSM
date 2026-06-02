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
    # SoC / 首推率分母用「有效（ok）cell 数」，不是 len(cells)：采集失败
    # （error/blocked）是「没问到」不是「问了没提及」，不该把曝光/首推率拉低。
    # ok_total==0 时全部归 0（无有效样本）。sentiment_score 仍按提及 cell 取均值。
    total = len(cells)
    ok_total = sum(1 for c in cells if c.status == "ok")
    error_cells = total - ok_total
    mentioned = sum(1 for c in cells if c.mentioned)   # errored cell 的 mentioned 本就是 False
    first = sum(1 for c in cells if c.mentioned and c.rank == 1)
    senti_vals = [_SENTI[c.sentiment] for c in cells if c.mentioned and c.sentiment in _SENTI]
    soc = (mentioned / ok_total) if ok_total else 0.0
    return {
        "total": total,
        "ok_total": ok_total,
        "error_cells": error_cells,
        "mentioned": mentioned,
        "soc": soc,
        "status_band": band(soc),
        "first_rank_rate": (first / ok_total) if ok_total else 0.0,
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
    # Rank distribution — buckets are NOT a partition; top3/top5 are cumulative
    # (top3 ⊆ top5 ⊆ mentioned), and mentioned_unranked = mentioned cells with rank<=0.
    # A mentioned cell at rank 6 appears in soc/mentioned but not in any top-N bucket.
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
