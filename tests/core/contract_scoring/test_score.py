from csm_core.config import ScoringConfig
from csm_core.lint.model import LintHit, LintReport
from csm_core.scoring import score_article


def _hit(cat: str, fixable: bool) -> LintHit:
    return LintHit(category=cat, text="x", start=0, end=1,
                   sentence="s", fixable=fixable, suggestion="")


CLEAN = (
    "上周把家里那台老吸尘器换掉了。原因说来好笑：猫毛缠进滚刷，拆了半小时。\n\n"
    "新机器用了十天，地毯上的猫毛一遍过。楼下邻居问我是不是换了保洁阿姨。\n\n"
    "要说缺点也有，尘杯小了点，倒得勤。但对我这种懒人，能少拆一次刷头就是胜利。"
)


def test_clean_text_high_score():
    rep = score_article(CLEAN, lint_report=LintReport(hits=[], fixed_text=CLEAN))
    assert rep.total >= 80.0
    assert all(p.points >= 0 for p in rep.parts)


def test_lint_weights_and_cap():
    judgment = [_hit("absolute", False)] * 3       # 3×4=12
    mech = [_hit("emoji", True)] * 2               # 2×2=4
    rep = score_article("x", lint_report=LintReport(hits=judgment + mech, fixed_text="x"))
    lint_part = next(p for p in rep.parts if p.key == "lint")
    assert lint_part.points == 16.0
    many = [_hit("traffic", False)] * 20           # 80 → cap 30
    rep2 = score_article("x", lint_report=LintReport(hits=many, fixed_text="x"))
    assert next(p for p in rep2.parts if p.key == "lint").points == 30.0


def test_factcheck_completeness_deduction():
    rep = score_article("x", lint_report=LintReport(hits=[], fixed_text="x"),
                        factcheck_violations=2, completeness_missing=1)
    assert next(p for p in rep.parts if p.key == "factcheck").points == 12.0
    assert next(p for p in rep.parts if p.key == "completeness").points == 4.0
    caps = score_article("x", lint_report=LintReport(hits=[], fixed_text="x"),
                         factcheck_violations=10, completeness_missing=10)
    assert next(p for p in caps.parts if p.key == "factcheck").points == 18.0
    assert next(p for p in caps.parts if p.key == "completeness").points == 12.0


def test_total_floor_zero():
    hits = [_hit("absolute", False)] * 30
    rep = score_article("首先，" * 300, lint_report=LintReport(hits=hits, fixed_text="x"),
                        factcheck_violations=10, completeness_missing=10)
    assert rep.total >= 0.0


def test_extra_ai_words_via_config():
    cfg = ScoringConfig(extra_ai_words=["赋能"])
    base = score_article("产品赋能生活。", lint_report=LintReport(hits=[], fixed_text="x"))
    ext = score_article("产品赋能生活。", lint_report=LintReport(hits=[], fixed_text="x"), config=cfg)
    assert ext.total <= base.total
