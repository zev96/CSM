"""Tests for the Kuaishou comment adapter's URL → photoId extractor.

The bug this file locks down: ``kuaishou.com/f/<slug>`` is a share-token
redirect (the ``X-7Ellfyy6sQUWfo``-style token in the path is NOT a
photoId — it's a shareToken). The old regex matched ``/f/<slug>`` and
fed the slug to the GraphQL endpoint; kuaishou returned HTTP 200 with
``visionCommentList.rootComments = []``, so the result row landed with
``status=ok / total_fetched=0`` and every video showed up as "未找到"
even though cookies and the photo itself were fine. The adapter now
follows the redirect first, which turns the URL into
``/short-video/<real-photoId>``.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from csm_core.monitor.platforms.kuaishou_comment import KuaishouCommentAdapter


def _session_with_redirect(final_url: str) -> MagicMock:
    """Fake curl_cffi session whose GET returns a 200 + redirected URL."""
    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.url = final_url
    resp.text = ""
    sess.get.return_value = resp
    return sess


def test_short_video_direct_path_extracts_photo_id():
    """Canonical case: ``/short-video/<id>`` is the photoId verbatim."""
    sess = MagicMock()  # no HTTP needed — direct match
    pid, err = KuaishouCommentAdapter._extract_video_id(
        sess, "https://www.kuaishou.com/short-video/3xt3ptkr6mqei9a"
    )
    assert pid == "3xt3ptkr6mqei9a"
    assert err == ""
    sess.get.assert_not_called()


def test_www_f_share_link_follows_redirect_before_matching():
    """The reported bug: ``kuaishou.com/f/<slug>`` must redirect-expand
    to ``/short-video/<photoId>`` before the path regex runs. Old behavior
    matched the slug directly via the (now-removed) ``/f/(...)`` pattern
    and shipped the share token to GraphQL as if it were a photoId."""
    final = (
        "https://www.kuaishou.com/short-video/3xt3ptkr6mqei9a?"
        "shareToken=X-7Ellfyy6sQUWfo&shareObjectId=3xt3ptkr6mqei9a"
    )
    sess = _session_with_redirect(final)
    pid, err = KuaishouCommentAdapter._extract_video_id(
        sess, "https://www.kuaishou.com/f/X-7Ellfyy6sQUWfo"
    )
    assert pid == "3xt3ptkr6mqei9a", "should pick the /short-video/ photoId, not the /f/ token"
    assert err == ""
    sess.get.assert_called_once()


def test_v_kuaishou_short_link_still_redirects():
    """Regression guard for the original short-link handling — the redirect
    branch previously only triggered on ``v.kuaishou.com``; the fix
    broadened the predicate but must not regress this case."""
    final = "https://www.kuaishou.com/short-video/3xvva54ve2nwzsk"
    sess = _session_with_redirect(final)
    pid, _ = KuaishouCommentAdapter._extract_video_id(
        sess, "https://v.kuaishou.com/abcd1234"
    )
    assert pid == "3xvva54ve2nwzsk"


def test_share_link_with_share_object_id_in_query_string():
    """When the redirected URL carries ``shareObjectId=<photoId>`` in the
    query string but the path doesn't expose ``/short-video/``, we still
    pick the canonical id."""
    final = "https://www.kuaishou.com/profile/3xy?shareObjectId=3xt3ptkr6mqei9a"
    sess = _session_with_redirect(final)
    pid, _ = KuaishouCommentAdapter._extract_video_id(
        sess, "https://www.kuaishou.com/f/some-token"
    )
    assert pid == "3xt3ptkr6mqei9a"


def _gql_response(*, root_comments=None, root_comments_v2=None, pcursor="", pcursor_v2=""):
    """Build a fake ``POST /graphql`` response object the adapter can parse.

    Either or both V1/V2 fields can be populated — that's the whole point
    of these tests, to lock down which one is preferred.
    """
    resp = MagicMock()
    resp.status_code = 200
    body = {
        "data": {
            "visionCommentList": {
                "commentCount": len(root_comments) if root_comments else None,
                "commentCountV2": len(root_comments_v2) if root_comments_v2 else None,
                "pcursor": pcursor or "no_more",
                "pcursorV2": pcursor_v2 or "no_more",
                "rootComments": root_comments,
                "rootCommentsV2": root_comments_v2,
            }
        }
    }
    resp.json.return_value = body
    return resp


def _make_adapter():
    """Build adapter with pacer stubbed so tests don't sleep."""
    from csm_core.monitor.platforms.kuaishou_comment import KuaishouCommentAdapter
    a = KuaishouCommentAdapter()
    a._pacer.wait = lambda: None
    return a


