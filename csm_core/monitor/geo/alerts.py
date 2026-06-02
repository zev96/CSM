"""GEO 告警纯函数。比较本次运行 metric 与上次，返回触发的告警列表。

三类（spec §9）：
- hidden：本次曝光度 SoC < 阈值（默认 0.2）。
- first_drop：首推率较上次显著下降（默认跌幅 ≥ 0.1）。
- platform_dropped：某平台从「提及(>0)」变「未提及(0)」。

整轮无有效样本（ok_total<=0）视为采集失败、不产告警；平台「掉出」也要求该平台
本轮 ok_total>0（与 metrics._block「error 是『没问到』不是『没提及』」口径一致，
避免 API 故障/软封误报隐身/掉出）。无 I/O、可单测。适配器在 fetch() 末尾调它，把结果塞进 metric["alerts"]；
notify.should_alert 的 geo 分支只看 metric["alerts"] 是否非空 + cooldown。
"""
from __future__ import annotations
from typing import Any


def evaluate_geo_alerts(
    result_metric: dict[str, Any],
    prev_metric: dict[str, Any] | None,
    *,
    hidden_threshold: float = 0.2,
    first_drop_threshold: float = 0.1,
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []
    # 整轮无有效样本（ok_total<=0）= 采集失败不是卡位信号，不产 GEO 告警。
    if (result_metric.get("ok_total") or 0) <= 0:
        return alerts
    soc = result_metric.get("soc")
    if isinstance(soc, (int, float)) and soc < hidden_threshold:
        alerts.append({"kind": "hidden", "detail": f"曝光度 {round(soc * 100)}% 低于 {round(hidden_threshold * 100)}%（隐身）"})
    if prev_metric:
        prev_first = prev_metric.get("first_rank_rate") or 0
        cur_first = result_metric.get("first_rank_rate") or 0
        if (prev_first - cur_first) >= first_drop_threshold:
            alerts.append({"kind": "first_drop", "detail": f"首推率 {round(prev_first * 100)}% → {round(cur_first * 100)}%"})
        prev_bp = prev_metric.get("by_platform") or {}
        cur_bp = result_metric.get("by_platform") or {}
        for plat, pb in prev_bp.items():
            cb = cur_bp.get(plat)
            # 该平台本轮真的问到了(ok_total>0)且品牌从提及变未提及才算「掉出」。
            if ((pb or {}).get("mentioned", 0) > 0 and cb is not None
                    and (cb or {}).get("ok_total", 0) > 0
                    and (cb or {}).get("mentioned", 0) == 0):
                alerts.append({"kind": "platform_dropped", "detail": f"{plat} 从提及变未提及"})
    return alerts
