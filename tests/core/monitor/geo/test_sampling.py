"""§4.6 多采样投票 + 采样驱动的纯函数单测。"""
from __future__ import annotations
import threading
import pytest

from csm_core.monitor.geo.models import GeoCell, ClassifiedCitation, RecommendedEntity
from csm_core.monitor.geo.sampling import (
    majority_sentiment, samples_digest, vote_cell, sampled_cell,
)


def ok(mentioned=False, rank=-1, sentiment="na", *, platform="kimi", keyword="k",
       answer="ans", cites=None, summary="", raw=None):
    return GeoCell(platform=platform, keyword=keyword, mentioned=mentioned, rank=rank,
                   sentiment=sentiment, answer_text=answer, status="ok",
                   citations=cites or [], summary=summary, raw=raw or {})


def fail(status="error", fail_reason="timeout", *, platform="kimi", keyword="k", err="boom"):
    return GeoCell(platform=platform, keyword=keyword, status=status,
                   fail_reason=fail_reason, raw={"error": err})


# ── majority_sentiment ────────────────────────────────────────────────────
class TestMajoritySentiment:
    def test_majority_wins(self):
        assert majority_sentiment(["pos", "pos", "neg"]) == "pos"

    def test_tie_returns_na(self):
        assert majority_sentiment(["pos", "neg"]) == "na"       # 1-1 平局
        assert majority_sentiment(["pos", "neg", "neu"]) == "na"  # 三方各 1

    def test_empty_returns_na(self):
        assert majority_sentiment([]) == "na"
        assert majority_sentiment(["na", "na"]) == "na"          # na 不计票


# ── vote_cell ─────────────────────────────────────────────────────────────
class TestVoteCell:
    def test_empty_raises(self):
        with pytest.raises(ValueError):
            vote_cell([])

    def test_single_sample_returned_verbatim(self):
        # K=1:原样返回同一对象(逐字节向后兼容,不加 samples、不动 rank)。
        c = ok(mentioned=True, rank=2, sentiment="pos", raw={"x": 1})
        out = vote_cell([c])
        assert out is c
        assert "samples" not in out.raw

    def test_mention_majority(self):
        out = vote_cell([ok(mentioned=True, rank=1, sentiment="pos"),
                         ok(mentioned=True, rank=3, sentiment="pos"),
                         ok(mentioned=False)])
        assert out.mentioned is True
        assert out.status == "ok"

    def test_mention_tie_falls_back_to_prev(self):
        pair = [ok(mentioned=True, rank=1, sentiment="pos"), ok(mentioned=False)]
        assert vote_cell(pair, prev_mentioned=True).mentioned is True    # 平局→prev
        assert vote_cell(pair, prev_mentioned=False).mentioned is False
        assert vote_cell(pair, prev_mentioned=None).mentioned is False   # 缺省保守 False

    def test_rank_median_int_over_hit_samples(self):
        out = vote_cell([ok(mentioned=True, rank=1), ok(mentioned=True, rank=3),
                         ok(mentioned=True, rank=5)])
        assert out.rank == 3                                     # 中位 3
        out2 = vote_cell([ok(mentioned=True, rank=2), ok(mentioned=True, rank=4)])
        assert out2.rank == 3                                    # (2+4)/2=3.0 → int 3

    def test_rank_ignores_non_hit_samples(self):
        # 只用命中(mentioned 且 rank>0)样本;未命中/rank<=0 不进中位。
        out = vote_cell([ok(mentioned=True, rank=4), ok(mentioned=True, rank=6),
                         ok(mentioned=False, rank=-1)])
        assert out.mentioned is True
        assert out.rank == 5                                     # median(4,6)

    def test_mentioned_but_no_positive_rank_gives_minus_one(self):
        out = vote_cell([ok(mentioned=True, rank=-1), ok(mentioned=True, rank=0)])
        assert out.mentioned is True and out.rank == -1          # 提及但未进序列

    def test_sentiment_majority_and_tie(self):
        out = vote_cell([ok(mentioned=True, rank=1, sentiment="pos"),
                         ok(mentioned=True, rank=1, sentiment="pos"),
                         ok(mentioned=True, rank=1, sentiment="neg")])
        assert out.sentiment == "pos"
        tie = vote_cell([ok(mentioned=True, rank=1, sentiment="pos"),
                         ok(mentioned=True, rank=1, sentiment="neg")])
        assert tie.sentiment == "na"                             # 平局→na

    def test_not_mentioned_forces_rank_and_sentiment_reset(self):
        # 投票判 not mentioned → rank=-1、senti=na(即便个别样本带值)。
        out = vote_cell([ok(mentioned=False), ok(mentioned=False),
                         ok(mentioned=True, rank=1, sentiment="pos")])
        assert out.mentioned is False and out.rank == -1 and out.sentiment == "na"

    def test_citations_and_answer_from_first_ok_only_not_union(self):
        c1 = [ClassifiedCitation(url="https://a.com/1", domain="a.com")]
        c2 = [ClassifiedCitation(url="https://b.com/2", domain="b.com")]
        r1 = [RecommendedEntity(name="小鹏", position=1)]
        out = vote_cell([
            ok(mentioned=True, rank=1, sentiment="pos", answer="第一样本", cites=c1,
               summary="s1").model_copy(update={"recommended": r1}),
            ok(mentioned=True, rank=1, sentiment="pos", answer="第二样本", cites=c2,
               summary="s2"),
        ])
        assert [c.url for c in out.citations] == ["https://a.com/1"]   # 只取首样本,不并集
        assert out.answer_text == "第一样本"
        assert out.summary == "s1"
        assert [r.name for r in out.recommended] == ["小鹏"]

    def test_first_ok_skips_leading_failures(self):
        # 首个失败样本不算「首个 ok」——信源应来自第一个 ok。
        c2 = [ClassifiedCitation(url="https://b.com/2", domain="b.com")]
        out = vote_cell([fail(), ok(mentioned=True, rank=1, answer="真答案", cites=c2)])
        assert out.status == "ok"
        assert out.answer_text == "真答案"
        assert [c.url for c in out.citations] == ["https://b.com/2"]

    def test_all_failed_returns_first_failure_with_digest(self):
        out = vote_cell([fail(status="blocked", fail_reason="not_logged_in", err="未登录"),
                         fail(status="error", fail_reason="timeout")])
        assert out.status == "blocked" and out.fail_reason == "not_logged_in"
        assert out.raw.get("error") == "未登录"                   # 保留首个失败原文
        assert len(out.raw["samples"]) == 2                      # 附样本摘要供追溯

    def test_mixed_votes_over_ok_only(self):
        # 2 ok(1 提及 1 未提及)+ 1 error → ok 内 1-1 平局 → prev。
        out = vote_cell([ok(mentioned=True, rank=1), ok(mentioned=False), fail()],
                        prev_mentioned=True)
        assert out.status == "ok" and out.mentioned is True

    def test_voted_cell_carries_samples_digest(self):
        out = vote_cell([ok(mentioned=True, rank=1), ok(mentioned=True, rank=1)])
        assert len(out.raw["samples"]) == 2


