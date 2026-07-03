"""完整性反向核对：激进契约删减后，主推型号关键事实必须仍在成稿。

方向与 checker 相反 —— checker 抓「成稿多了白名单外的数」，本模块抓
「初稿有、且属于主推型号 spec/认证 的事实，在成稿里消失」。竞品内容
被删不算缺失（激进契约允许取舍竞品）。万-展开与 extract 对称。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .extract import extract_certs, extract_number_mentions, split_sentences


class MissingFact(BaseModel):
    kind: Literal["number", "cert"]
    token: str               # 初稿原文 token，如 "250AW" / "CCC"
    value: float | None      # 归一值（万展开），cert=None
    sentence: str            # 初稿所在句（定位）


class CompletenessReport(BaseModel):
    checked: bool            # False = 无主推 scope，未核
    missing: list[MissingFact] = Field(default_factory=list)


def _sentence_of(draft: str, token: str) -> str:
    for s in split_sentences(draft):
        if token in s:
            return s
    return ""


def check_completeness(draft: str, final_text: str, scopes: list) -> CompletenessReport:
    primary = [s for s in scopes if getattr(s, "role", "") == "主推"]
    if not primary:
        return CompletenessReport(checked=False)

    spec_numbers: set[float] = set()
    cert_vocab: set[str] = set()
    for scope in primary:
        for sv in scope.memory.specs.values():
            spec_numbers.update(sv.numbers)
        cert_vocab.update(scope.memory.certs)

    final_numbers = {v for v, _tok in extract_number_mentions(final_text)}
    final_certs = set(extract_certs(final_text))

    missing: list[MissingFact] = []
    seen_values: set[float] = set()
    for value, token in extract_number_mentions(draft):
        if value not in spec_numbers or value in seen_values:
            continue
        seen_values.add(value)
        if value not in final_numbers:
            missing.append(MissingFact(
                kind="number", token=token, value=value,
                sentence=_sentence_of(draft, token)))
    for cert in extract_certs(draft):
        if cert in cert_vocab and cert not in final_certs:
            missing.append(MissingFact(
                kind="cert", token=cert, value=None,
                sentence=_sentence_of(draft, cert)))
    return CompletenessReport(checked=True, missing=missing)
