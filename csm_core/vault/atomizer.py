"""把一篇资料拆成原子素材的纯函数层（无 LLM、无磁盘）。

LLM 调用在 sidecar 的 atomize_service；本模块只负责：把真实库文件夹拼成
喂 LLM 的菜单（build_menu）、把 LLM 返回的 JSON 数组解析+校验成 AtomDraft
（parse_atoms）。grounding：建议文件夹必须在真实菜单里，否则置空+warning
——off-menu 进不了库。忠实拆条（spec D1）：正文 = 原文，写成单变体①。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .folder_profile import FolderProfile


@dataclass(frozen=True)
class AtomDraft:
    text: str                       # 正文（单变体①，忠实原文）
    rel_folder: str | None          # 已对真实菜单校验；off-menu → None
    material_type: str              # 素材类型（预填提示，人工可改）
    product: str                    # 产品：希喂/戴森/小米/追觅/通用
    keyword: str                    # 核心关键词
    filename: str                   # 已 sanitize，.md 结尾
    confidence: str                 # high|med|low（非法 → low）
    warnings: list[str] = field(default_factory=list)


def build_menu(folders: list[FolderProfile]) -> str:
    """把可写文件夹拼成喂 LLM 的菜单串。只取内容型（body_shape != spec_table）
    ——产品参数表归 3a 手动录入，prose 拆条不该落进参数表。"""
    lines = []
    for f in folders:
        if f.body_shape == "spec_table":
            continue
        types = "/".join(f.material_types) if f.material_types else "（无固定类型）"
        lines.append(f"- {f.rel_folder} ｜ 素材类型: {types}")
    return "\n".join(lines)


def _safe_filename(raw: str, fallback: str) -> str:
    """空格/路径分隔符 → 连字符；空 → fallback（取关键词或正文首段）；保证 .md 结尾。
    中文允许（库里就是中文笔记名）。"""
    s = (raw or "").strip()
    if not s:
        s = (fallback or "").strip() or "素材"
    s = re.sub(r"[\s/\\]+", "-", s).strip("-") or "素材"
    if not s.endswith(".md"):
        s = s + ".md"
    return s
