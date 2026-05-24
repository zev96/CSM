"""Pydantic / dataclass models for the mining module.

VideoCard is the adapter→runner DTO (mutable dataclass — easier to fill in
incrementally as we parse a search result card). MiningJob / Video /
SourceKeyword are pydantic models used at API boundaries.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


Platform = Literal["douyin", "bilibili", "kuaishou"]

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


class StartJobRequest(BaseModel):
    keyword: str = Field(min_length=1, max_length=80)
    platforms: list[Platform] = Field(default_factory=lambda: ["douyin", "bilibili", "kuaishou"])
    target_per_platform: int = Field(default=50, ge=10, le=200)
