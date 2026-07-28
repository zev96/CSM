"""润色链不得改动文章标题 —— chain_service 侧的接线。

用户报「这里的润色，是不应该修改标题的」+「标题生成会修改我输入的关键词」。
根是同一个：正文首行的 H1 就是全链路认定的文章标题，而链的 prompt 只是把
标题当写作指引给了 LLM，没人拦着它写一个自己的。LLM 写的标题不受
「必须原样包含关键词」约束（那条只长在 /api/title 的候选生成上），于是
关键词被改没了。

守卫逻辑本身在 tests/core/llm/test_title_guard.py；这里只钉「链真的调了它」
+ 「纠正说明有记录、不静默」。
"""
from csm_sidecar.services import chain_service


class _Client:
    """按顺序吐预设输出，模拟 LLM 擅自改标题。"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def complete(self, *, system, user, temperature=None):
        self.calls.append((system, user))
        return self.outputs[len(self.calls) - 1]


def _steps(*specs):
    return [chain_service.ChainStepInput(skill_id=s[0], role=s[1], name=s[2], body=s[3])
            for s in specs]


def _run(outputs, *, draft, title, keyword="空气净化器", steps=None):
    chain_service.reset_for_test()
    c = _Client(outputs)
    state = chain_service.run_chain(
        "job-title", steps or _steps(("p", "persona", "人设", "P")),
        draft=draft, keyword=keyword, title=title, angle_directive=None,
        brand_facts=None, provider="mock", model=None, client=c,
        checkpoint=lambda: None, on_pass=lambda p: None,
    )
    return state, c


def test_llm_inventing_a_title_gets_replaced_by_the_users():
    state, _ = _run(
        ["# 净化器选购全攻略\n\n润色后的正文"],
        draft="## 一、品牌分析\n毛坯正文",
        title="养宠家庭空气净化器推荐哪款好？",
    )
    assert state.final_text == "# 养宠家庭空气净化器推荐哪款好？\n\n润色后的正文"
    assert state.title_corrections and "自造" in state.title_corrections[0]


def test_existing_title_rewritten_by_the_chain_is_restored():
    # 用户在初稿里手写了标题 → 毛坯带 H1 → 链必须原样留着
    state, _ = _run(
        ["# 被润色改过的标题\n\n润色后的正文"],
        draft="# 我自己写的标题\n\n毛坯正文",
        title="我自己写的标题",
    )
    assert state.final_text.splitlines()[0] == "# 我自己写的标题"
    assert state.title_corrections and "改写" in state.title_corrections[0]


def test_chain_dropping_the_title_puts_it_back():
    state, _ = _run(
        ["润色后的正文，标题没了。"],
        draft="# 我自己写的标题\n\n毛坯正文",
        title="我自己写的标题",
    )
    assert state.final_text.startswith("# 我自己写的标题\n\n")
    assert state.title_corrections and "删除" in state.title_corrections[0]


def test_untouched_output_is_byte_identical_and_records_nothing():
    # 今天的常态：毛坯无 H1、链输出也无 H1（标题是单独字段，导出时才补）。
    # 守卫在这条路上必须一个字都不动 —— 否则字数/查重/事实核对的输入全变了。
    state, _ = _run(
        ["## 一、品牌分析\n润色后的正文"],
        draft="## 一、品牌分析\n毛坯正文",
        title="用户选的标题",
    )
    assert state.final_text == "## 一、品牌分析\n润色后的正文"
    assert state.title_corrections == []


def test_later_passes_are_guarded_too():
    # 链越往后越容易被「改进措辞」顺手改掉标题 —— 精修 pass 同样要过守卫。
    state, c = _run(
        ["# 用户选的标题\n\n第一轮输出", "# 第二轮擅自改的标题\n\n第二轮输出"],
        draft="## 章节\n毛坯",
        title="用户选的标题",
        steps=_steps(("p", "persona", "人设", "P"), ("h", "humanize", "去AI味", "H")),
    )
    assert state.final_text == "# 用户选的标题\n\n第二轮输出"
    assert any("pass 1" in n for n in state.title_corrections)
    # 精修 pass 的 prompt 里带了标题硬约束（上段输出有标题行才加）
    assert "标题硬约束" in c.calls[1][1]


def test_no_user_title_still_constrains_the_keyword():
    """默认流程：用户只填了关键词、没选标题。

    这条路占绝大多数（「换标题」只在成稿面板上，链第一次跑时用户根本还没
    机会选标题）。链可以自己拟标题，但关键词必须一字不差留着 —— 否则用户
    的 SEO 词就被润色改没了，正是用户报的第二个问题。
    """
    state, c = _run(
        ["# 2026年十大净化器推荐榜\n\n润色后的正文", "## 一、品牌分析\n第二轮输出"],
        draft="## 一、品牌分析\n毛坯",
        title=None,
        keyword="空气净化器推荐",
        steps=_steps(("p", "persona", "人设", "P"), ("h", "humanize", "去AI味", "H")),
    )
    # 自造标题不含关键词 → 整行移除，退回导出层用关键词兜底
    assert not state.passes[0].output.startswith("#")
    assert any("关键词" in n for n in state.title_corrections)
    # 正向约束也下了（两个 pass 都要）
    assert "空气净化器推荐" in c.calls[0][1] and "标题硬约束" in c.calls[0][1]
    assert "标题硬约束" in c.calls[1][1]


def test_invented_title_keeping_the_keyword_is_allowed():
    state, _ = _run(
        ["# 空气净化器推荐哪款好？实测三款\n\n润色后的正文"],
        draft="## 一、品牌分析\n毛坯",
        title=None,
        keyword="空气净化器推荐",
    )
    assert state.final_text.startswith("# 空气净化器推荐哪款好？实测三款")
    assert state.title_corrections == []


def test_refine_pass_keeps_the_no_new_title_rule_on_the_main_path():
    """主路径象限：用户定了标题、但上段输出不带标题行（毛坯文不产 H1）。

    精修 pass 的 clause 只看上段输出的话，这里会下成 keyword_title_clause ——
    反过来邀请 LLM 加个标题，而链输出本不该带标题（硬塞 H1 会让字数/查重/
    事实核对的输入全变样）。判据必须和 step0 一致：看用户有没有定标题。
    """
    _, c = _run(
        ["## 一、品牌分析\n第一轮输出", "## 一、品牌分析\n第二轮输出"],
        draft="## 一、品牌分析\n毛坯",
        title="养宠家庭空气净化器推荐哪款好？",
        steps=_steps(("p", "persona", "人设", "P"), ("h", "humanize", "去AI味", "H")),
    )
    assert "也不要自己新增一个" in c.calls[1][1]
    assert "如果你要给正文加标题行" not in c.calls[1][1]


def test_no_title_and_no_keyword_adds_no_clause():
    # 零回归边界：既无标题也无关键词 → prompt 不变。
    _, c = _run(
        ["## 章节\n第一轮输出", "## 章节\n第二轮输出"],
        draft="## 章节\n毛坯",
        title=None,
        keyword="",
        steps=_steps(("p", "persona", "人设", "P"), ("h", "humanize", "去AI味", "H")),
    )
    assert "标题硬约束" not in c.calls[0][1]
    assert "标题硬约束" not in c.calls[1][1]


def test_rerun_is_guarded_too():
    state, _ = _run(
        ["# 用户选的标题\n\n第一轮输出"],
        draft="## 章节\n毛坯",
        title="用户选的标题",
    )
    # 首轮吐的就是用户的标题 —— 没动过，守卫不该记账
    assert state.title_corrections == []

    class _Rerun:
        def complete(self, *, system, user, temperature=None):
            return "# 重跑时又改的标题\n\n重跑后的正文"

    chain_service.rerun("job-title", 0, client=_Rerun())
    st = chain_service.get_state("job-title")
    assert st.final_text == "# 用户选的标题\n\n重跑后的正文"
    assert st.title_corrections and "pass 0" in st.title_corrections[0]
