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


def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔包裹的 ```json ... ``` 围栏（逻辑同 xhs_ai_service，本层自带一份）。"""
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _loads_array(raw: str):
    """整体解析失败时，贪婪抠最外层 [...] 再试；都失败 → None。
    （注：贪婪匹配到最后一个 ]，若数组后还跟含括号的文本会落空 →
    上层得 []，属安全失败，不污染库。）"""
    t = _strip_code_fence((raw or "").strip())
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", t, re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def parse_atoms(raw_llm_text: str, folders: list[FolderProfile]) -> list[AtomDraft]:
    """把 LLM 返回解析+校验成 AtomDraft 列表（忠实拆条 spec §4.1/§5）。

    grounding：建议文件夹必须 ∈ 真实菜单，否则置空 + warning（off-menu 进不了库）。
    正文空 → 跳过；置信度非 high/med/low → low；文件名 sanitize（空则取关键词/正文首段）。
    整体非数组 → 返回 []。
    """
    data = _loads_array(raw_llm_text)
    if not isinstance(data, list):
        return []
    allowed = {f.rel_folder for f in folders}
    out: list[AtomDraft] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("正文") or "").strip()
        if not text:
            continue
        warnings: list[str] = []
        rel = (str(item.get("建议文件夹") or "").strip()) or None
        if rel is not None and rel not in allowed:
            warnings.append(f"建议文件夹「{rel}」不在素材库中，请人工选择")
            rel = None
        keyword = str(item.get("核心关键词") or "").strip()
        conf = str(item.get("置信度") or "").strip().lower()
        if conf not in ("high", "med", "low"):
            conf = "low"
        filename = _safe_filename(str(item.get("建议文件名") or ""), keyword or text[:12])
        out.append(AtomDraft(
            text=text, rel_folder=rel,
            material_type=str(item.get("素材类型") or "").strip(),
            product=str(item.get("产品") or "").strip(),
            keyword=keyword, filename=filename, confidence=conf, warnings=warnings))
    return out
