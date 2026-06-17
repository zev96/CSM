"""Tests for xhs_ai_service —— AI 生成整篇 + 润色正文（P3）.

Mock 策略同 mining：recording fake client + monkeypatch build_client；
503 分支不打 patch，让真 build_client 抛 LLMConfigError。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from csm_sidecar.services import config_service, xhs_ai_service
from csm_sidecar.services.llm_factory import LLMConfigError


class _RecordingClient:
    def __init__(self, response: str = ""):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.response


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _RecordingClient:
    client = _RecordingClient()
    monkeypatch.setattr(
        xhs_ai_service.llm_factory, "build_client", lambda **kw: client,
    )
    return client


# ── _parse_generated ────────────────────────────────────────────────────
def test_parse_generated_valid_json():
    out = xhs_ai_service._parse_generated(
        '{"title": "标题", "body": "正文", "topics": ["a", "b"]}'
    )
    assert out == {"title": "标题", "body": "正文", "topics": ["a", "b"]}


def test_parse_generated_strips_code_fence():
    out = xhs_ai_service._parse_generated(
        '```json\n{"title": "T", "body": "B", "topics": ["x"]}\n```'
    )
    assert out["title"] == "T"
    assert out["topics"] == ["x"]


def test_parse_generated_non_json_falls_back_to_body():
    out = xhs_ai_service._parse_generated("这不是 JSON，只是一段文字")
    assert out == {"title": "", "body": "这不是 JSON，只是一段文字", "topics": []}


def test_parse_generated_filters_non_string_topics():
    out = xhs_ai_service._parse_generated(
        '{"title": "T", "body": "B", "topics": ["ok", 123, null]}'
    )
    assert out["topics"] == ["ok"]


def test_parse_generated_missing_fields_default_empty():
    out = xhs_ai_service._parse_generated('{"title": "只有标题"}')
    assert out == {"title": "只有标题", "body": "", "topics": []}


def test_parse_generated_filters_empty_topics():
    out = xhs_ai_service._parse_generated(
        '{"title": "T", "body": "B", "topics": ["ok", "", "  ", "yes"]}'
    )
    assert out["topics"] == ["ok", "yes"]


def test_parse_generated_extracts_json_with_preamble():
    out = xhs_ai_service._parse_generated(
        '好的，这是你的笔记：\n{"title": "T", "body": "B", "topics": ["x"]}'
    )
    assert out["title"] == "T"
    assert out["body"] == "B"
    assert out["topics"] == ["x"]


# ── generate_note ─────────────────────────────────────────────────────────
def test_generate_note_returns_parsed_dict(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = '{"title": "平价护肤", "body": "正文内容", "topics": ["护肤", "学生党"]}'
    out = xhs_ai_service.generate_note("学生党平价护肤")
    assert out["title"] == "平价护肤"
    assert out["topics"] == ["护肤", "学生党"]
    assert "学生党平价护肤" in fake_client.calls[0]["user"]


def test_generate_note_non_json_fallback(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = "模型没按 JSON 输出，直接给了一段正文"
    out = xhs_ai_service.generate_note("随便")
    assert out["title"] == ""
    assert out["body"] == "模型没按 JSON 输出，直接给了一段正文"
    assert out["topics"] == []


def test_generate_note_raises_when_no_provider(settings_path: Path):
    with pytest.raises(LLMConfigError):
        xhs_ai_service.generate_note("主题")


# ── polish_note ─────────────────────────────────────────────────────────
def test_polish_note_returns_stripped(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    fake_client.response = "  润色后的小红书风正文  "
    out = xhs_ai_service.polish_note("朴素正文")
    assert out == "润色后的小红书风正文"
    assert fake_client.calls[0]["user"] == "朴素正文"


def test_polish_note_empty_returns_empty_without_llm(settings_path: Path, fake_client: _RecordingClient):
    config_service.patch({"default_provider": "mock"})
    out = xhs_ai_service.polish_note("   ")
    assert out == ""
    assert fake_client.calls == []


def test_polish_note_raises_when_no_provider(settings_path: Path):
    with pytest.raises(LLMConfigError):
        xhs_ai_service.polish_note("正文")
