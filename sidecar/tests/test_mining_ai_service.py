"""Tests for ``mining_ai_service`` — AI 速览 + AI 建议.

Mock provider strategy: set ``default_provider="mock"`` on the per-test
config, then monkeypatch ``llm_factory.build_client`` to a recording
fake so we can assert on the rendered prompts the service passed in.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_core.mining import storage as mining_storage
from csm_core.monitor import storage as monitor_storage
from csm_sidecar.services import config_service, mining_ai_service
from csm_sidecar.services.llm_factory import LLMConfigError


# ── Recording fake LLM client ───────────────────────────────────────────
class _RecordingClient:
    """Mimics LLMClient protocol; records every complete() call."""

    def __init__(self, response: str = "fake summary 60-100 chars 中文"):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    """Replace llm_factory.build_client with a RecordingClient factory."""
    client = _RecordingClient()
    monkeypatch.setattr(
        mining_ai_service.llm_factory,
        "build_client",
        lambda **kw: client,
    )
    return client


def _insert_video(
    *, video_id: int = 1, title: str = "评测视频", author: str = "UP-A",
    platform: str = "bilibili", duration: int = 120, play: int = 5000,
    ai_summary: str | None = None,
) -> int:
    conn = monitor_storage.get_conn()
    conn.execute(
        "INSERT INTO videos(id, platform, platform_video_id, url, title, "
        "author_name, duration_sec, play_count, ai_summary) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (video_id, platform, f"BV-{video_id}", f"https://example/{video_id}",
         title, author, duration, play, ai_summary),
    )
    return video_id


# ── _render helper ──────────────────────────────────────────────────────
def test_render_missing_key_returns_empty_string():
    """spec §4.3: typo in template MUST NOT raise — render empty instead."""
    out = mining_ai_service._render("title={title} typo={titel}", {"title": "X"})
    assert out == "title=X typo="


def test_render_with_all_keys_works():
    out = mining_ai_service._render(
        "p={platform} t={title} a={author}",
        {"platform": "bilibili", "title": "T", "author": "A"},
    )
    assert out == "p=bilibili t=T a=A"


# ── _resolve_prompt helper ──────────────────────────────────────────────
def test_resolve_prompt_empty_returns_defaults():
    sys_, usr_ = mining_ai_service._resolve_prompt("", "default-sys", "default-usr")
    assert sys_ == "default-sys"
    assert usr_ == "default-usr"


def test_resolve_prompt_whitespace_returns_defaults():
    sys_, usr_ = mining_ai_service._resolve_prompt("   \n  ", "default-sys", "default-usr")
    assert sys_ == "default-sys"
    assert usr_ == "default-usr"


def test_resolve_prompt_no_separator_replaces_system_only():
    sys_, usr_ = mining_ai_service._resolve_prompt("custom system", "def-sys", "def-usr")
    assert sys_ == "custom system"
    assert usr_ == "def-usr"


def test_resolve_prompt_with_separator_splits_both():
    sys_, usr_ = mining_ai_service._resolve_prompt(
        "custom sys\n---user---\ncustom usr {title}",
        "def-sys", "def-usr",
    )
    assert sys_ == "custom sys"
    assert usr_ == "custom usr {title}"


# ── summarize_video ─────────────────────────────────────────────────────
def test_summarize_video_persists_and_returns(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()

    out = mining_ai_service.summarize_video(vid)

    assert out  # non-empty
    assert len(fake_client.calls) == 1
    # Default system prompt was used (contains 中文短视频 marker)
    call = fake_client.calls[0]
    assert "中文短视频" in call["system"]
    # Default user template rendered with our row
    assert "评测视频" in call["user"]
    assert "UP-A" in call["user"]
    assert "bilibili" in call["user"]

    # set_ai_summary persisted
    conn = monitor_storage.get_conn()
    row = conn.execute("SELECT ai_summary FROM videos WHERE id=?", (vid,)).fetchone()
    assert row["ai_summary"] == out


def test_summarize_video_cached_skips_llm(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video(ai_summary="已有摘要 cached")

    out = mining_ai_service.summarize_video(vid, force=False)

    assert out == "已有摘要 cached"
    assert fake_client.calls == []  # no LLM call


def test_summarize_video_force_regenerates(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video(ai_summary="老摘要")
    fake_client.response = "新摘要 fresh"

    out = mining_ai_service.summarize_video(vid, force=True)

    assert out == "新摘要 fresh"
    assert len(fake_client.calls) == 1


def test_summarize_video_custom_prompt_used(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    """Custom prompt in AppConfig.mining_summary_prompt overrides default."""
    config_service.patch({
        "default_provider": "mock",
        "mining_summary_prompt": "custom-instructions {title}",
    })
    vid = _insert_video(title="我的视频")

    mining_ai_service.summarize_video(vid)

    call = fake_client.calls[0]
    # custom is single-segment -> goes into system, with {title} rendered
    assert call["system"] == "custom-instructions 我的视频"
    # default user template still in effect
    assert "平台=" in call["user"]


def test_summarize_video_custom_with_user_separator(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({
        "default_provider": "mock",
        "mining_summary_prompt": "sys part\n---user---\nuser part {author}",
    })
    vid = _insert_video(author="某人")

    mining_ai_service.summarize_video(vid)

    call = fake_client.calls[0]
    assert call["system"] == "sys part"
    assert call["user"] == "user part 某人"


def test_summarize_video_raises_when_no_provider(
    settings_path: Path, monitor_db: Path,
):
    """LLMConfigError propagates when default_provider is None."""
    # Don't patch — default config has default_provider=None
    vid = _insert_video()

    with pytest.raises(LLMConfigError):
        mining_ai_service.summarize_video(vid)


def test_summarize_video_missing_video_raises(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    with pytest.raises(LookupError):
        mining_ai_service.summarize_video(99999)


# ── suggest_comment ─────────────────────────────────────────────────────
def test_suggest_comment_does_not_persist(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()
    fake_client.response = "建议草稿 ≤80 字"

    out = mining_ai_service.suggest_comment(vid, tier=2, previous_tiers=["第一层文本"])

    assert out == "建议草稿 ≤80 字"
    # NOT written to ai_summary
    conn = monitor_storage.get_conn()
    row = conn.execute("SELECT ai_summary FROM videos WHERE id=?", (vid,)).fetchone()
    assert row["ai_summary"] is None


def test_suggest_comment_renders_previous_block(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({"default_provider": "mock"})
    vid = _insert_video()

    mining_ai_service.suggest_comment(
        vid, tier=3, previous_tiers=["第一层 hi", "第二层 yo"],
    )

    call = fake_client.calls[0]
    assert "第 1 层: 第一层 hi" in call["user"]
    assert "第 2 层: 第二层 yo" in call["user"]
    assert "请写第 3 层" in call["user"]


def test_suggest_comment_raises_when_no_provider(
    settings_path: Path, monitor_db: Path,
):
    vid = _insert_video()
    with pytest.raises(LLMConfigError):
        mining_ai_service.suggest_comment(vid, tier=1, previous_tiers=[])


def test_suggest_comment_custom_prompt_used(
    settings_path: Path, monitor_db: Path, fake_client: _RecordingClient,
):
    config_service.patch({
        "default_provider": "mock",
        "mining_suggest_prompt": "X {tier} Y {previous_block}",
    })
    vid = _insert_video()

    mining_ai_service.suggest_comment(vid, tier=2, previous_tiers=["a", "b"])

    call = fake_client.calls[0]
    # Single-segment custom -> system replaced, user default stays
    assert call["system"] == "X 2 Y 第 1 层: a\n第 2 层: b"
