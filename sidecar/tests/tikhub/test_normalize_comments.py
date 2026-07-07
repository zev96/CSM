import json, pathlib
from csm_core.monitor.tikhub.normalize import (
    normalize_douyin_comments, normalize_bilibili_comments)

FIX = pathlib.Path(__file__).parent / "fixtures"

def test_douyin_real_fixture():
    raw = json.loads((FIX / "tikhub_douyin_comments.json").read_text(encoding="utf-8"))
    out = normalize_douyin_comments(raw)
    assert len(out) == 19
    assert all(o["rank"] == i + 1 for i, o in enumerate(out))
    assert out[0]["text"] == "有没有用过友望大橘吸尘器的～咋样呀"
    assert out[0]["author"] == "海带山药排骨汤"
    assert out[0]["likes"] == 3
    assert all(set(o) == {"rank", "text", "author", "likes"} for o in out)

def test_bilibili_real_fixture_replies():
    raw = json.loads((FIX / "tikhub_bilibili_comments.json").read_text(encoding="utf-8"))
    out = normalize_bilibili_comments(raw, first_page=True)
    assert len(out) >= 1
    assert any(o["author"] == "Or9kkk" for o in out)          # fixture 里 replies[0] 作者
    assert all(set(o) == {"rank", "text", "author", "likes"} for o in out)
    assert all(o["rank"] == i + 1 for i, o in enumerate(out))

def test_bilibili_pinned_first_and_dedup():
    # 合成:置顶 + replies 里重复同文本 -> 置顶排 rank1 且全局按文本去重
    raw = {"data": {"data": {
        "top": {"upper": {"content": {"message": "置顶话"}, "member": {"uname": "UP"}, "like": 99},
                "admin": None},
        "replies": [
            {"content": {"message": "置顶话"}, "member": {"uname": "UP"}, "like": 99},   # 与置顶重复
            {"content": {"message": "普通评论"}, "member": {"uname": "路人"}, "like": 1},
        ],
    }}}
    out = normalize_bilibili_comments(raw, first_page=True)
    assert out[0] == {"rank": 1, "text": "置顶话", "author": "UP", "likes": 99}
    assert [o["text"] for o in out] == ["置顶话", "普通评论"]      # 去重后置顶只出现一次