# ── samples_digest ────────────────────────────────────────────────────────
def test_samples_digest_shape():
    d = samples_digest([ok(mentioned=True, rank=2, sentiment="pos"),
                        fail(fail_reason="timeout")])
    assert d[0] == {"status": "ok", "mentioned": True, "rank": 2,
                    "sentiment": "pos", "fail_reason": ""}
    assert d[1]["status"] == "error" and d[1]["fail_reason"] == "timeout"


# ── sampled_cell 驱动 ──────────────────────────────────────────────────────
def _scripted(cells):
    """按序返回 cells 的 sample_fn + 调用计数。"""
    box = {"i": 0}
    def fn():
        c = cells[box["i"]]
        box["i"] += 1
        return c
    return fn, box


class TestSampledCell:
    def test_k1_no_flip_returns_single(self):
        fn, box = _scripted([ok(mentioned=True, rank=1)])
        out = sampled_cell(fn, k=1, flip_recheck=True, prev_mentioned=True)
        assert box["i"] == 1 and out.mentioned is True           # 未翻转 → 不补采

    def test_runs_k_times_and_votes(self):
        fn, box = _scripted([ok(mentioned=True, rank=1), ok(mentioned=True, rank=3),
                             ok(mentioned=False)])
        out = sampled_cell(fn, k=3, flip_recheck=False)
        assert box["i"] == 3
        assert out.mentioned is True and out.rank == 2           # median(1,3)=2

    def test_flip_recheck_confirms_flip(self):
        # prev=False,本轮 K=1 判 True(翻转)→ 补采 1;补采也 True → 确认 True(2-0)。
        fn, box = _scripted([ok(mentioned=True, rank=1), ok(mentioned=True, rank=1)])
        out = sampled_cell(fn, k=1, flip_recheck=True, prev_mentioned=False)
        assert box["i"] == 2                                     # 补采了 1 次
        assert out.mentioned is True                            # 翻转确认

    def test_flip_recheck_rejects_unconfirmed_flip(self):
        # prev=False,K=1 判 True(翻转)→ 补采;补采 False → 1-1 平局 → 回落 prev=False。
        fn, box = _scripted([ok(mentioned=True, rank=1), ok(mentioned=False)])
        out = sampled_cell(fn, k=1, flip_recheck=True, prev_mentioned=False)
        assert box["i"] == 2
        assert out.mentioned is False                           # 翻转未确认,维持上轮

    def test_no_recheck_when_not_flipped(self):
        # prev=True,本轮也 True → 未翻转 → 不补采。
        fn, box = _scripted([ok(mentioned=True, rank=1)])
        out = sampled_cell(fn, k=1, flip_recheck=True, prev_mentioned=True)
        assert box["i"] == 1 and out.mentioned is True

    def test_no_recheck_when_prev_unknown(self):
        fn, box = _scripted([ok(mentioned=True, rank=1)])
        out = sampled_cell(fn, k=1, flip_recheck=True, prev_mentioned=None)
        assert box["i"] == 1                                     # 无基线 → 不补采

    def test_no_recheck_when_disabled(self):
        fn, box = _scripted([ok(mentioned=True, rank=1)])
        sampled_cell(fn, k=1, flip_recheck=False, prev_mentioned=False)
        assert box["i"] == 1                                     # 关掉复核 → 不补采

    def test_no_recheck_when_all_failed(self):
        # 全失败(voted.status != ok)→ 即便 prev 提及也不补采(erroring 平台不复核)。
        fn, box = _scripted([fail(), fail()])
        out = sampled_cell(fn, k=2, flip_recheck=True, prev_mentioned=True)
        assert box["i"] == 2 and out.status == "error"

    def test_cancel_between_samples_raises(self):
        try:
            from csm_sidecar.services.monitor_loop import _CancelledFetch
        except ImportError:
            pytest.skip("sidecar 不可用,无法区分取消")
        tok = threading.Event()
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            tok.set()                                            # 首样本后置位
            return ok(mentioned=True, rank=1)
        with pytest.raises(_CancelledFetch):
            sampled_cell(fn, k=3, flip_recheck=False, cancel_token=tok)
        assert calls["n"] == 1                                   # 第 2 次采样前 maybe_cancel 拦下
