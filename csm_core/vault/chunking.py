"""AI 拆条长文分块：确定性切分，绝不切断句子（病理无标点长文硬切兜底）。

切点优先级：markdown 标题行 > 空行段界 > 句界（。！？!?\\n）。
贪心装填至 max_chars；缓冲已 ≥60% 满且遇标题段 → 提前断块（章节聚拢）。
超 cap 块截尾（truncated + dropped_chars），调用方负责提示。
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

_HEADING_RE = re.compile(r"^#{1,6} ")
_SENT_END = "。！？!?\n"


class ChunkResult(BaseModel):
    chunks: list[str] = Field(default_factory=list)
    truncated: bool = False
    dropped_chars: int = 0


def _sentences(block: str) -> list[str]:
    out: list[str] = []
    buf = ""
    for ch in block:
        buf += ch
        if ch in _SENT_END:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _units(text: str, max_chars: int) -> list[tuple[str, bool]]:
    """切成 (unit, 是否标题段起点)；每个 unit 保证 ≤ max_chars。"""
    units: list[tuple[str, bool]] = []
    for block in re.split(r"\n{2,}", text):
        if not block.strip():
            continue
        is_heading = bool(_HEADING_RE.match(block.lstrip()))
        chunk_block = block + "\n\n"
        if len(chunk_block) <= max_chars:
            units.append((chunk_block, is_heading))
            continue
        first = True
        for sent in _sentences(chunk_block):
            while len(sent) > max_chars:          # 病理无标点长句：硬切兜底
                units.append((sent[:max_chars], is_heading and first))
                sent = sent[max_chars:]
                first = False
            if sent:
                units.append((sent, is_heading and first))
                first = False
    return units


def split_for_atomize(text: str, *, max_chars: int = 8000, cap: int = 8) -> ChunkResult:
    text = (text or "").strip()
    if not text:
        return ChunkResult()
    # CPU 上界：cap 之外的内容注定进截尾，多留 3 倍余量已绰绰有余；
    # 防病理超长输入把 O(n²) 硬切循环拖成数十秒（sync handler 占线程）。
    hard_limit = max_chars * cap * 3
    pre_dropped = 0
    if len(text) > hard_limit:
        pre_dropped = len(text) - hard_limit
        text = text[:hard_limit]
    if len(text) <= max_chars and pre_dropped == 0:
        return ChunkResult(chunks=[text])

    chunks: list[str] = []
    buf = ""
    for unit, is_heading in _units(text, max_chars):
        over = len(buf) + len(unit) > max_chars
        heading_break = is_heading and len(buf) >= max_chars * 0.6
        if buf and (over or heading_break):
            chunks.append(buf.strip())
            buf = ""
        buf += unit
    if buf.strip():
        chunks.append(buf.strip())

    if len(chunks) > cap:
        dropped = sum(len(c) for c in chunks[cap:]) + pre_dropped
        return ChunkResult(chunks=chunks[:cap], truncated=True, dropped_chars=dropped)
    if pre_dropped:
        return ChunkResult(chunks=chunks, truncated=True, dropped_chars=pre_dropped)
    return ChunkResult(chunks=chunks)
