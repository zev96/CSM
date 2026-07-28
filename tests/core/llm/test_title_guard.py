"""标题守卫 —— 润色链不得新增/改写/删除文章标题。

用户报「润色不应该修改标题」+「标题生成会改掉我输入的关键词」。两条是同一
个根：链的 prompt 把标题当写作指引给了 LLM（【标题】…，围绕标题开篇点题），
但没有任何东西禁止它自己写一个 H1 或把原标题删掉。而正文首行的 H1 恰恰是
全链路（ensure_title / extract_title / 前端 effectiveTitle）认定的文章标题
—— 于是 LLM 写的标题就成了文章标题，而它不受「必须原样包含关键词」的约束
（那条约束只长在 /api/title 的候选生成上）。
"""
from csm_core.llm.title_guard import TITLE_CLAUSE, enforce, leading_h1


class TestLeadingH1:
    def test_finds_h1_skipping_blank_lines(self):
        assert leading_h1("\n\n# 标题\n\n正文") == (2, "标题")

    def test_h2_is_a_section_not_the_article_title(self):
        assert leading_h1("## 一、品牌分析\n正文") is None

    def test_no_heading(self):
        assert leading_h1("正文第一句。\n# 后面的才不算") is None

    def test_empty(self):
        assert leading_h1("") is None
        assert leading_h1(None) is None


class TestEnforceRestoresUserTitle:
    def test_rewritten_title_is_restored(self):
        before = "# 养宠家庭空气净化器推荐哪款好？\n\n毛坯正文"
        after = "# 空气净化器怎么选才不踩坑\n\n润色后的正文"
        out, note = enforce(before, after, title="养宠家庭空气净化器推荐哪款好？")
        assert out == "# 养宠家庭空气净化器推荐哪款好？\n\n润色后的正文"
        assert note and "改写" in note

    def test_deleted_title_is_put_back(self):
        before = "# 我的标题\n\n毛坯正文"
        after = "润色后的正文，标题没了。"
        out, note = enforce(before, after, title="我的标题")
        assert out == "# 我的标题\n\n润色后的正文，标题没了。"
        assert note and "删除" in note

    def test_untouched_title_passes_through_byte_identical(self):
        before = "# 我的标题\n\n毛坯"
        after = "# 我的标题\n\n润色后的正文"
        out, note = enforce(before, after, title="我的标题")
        assert out == after
        assert note is None


class TestEnforceWhenInputHasNoTitle:
    """毛坯文本身不带标题（compose_draft 不生成 H1）—— 今天的主路径。"""

    def test_llm_inventing_a_title_gets_replaced_by_the_users(self):
        before = "## 一、品牌分析\n正文"
        after = "# LLM自己想的标题\n\n## 一、品牌分析\n润色后的正文"
        out, note = enforce(before, after, title="用户选的标题")
        assert out == "# 用户选的标题\n\n## 一、品牌分析\n润色后的正文"
        assert note and "自造" in note

    def test_echoing_the_users_title_is_fine(self):
        before = "## 一、品牌分析\n正文"
        after = "# 用户选的标题\n\n## 一、品牌分析\n润色后的正文"
        out, note = enforce(before, after, title="用户选的标题")
        assert out == after
        assert note is None

    def test_no_title_in_no_title_out_is_todays_behaviour(self):
        # 链输出不带标题是今天的行为：标题是单独字段，导出时 ensure_title 才补。
        # 守卫不能在这里硬塞一个 H1，否则字数/查重/事实核对的输入都变了。
        before = "## 一、品牌分析\n正文"
        after = "## 一、品牌分析\n润色后的正文"
        out, note = enforce(before, after, title="用户选的标题")
        assert out == after
        assert note is None


class TestGuardNeverRewritesTheKeywordItself:
    """守卫自己不能成为「改关键词」的路径 —— 归一化只用于比较，不用于回写。"""

    def test_fullwidth_space_in_title_survives_restoration(self):
        # 全角空格 U+3000（中文输入法全角模式下很常见）会被 str.split() 折成
        # 半角空格。拿归一化结果回写 = 守卫把关键词改了，正撞用户的要求。
        kw = "扫地机器人　推荐"
        before = f"# {kw}实测\n\n毛坯"
        after = "# 被改过的标题\n\n润色后的正文"
        out, note = enforce(before, after, title=f"{kw}实测", keyword=kw)
        assert out.splitlines()[0] == f"# {kw}实测"
        assert kw in out          # 关键词一字不差还在
        assert note is not None

    def test_double_space_in_title_survives_restoration(self):
        before = "# Dyson  V15 实测\n\n毛坯"
        after = "润色后的正文"
        out, _ = enforce(before, after, title="Dyson  V15 实测")
        assert out.splitlines()[0] == "# Dyson  V15 实测"

    def test_whitespace_only_mutation_is_still_restored_byte_exactly(self):
        # LLM 最容易干的不是重写标题，而是「顺手规范化」——把关键词里的全角
        # 空格换成半角。只按归一化比对的话这会被判成「没动」，而它恰恰就是
        # 「改了关键词」。字节不同就还原，文本本就等价、没有误报风险。
        kw = "扫地机器人　推荐"          # U+3000
        before = f"# {kw}实测\n\n毛坯"
        after = "# 扫地机器人 推荐实测\n\n润色后的正文"   # 半角
        out, note = enforce(before, after, title=f"{kw}实测", keyword=kw)
        assert out.splitlines()[0] == f"# {kw}实测"
        assert kw in out
        assert note and "空白" in note

    def test_byte_identical_title_is_a_true_no_op(self):
        before = "# 我的  标题\n\n毛坯"
        after = "# 我的  标题\n\n润色后的正文"
        out, note = enforce(before, after, title="我的 标题")
        assert out == after
        assert note is None

    def test_leading_fullwidth_space_in_the_title_is_not_stripped(self):
        # str.strip() 会剥掉 U+3000/NBSP —— 关键词首尾带它们时，剥了就是
        # 守卫自己改了关键词的字节。
        title = "　空气净化器推荐"
        before = "毛坯正文"
        after = "# 别的标题\n\n润色后的正文"
        out, _ = enforce(before, after, title=title)
        assert out.splitlines()[0] == f"# {title}"


