"""AI 拆条服务（spec 3b §4.2）。

scan 真实库 → build_menu（grounding）→ llm_factory.complete → parse_atoms。
LLM client 复用 llm_factory（与润色/mining/xhs 同一套设置）；未配 provider 时
LLMConfigError 透传给路由层包成 503。vault_root 解析复用 3a 的
vault_writer_service._root()（同 services 包，同一份存在性校验，避免重复）。
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from csm_core.vault import folder_profile
from csm_core.vault.atomizer import build_menu, parse_atoms

from . import config_service, llm_factory, vault_service, vault_writer_service

logger = logging.getLogger(__name__)

_MAX_INPUT = 8000   # v1 不分块：超长截断 + 记一条 warning 日志（前端级提示/分块留后续）

ATOMIZE_SYSTEM = (
    "你是家电营销资料的素材拆条助手。把用户给的原文【忠实拆分】成多条可复用的"
    "原子素材，每条只讲一个要点。严格要求：\n"
    "1) 忠实：尽量保留原文措辞，不改写、不扩写、不编造，不要把不同要点合并；一个要点一条。\n"
    "2) 归类：从【可选归类菜单】里给每条选一个最合适的「建议文件夹」和「素材类型」；"
    "菜单里没有合适的就把这两项留空字符串（交给人工定）。\n"
    "3) 产品：从 希喂 / 戴森 / 小米 / 追觅 / 通用 中选（希喂是自家品牌）。\n"
    "4) 置信度：给每条一个「置信度」= high / med / low，只评你对【归类】的把握，不评正文。\n"
    "5) 文件名：给一个简短的「建议文件名」（中文可，不含空格和斜杠，可不带 .md）。\n"
    "只返回一个 JSON 数组，每个元素形如 "
    '{"正文": "...", "建议文件夹": "...", "素材类型": "...", "产品": "...", '
    '"核心关键词": "...", "建议文件名": "...", "置信度": "high"}，'
    "不要输出 JSON 数组以外的任何文字、解释或 markdown 代码块标记。"
)


def atomize(text: str) -> list[dict]:
    """把 text 拆成原子素材列表（每个元素 = asdict(AtomDraft)）。

    Raises
    ------
    ValueError
        vault_root 未配置/不存在（路由层 → 400）。
    llm_factory.LLMConfigError
        未配 default provider / api key（路由层 → 503）。
    OSError
        共享盘断开/占用（scan 阶段，路由层 → 503）。
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) > _MAX_INPUT:
        logger.warning("[atomize] 输入超长，截断 %d→%d 字（v1 不分块）", len(text), _MAX_INPUT)
        text = text[:_MAX_INPUT]
    root = vault_writer_service._root()          # 复用 3a 的 vault_root 解析
    index = vault_service.scan(root)
    folders = folder_profile.list_writable_folders(index)
    menu = build_menu(folders)
    client = llm_factory.build_client()
    raw = client.complete(
        system=ATOMIZE_SYSTEM,
        user=f"【可选归类菜单】\n{menu}\n\n【待拆分原文】\n{text}",
        temperature=0.2)
    return [asdict(a) for a in parse_atoms(raw, folders)]
