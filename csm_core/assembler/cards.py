"""竞品卡 H2 小节解析，供模板库 card_coverage / card_sections 使用。

素材形态::

    ---
    品牌: 欧瑞达
    型号: 欧瑞达X9
    素材类型: 竞品卡
    层级标签: 热门品牌
    ---
    ## 市场口碑数据
    ① 全平台销量稳步增长……
    ② 连续两年入围双11热销榜……

    ## 品牌赛道定位
    ① 主打长效滤网的家用品牌……

一张卡 = 一个竞品；H2 = 一个「点」；节内 ①②③ = 该点的多份候选内容。

原先这里还有竞品名册构建与逐小节采样（``build_roster`` / ``sample_roster``
等），随创作区的组装器一起下线；现在只剩模板库编辑器（routes/vault.py 的
``card_coverage`` / ``card_sections``）用到的两个纯解析函数。
"""
from __future__ import annotations

from csm_core.test_framework.section_parser import extract_brand_sections
from csm_core.vault.note_parser import ParsedNote


_SECTIONS_ATTR = "_card_sections_cache"


def note_sections(note: ParsedNote) -> list:
    """卡片笔记的 H2 小节。在 raw_body 上做 —— 变体切分会吃掉 H2 行。

    结果缓存在 **ParsedNote 实例上**：覆盖度检查要对每张卡 × 每个小节各查
    一次，10 竞品 × 7 小节就是 70 次全文解析，纯浪费。

    挂在实例上而不是模块级字典，是为了让缓存跟着索引一起失效 —— 笔记变了
    索引会重新解析出**新的** ParsedNote 对象，自然没有这个属性。早期版本用
    ``(路径, 正文长度)`` 做 key，而最典型的订正动作恰恰是等长编辑
    （``550`` → ``660``、``口啤`` → ``口碑``），缓存撞不到变化。
    """
    cached = getattr(note, _SECTIONS_ATTR, None)
    if cached is None:
        cached = extract_brand_sections(note.raw_body)
        try:
            setattr(note, _SECTIONS_ATTR, cached)
        except AttributeError:      # slots 化的笔记对象：不缓存也能跑
            pass
    return cached


def find_card_section(sections: list, topic: str):
    """在竞品卡里找匹配 ``topic`` 的 H2。精确 → topic⊂H2 → H2⊂topic。

    **不能**复用 ``find_section_for_topic``：它会先剥 ``云测/实测/测试`` +
    数字前缀（那是测试结果笔记专用的规整）。卡片里写 ``## 测试数据`` 会被
    规整成「数据」，而「数据」是「市场口碑数据」的子串 —— 一张根本没有口碑
    小节的卡就这样通过覆盖度预检，把测试数据渲染到「市场口碑数据」标签下，
    覆盖度告警还什么都不报（它只报缺什么、不报绑到了谁）。
    """
    topic = (topic or "").strip()
    if not topic or not sections:
        return None
    titles = [(s, (s.raw_title or "").strip()) for s in sections]
    for s, t in titles:
        if t == topic:
            return s
    for s, t in titles:
        if topic in t:
            return s
    for s, t in titles:
        if t and t in topic:
            return s
    return None
