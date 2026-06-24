"""Compare a finished article against a fact whitelist (number/cert sets).

只看**带单位**的数字和**已知**认证名（见 extract）。membership 用精确集合
查找 —— 白名单已把区间/万展开为独立 float（见 brand_memory.whitelist），
本域数值都是良态 float，无需 math.isclose。句子上下文随违规一起返回，供
Plan 5 审查面板定位。
"""
from __future__ import annotations
from .extract import extract_certs, extract_number_mentions, split_sentences
from .model import FactCheckReport, Violation


def check_facts(
    text: str, *, allowed_numbers: set[float], allowed_certs: set[str],
) -> FactCheckReport:
    violations: list[Violation] = []
    for sentence in split_sentences(text):
        for value, raw in extract_number_mentions(sentence):
            if value not in allowed_numbers:
                violations.append(Violation(
                    kind="number", value=raw, number=value, sentence=sentence,
                    suggestion="改用注入参数表里的数值，或标为通用表述/本次放行",
                ))
        for cert in extract_certs(sentence):
            if cert not in allowed_certs:
                violations.append(Violation(
                    kind="cert", value=cert, sentence=sentence,
                    suggestion="删除或替换为该型号实际通过的认证，或本次放行",
                ))
    return FactCheckReport(ok=not violations, violations=violations)