def test_fetch_prefers_v2_rootcomments_over_v1():
    """The reported bug: kuaishou now only fills ``rootCommentsV2``, the
    legacy ``rootComments`` stays empty even on videos with active
    discussion. Old adapter read V1 first, got [], and reported
    ``total_fetched=0`` for every task — UI displayed "未找到" across the
    board even though the cookie was valid and the photoId correct.
    Adapter must read V2 when present."""
    sess = MagicMock()
    sess.post.return_value = _gql_response(
        root_comments=[],  # V1 empty, like the wild kuaishou response
        root_comments_v2=[
            {"commentId": "c1", "content": "hello", "authorName": "alice", "likedCount": 3},
            {"commentId": "c2", "content": "world", "authorName": "bob", "likedCount": 1},
        ],
    )
    adapter = _make_adapter()
    comments, ok, err = adapter._fetch_comments(sess, "fakePhotoId", limit=200)
    assert ok is True
    assert err is None
    assert [c["text"] for c in comments] == ["hello", "world"]
    assert [c["rank"] for c in comments] == [1, 2]


def test_fetch_falls_back_to_v1_when_v2_absent():
    """Regression guard: if some future / legacy kuaishou response has
    no V2 fields at all, V1 should still work."""
    sess = MagicMock()
    sess.post.return_value = _gql_response(
        root_comments=[
            {"commentId": "c1", "content": "legacy", "authorName": "x", "likedCount": 0},
        ],
        root_comments_v2=None,
    )
    adapter = _make_adapter()
    comments, ok, _ = adapter._fetch_comments(sess, "fakePhotoId", limit=200)
    assert ok is True
    assert [c["text"] for c in comments] == ["legacy"]


def test_fetch_uses_v2_pcursor_when_paging_v2():
    """Pagination cursor must be picked from the same family as the
    chosen comment field. Mixing ``rootCommentsV2`` with ``pcursor``
    (V1) would either loop forever or terminate after page 1 with
    partial data, both bad."""
    sess = MagicMock()
    # Page 1: V2 comments + V2 cursor saying "more available"
    page1 = _gql_response(
        root_comments_v2=[{"commentId": "c1", "content": "a", "authorName": "x"}],
        pcursor="should-not-be-used",
        pcursor_v2="next-page",
    )
    # Page 2: V2 comments + V2 cursor saying done
    page2 = _gql_response(
        root_comments_v2=[{"commentId": "c2", "content": "b", "authorName": "y"}],
        pcursor="",
        pcursor_v2="no_more",
    )
    sess.post.side_effect = [page1, page2]
    adapter = _make_adapter()
    comments, ok, _ = adapter._fetch_comments(sess, "fakePhotoId", limit=200)
    assert ok is True
    assert [c["text"] for c in comments] == ["a", "b"]
    # Verify the 2nd call carried the V2 cursor, not the V1 one
    second_payload = sess.post.call_args_list[1].kwargs["json"]
    assert second_payload["variables"]["pcursor"] == "next-page"


def test_unresolvable_share_link_falls_through_to_html_grep():
    """If redirect resolution returns a URL that still doesn't match any
    path pattern AND the HTML fallback can't find a photoId either, we
    must return an error rather than silently shipping the share token —
    that was the heart of the original bug."""
    final = "https://www.kuaishou.com/about/unrelated"
    sess = MagicMock()
    # 1st GET (redirect resolution) lands somewhere unmatched
    redirect_resp = MagicMock()
    redirect_resp.status_code = 200
    redirect_resp.url = final
    redirect_resp.text = "no photoId markers here at all"
    # 2nd GET (HTML fallback) also produces nothing usable
    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.text = "<html>no markers</html>"
    sess.get.side_effect = [redirect_resp, html_resp]

    pid, err = KuaishouCommentAdapter._extract_video_id(
        sess, "https://www.kuaishou.com/f/X-doesnt-resolve"
    )
    assert pid is None
    assert "could not find photoId" in err
