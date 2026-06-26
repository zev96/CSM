"""Part 1 Unit A: 本地 token 估算 + 单价表 + 算钱。"""
from __future__ import annotations

from csm_core.llm import pricing


def test_estimate_tokens_cjk_and_latin():
    assert pricing.estimate_tokens("") == 0
    # 纯中文 9 字 → ceil(9*0.6)=6（CJK 标点不计入正文字时按实现）
    t = pricing.estimate_tokens("无线吸尘器评测十款")
    assert 5 <= t <= 7
    assert pricing.estimate_tokens("hello world") >= 2
    assert pricing.estimate_tokens("吸力220AW 实测") > 0


def test_price_for_default_override_unknown():
    p = pricing.price_for("deepseek-chat")
    assert p is not None and p.input > 0 and p.output > 0
    ov = {"deepseek-chat": {"input": 9.9, "output": 8.8}}
    p2 = pricing.price_for("deepseek-chat", ov)
    assert p2.input == 9.9 and p2.output == 8.8
    assert pricing.price_for("no-such-model") is None
    assert pricing.price_for(None) is None


def test_chain_cost_with_and_without_price():
    passes = [
        {"input_tokens": 1000, "output_tokens": 500},
        {"input_tokens": 200, "output_tokens": 800},
    ]
    c = pricing.chain_cost(passes, "deepseek-chat")
    assert c["input_tokens"] == 1200 and c["output_tokens"] == 1300
    assert c["cost"] is not None and c["currency"] == "CNY"
    c2 = pricing.chain_cost(passes, "no-such-model")
    assert c2["cost"] is None and c2["input_tokens"] == 1200


def test_chainpass_to_dict_has_tokens():
    from csm_sidecar.services.chain_service import ChainPass
    d = ChainPass(index=0, skill_id="p", role="persona", skill_name="人设",
                  input="无线吸尘器", output="成稿正文内容").to_dict()
    assert d["input_tokens"] > 0 and d["output_tokens"] > 0
    assert d["input_chars"] == 5  # 旧字段保留（零回归）
