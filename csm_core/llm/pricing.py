"""本地 token 估算 + 内置单价表 + 链成本（无依赖、离线稳）。

token 是**估算值**（CJK 启发式，非真实分词），UI 须以「≈」呈现。单价表
默认近似、可在设置（AppConfig.pricing）覆盖；未知 model → 无价（只显 token）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

# CJK 统一表意 + 扩展A + 兼容 + CJK标点 + 全角（够覆盖中文正文；只求稳定估算）。
_CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿　-〿＀-￯]")


def estimate_tokens(text: str) -> int:
    """CJK 感知 token 估算：中文 ~0.6 token/字、其余 ~0.25 token/字符。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return math.ceil(cjk * 0.6 + other * 0.25)


@dataclass(frozen=True)
class ModelPrice:
    input: float   # ¥ / 1M tokens
    output: float  # ¥ / 1M tokens


# 内置默认单价（¥/1M tokens，**近似种子值**，随官方调价会过时 → 设置可覆盖）。
# key = model 名（与 AppConfig.default_model 的 value 对齐）。缺项 → price_for 返回 None。
DEFAULT_PRICES: dict[str, ModelPrice] = {
    "deepseek-chat": ModelPrice(input=1.0, output=2.0),
    "deepseek-reasoner": ModelPrice(input=1.0, output=4.0),
    "qwen-plus": ModelPrice(input=0.8, output=2.0),
    "qwen-max": ModelPrice(input=2.4, output=9.6),
    "qwen-turbo": ModelPrice(input=0.3, output=0.6),
}


def price_for(model: str | None, overrides: dict[str, dict] | None = None) -> ModelPrice | None:
    """默认←设置覆盖。未知 model / None → None（调用方据此只显 token）。"""
    if not model:
        return None
    ov = (overrides or {}).get(model)
    if ov and "input" in ov and "output" in ov:
        return ModelPrice(input=float(ov["input"]), output=float(ov["output"]))
    return DEFAULT_PRICES.get(model)


def chain_cost(
    pass_dicts: list[dict[str, Any]], model: str | None,
    overrides: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """从 ChainPass.to_dict() 列表算成本摘要（用其 input_tokens/output_tokens 字段）。
    无价 → cost=None（token 仍汇总）。"""
    it = sum(int(p.get("input_tokens", 0)) for p in pass_dicts)
    ot = sum(int(p.get("output_tokens", 0)) for p in pass_dicts)
    price = price_for(model, overrides)
    cost = None if price is None else round(
        it / 1_000_000 * price.input + ot / 1_000_000 * price.output, 4)
    return {"input_tokens": it, "output_tokens": ot, "cost": cost, "currency": "CNY"}