class TestTitleMovedNotDeleted:
    def test_title_pushed_below_the_lede_is_hoisted_not_duplicated(self):
        before = "# 我的标题\n\n毛坯"
        after = "开篇先来一段引子。\n\n# 我的标题\n\n正文"
        out, note = enforce(before, after, title="我的标题")
        assert out.count("# 我的标题") == 1
        assert out.splitlines()[0] == "# 我的标题"
        assert "开篇先来一段引子。" in out
        assert note and "挪" in note

    def test_title_written_twice_leaves_exactly_one(self):
        # 只摘第一处的话输出里还是两个 H1 —— 正是这条分支要消灭的形态。
        before = "# 我的标题\n\n毛坯"
        after = "引子。\n\n# 我的标题\n\n正文\n\n# 我的标题\n\n结尾"
        out, _ = enforce(before, after, title="我的标题")
        assert out.count("# 我的标题") == 1
        assert out.splitlines()[0] == "# 我的标题"
        for kept in ("引子。", "正文", "结尾"):
            assert kept in out

    def test_h1_inside_a_code_fence_is_not_hoisted(self):
        # 围栏里的 `# foo` 是代码不是标题；当成标题搬走会把代码块掏空 ——
        # 静默改内容比漏纠正糟得多。
        before = "# 我的标题\n\n毛坯"
        after = "引子。\n\n```markdown\n# 我的标题\n```\n\n正文"
        out, note = enforce(before, after, title="我的标题")
        assert "```markdown\n# 我的标题\n```" in out
        assert out.splitlines()[0] == "# 我的标题"
        assert note and "删除" in note      # 正文里确实没有标题了 → 补回


class TestKeywordSafetyNet:
    """没有用户标题可还原时的兜底 —— 自造标题至少得含关键词。"""

    def test_invented_title_without_keyword_is_dropped(self):
        before = "正文"
        after = "# 随便编的标题\n\n润色后的正文"
        out, note = enforce(before, after, title=None, keyword="空气净化器")
        assert out == "润色后的正文"
        assert note and "关键词" in note

    def test_invented_title_containing_keyword_is_kept(self):
        before = "正文"
        after = "# 空气净化器怎么选\n\n润色后的正文"
        out, note = enforce(before, after, title=None, keyword="空气净化器")
        assert out == after
        assert note is None

    def test_title_only_output_is_never_emptied(self):
        # 删掉标题行就什么都不剩了 —— 空成稿会一路流进查重/事实核对/导出，
        # 比留一个不合规的标题糟得多。但不能静默：这稿的标题确实不合规。
        for after in ("# 随便编的标题", "# 随便编的标题\n\n\n"):
            out, note = enforce("正文", after, title=None, keyword="空气净化器")
            assert out == after
            assert note and "未移除" in note


class TestZeroRegression:
    def test_no_title_no_keyword_never_touches_text(self):
        before = "正文"
        after = "# 什么都没约束时不动它\n\n润色后的正文"
        out, note = enforce(before, after, title=None, keyword=None)
        assert out == after
        assert note is None

    def test_blank_title_is_treated_as_absent(self):
        before = "## 章节\n正文"
        after = "## 章节\n润色后的正文"
        out, note = enforce(before, after, title="   ")
        assert out == after
        assert note is None

    def test_title_whitespace_is_normalised_before_comparing(self):
        # H1 是单行结构；用户标题里的换行/多空格压成单空格后再比，避免
        # 「看起来一样但差一个空格」被判成 LLM 改了标题、白白重写一行。
        before = "# 我的  标题\n\n毛坯"
        after = "# 我的  标题\n\n润色后的正文"
        out, note = enforce(before, after, title="我的 标题")
        assert out == after
        assert note is None


def test_clause_is_non_empty_and_mentions_the_rule():
    assert "标题" in TITLE_CLAUSE
    assert TITLE_CLAUSE.strip() == TITLE_CLAUSE
