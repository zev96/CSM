from pathlib import Path

import pytest

from csm_core.assembler.plan import AssemblyPlan
from csm_sidecar.services import factcheck_service


def _plan() -> AssemblyPlan:
    return AssemblyPlan(keyword="无线吸尘器", template_id="t", seed=0)


def _seed(job_id: str, out_dir: Path) -> None:
    factcheck_service.cache_pending(
        job_id, plan=_plan(), out_dir=out_dir, keyword="无线吸尘器",
        fmt="markdown", allowed_numbers={220.0}, allowed_certs={"CE"},
    )


def test_resolve_exports_when_clean(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j1", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j1", final_text="吸力220AW，CE认证。", released_numbers=[], released_certs=[])
    assert res["ok"] is True
    assert Path(res["document"]).exists()
    assert factcheck_service.get_pending("j1") is None


def test_resolve_still_blocked_when_violation_remains(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j2", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j2", final_text="吸力250AW。", released_numbers=[], released_certs=[])
    assert res["ok"] is False
    assert res["violations"][0]["value"] == "250AW"
    assert factcheck_service.get_pending("j2") is not None


def test_resolve_with_released_number_passes(tmp_path: Path):
    factcheck_service.reset_for_test()
    _seed("j3", tmp_path)
    res = factcheck_service.resolve_and_export(
        "j3", final_text="吸力250AW。", released_numbers=[250.0], released_certs=[])
    assert res["ok"] is True and Path(res["document"]).exists()


def test_resolve_unknown_job_raises(tmp_path: Path):
    factcheck_service.reset_for_test()
    with pytest.raises(KeyError):
        factcheck_service.resolve_and_export(
            "nope", final_text="x", released_numbers=[], released_certs=[])


def test_resolve_export_carries_article_title(tmp_path: Path):
    """事实核对放行后导出的文档必须带**文章标题**，不是搜索关键词。

    成稿正文里没有标题（标题是单独字段），导出时才补。cache_pending 收了
    title 却没存进 _Pending 的话，这条链回落到 keyword —— 文档首行变成
    「# 无线吸尘器」，而这正是本次要修的那个病在另一条导出路径上的翻版。
    """
    factcheck_service.reset_for_test()
    factcheck_service.cache_pending(
        "j9", plan=_plan(), out_dir=tmp_path, keyword="无线吸尘器",
        fmt="markdown", allowed_numbers={220.0}, allowed_certs={"CE"},
        title="2026年无线吸尘器十大排名",
    )
    res = factcheck_service.resolve_and_export(
        "j9", final_text="## 一、品牌分析\n\n吸力220AW，CE认证。",
        released_numbers=[], released_certs=[])
    assert res["ok"] is True
    assert res["title"] == "2026年无线吸尘器十大排名"
    head = Path(res["document"]).read_text(encoding="utf-8").splitlines()[0]
    assert head == "# 2026年无线吸尘器十大排名"


def test_resolve_export_prefers_caller_title(tmp_path: Path):
    """调用方现取的标题优先于起飞时缓存的那个。

    用户被事实核对拦下后点「换标题」——编辑器立刻显示新标题，而缓存里还是
    起飞时那个。不透传的话导出的文件首行是旧标题，正是用户报的「导出的文章
    标题也不一样」。空白 / 不传 → 退回缓存值（老客户端零回归）。
    """
    factcheck_service.reset_for_test()
    for job_id, override, expected in (
        ("t1", "换过的新标题", "换过的新标题"),
        ("t2", "   ", "起飞时的旧标题"),
        ("t3", None, "起飞时的旧标题"),
    ):
        factcheck_service.cache_pending(
            job_id, plan=_plan(), out_dir=tmp_path, keyword="无线吸尘器",
            fmt="markdown", allowed_numbers={220.0}, allowed_certs={"CE"},
            title="起飞时的旧标题",
        )
        res = factcheck_service.resolve_and_export(
            job_id, final_text="## 一、品牌分析\n\n吸力220AW，CE认证。",
            released_numbers=[], released_certs=[], title=override)
        assert res["ok"] is True
        assert res["title"] == expected, f"{job_id}: {res['title']}"
        head = Path(res["document"]).read_text(encoding="utf-8").splitlines()[0]
        assert head == f"# {expected}"
