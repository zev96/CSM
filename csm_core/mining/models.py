"""Pydantic / dataclass models for the mining module.

VideoCard is the adapter→runner DTO (mutable dataclass — easier to fill in
incrementally as we parse a search result card). MiningJob / Video /
SourceKeyword are pydantic models used at API boundaries.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


Platform = Literal["douyin", "bilibili", "kuaishou", "xiaohongshu"]

MiningStatus = Literal[
    "pending", "running", "done", "partial_done",
    "failed", "cancelled", "interrupted",
]

PlatformPhase = Literal[
    "queued", "launching", "logging_in",
    "scrolling", "done", "failed",
    "needs_login", "risk_control", "cancelled",
    # v0.5.6: 撞 captcha 时不再立刻 bail (risk_control)，先停在浏览器
    # 里 poll 等用户手动解。这个 phase 期间 job.status 保持 "running"，
    # 前端能看到任务"等待验证"的中间态。解完回 scrolling；超时才 bail。
    "captcha_waiting",
    # v0.8: 预筛 pass — search 收齐后对候选视频抓首页评论做品牌词计数；
    # 同一 pass 里顺带识别「评论精选后才可见」的视频并排除（没填品牌词时
    # 只跑这一项的轻量探测，note 为「检查评论精选」）。
    "prefilter",
]


@dataclass
class VideoCard:
    """One scraped search-result entry, before it lands in SQLite."""
    platform: Platform
    platform_video_id: str
    url: str
    title: str = ""
    author_name: str = ""
    author_id: str = ""
    cover_url: str = ""
    duration_sec: int | None = None
    play_count: int | None = None
    like_count: int | None = None
    published_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    rank_in_search: int = 0  # 1-based, filled by adapter


@dataclass
class ProgressUpdate:
    platform: Platform
    phase: PlatformPhase
    got: int = 0
    target: int = 0
    note: str = ""


@dataclass
class SearchOutcome:
    platform: Platform
    status: Literal["done", "failed", "needs_login", "risk_control", "cancelled"]
    cards_emitted: int
    error_message: str = ""


class MiningJob(BaseModel):
    id: int | None = None
    keyword: str
    platforms: list[Platform] = Field(default_factory=lambda: ["douyin", "bilibili", "kuaishou"])
    target_per_platform: int = 50
    brand_keywords: list[str] = Field(default_factory=list)
    status: MiningStatus = "pending"
    progress: dict[str, dict[str, Any]] = Field(default_factory=dict)
    error_message: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Video(BaseModel):
    id: int
    platform: Platform
    platform_video_id: str
    url: str
    title: str = ""
    author_name: str = ""
    author_id: str = ""
    cover_url: str = ""
    duration_sec: int | None = None
    play_count: int | None = None
    like_count: int | None = None
    published_at: str | None = None
    excluded: bool = False
    already_commented: bool = False
    commented_source: str | None = None
    commented_at: str | None = None
    first_seen_at: datetime
    source_keywords: list[str] = Field(default_factory=list)  # joined from video_source_keywords


# ── 搜索筛选（按平台分组，UI 只展示各平台真实支持的档位）───────────────
# 存进 mining_jobs.filters_json（v13），adapter.search(filters=...) 各取
# 自己那份。值全部用平台原生参数格式，adapter 侧尽量零转换。

class DouyinFilters(BaseModel):
    """抖音网页搜索 URL 参数。publish_time 只有档位：0=不限 1=一天内
    7=一周内 182=半年内；sort_type：0=综合 1=最多点赞 2=最新发布。
    content_types 含 "note" 时改走综合搜索并按 aweme 结构后过滤图文。"""
    publish_time: Literal["0", "1", "7", "182"] = "0"
    sort_type: Literal["0", "1", "2"] = "0"
    content_types: list[Literal["video", "note"]] = Field(
        default_factory=lambda: ["video"]
    )


class BilibiliFilters(BaseModel):
    """B 站 search/type 直连参数。order：totalrank=综合 click=最多点击
    pubdate=最新发布 dm=最多弹幕 stow=最多收藏；时间为任意日期区间
    （YYYY-MM-DD，adapter 转 pubtime_begin_s / pubtime_end_s 秒级时间戳）。"""
    order: Literal["totalrank", "click", "pubdate", "dm", "stow"] = "totalrank"
    time_begin: str | None = None
    time_end: str | None = None


class KuaishouFilters(BaseModel):
    """快手 visionSearchPhoto 无服务端时间参数 —— 日期区间在 adapter 内
    按 published_at 本地后过滤（不计入 emitted，自动翻页补偿产出）。"""
    time_begin: str | None = None
    time_end: str | None = None


class XiaohongshuFilters(BaseModel):
    """小红书搜索(TikHub ``app_v2/search_notes``)筛选 —— 全部服务端下推。
    sort_type:general=综合 time_descending=最新 popularity_descending=最多点赞
    comment_descending=最多评论 collect_descending=最多收藏;
    note_type:all=不限 video=视频笔记 image=图文笔记(adapter 转成接口的中文档位);
    time_filter 档位与抖音同形:0=不限 1=一天内 7=一周内 182=半年内。"""
    sort_type: Literal[
        "general", "time_descending", "popularity_descending",
        "comment_descending", "collect_descending",
    ] = "general"
    note_type: Literal["all", "video", "image"] = "all"
    time_filter: Literal["0", "1", "7", "182"] = "0"


class SearchFilters(BaseModel):
    douyin: DouyinFilters = Field(default_factory=DouyinFilters)
    bilibili: BilibiliFilters = Field(default_factory=BilibiliFilters)
    kuaishou: KuaishouFilters = Field(default_factory=KuaishouFilters)
    xiaohongshu: XiaohongshuFilters = Field(default_factory=XiaohongshuFilters)


class StartJobRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    platforms: list[Platform] = Field(
        default_factory=lambda: ["douyin", "bilibili", "kuaishou"],
        min_length=1, max_length=4,
    )
    target_per_platform: int = Field(default=50, ge=10, le=200)
    brand_keywords: list[str] = Field(default_factory=list)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator("platforms", mode="before")
    @classmethod
    def _dedupe_platforms(cls, v: Any) -> Any:
        """C1: 去重必须在 min_length/max_length 之前生效——否则重复的平台名
        （如恶意/误传 ["douyin"]*500）会先被塞进一个巨大的原始列表，逐条打
        TikHub 付费搜索请求，是一个现成的计费放大器。dict.fromkeys 保序去重，
        非 list 输入原样透传交给下一步的类型校验去报错。"""
        if isinstance(v, list):
            return list(dict.fromkeys(v))
        return v
