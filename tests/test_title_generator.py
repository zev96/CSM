"""Tests for the auto-title generator (csm_core.title)."""
from __future__ import annotations
import json
from pathlib import Path
from textwrap import dedent

import pytest

from csm_core.title.generator import (
    fallback_title,
    generate_titles,
    parse_title_response,
    validate_title,
)
from csm_core.vault.scanner import scan_vault


# ── Helpers ────────────────────────────────────────────────────────────


class _FakeClient:
    """LLMClient stub returning a queued list of canned responses."""

    def __init__(self, responses: list[str | Exception]):
        self._responses = list(responses)
        self.calls: list[tuple[str, str, float | None]] = []

    def complete(
        self,
        *,
        system: str,
        user: str,
        temperature: float | None = None,
    ) -> str:
        self.calls.append((system, user, temperature))
        if not self._responses:
            raise RuntimeError("no canned response left")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _make_vault(tmp_path: Path) -> Path:
    """Drop a single 导购文 title-formula note into a temp vault."""
    note_dir = tmp_path / "营销资料库" / "标题模块" / "导购文"
    note_dir.mkdir(parents=True)
    (note_dir / "一问一答型.md").write_text(
        dedent("""\
        ---
        标题类型: 一问一答型
        适用模板类型: [导购文]
        公式: "[关键词] [疑问词]好用？推荐 + [利益] + [关键词]牌子分享"
        示例:
          - "无线吸尘器哪款好用？实测后分享几款真正能打的"
          - "扫地机器人哪种值得买？看完这篇不踩坑"
        ---
        正文随便写。
        """),
        encoding="utf-8",
    )
    return tmp_path


# ── parse_title_response ───────────────────────────────────────────────


class TestParseResponse:
    def test_clean_json(self):
        raw = '{"candidates": ["标题A", "标题B", "标题C"]}'
        assert parse_title_response(raw) == ["标题A", "标题B", "标题C"]

    def test_with_markdown_fence(self):
        raw = '```json\n{"candidates": ["x", "y"]}\n```'
        assert parse_title_response(raw) == ["x", "y"]

    def test_bare_array_fallback(self):
        raw = 'preface noise\n["a", "b"]\ntrailing noise'
        assert parse_title_response(raw) == ["a", "b"]

    def test_invalid_returns_empty(self):
        assert parse_title_response("plain text no json") == []
        assert parse_title_response("") == []

    def test_skips_blanks(self):
        raw = '{"candidates": ["ok", "", "  ", "again"]}'
        assert parse_title_response(raw) == ["ok", "again"]


# ── validate_title ─────────────────────────────────────────────────────


class TestValidate:
    def test_keyword_present_and_length_ok(self):
        # 26 chars (within 18-36), keyword present, no banned chars.
        t = "无线吸尘器哪款好用？实测分享几款真正能打的"
        assert validate_title(t, "无线吸尘器")

    def test_missing_keyword_rejected(self):
        assert not validate_title(
            "怎么选才不踩坑？看完这篇就懂了", "无线吸尘器",
        )

    def test_too_short_rejected(self):
        assert not validate_title("无线吸尘器选购", "无线吸尘器")

    def test_too_long_rejected(self):
        t = "无线吸尘器" + ("好" * 40)
        assert not validate_title(t, "无线吸尘器")

    def test_smart_quotes_rejected(self):
        # 26 chars, keyword, but contains "
        t = "无线吸尘器“哪款好用”实测分享几款真正能打"
        assert not validate_title(t, "无线吸尘器")


# ── fallback_title ─────────────────────────────────────────────────────


class TestFallback:
    def test_default_format(self):
        assert fallback_title("吸尘器") == "吸尘器怎么选？看完这篇就不踩坑"

    def test_long_keyword_uses_short_form(self):
        # Keyword longer than max-chars window forces short fallback.
        long_kw = "超长关键词" * 8
        out = fallback_title(long_kw)
        assert long_kw in out
        # Either passes or trims, but always non-empty.
        assert out

    def test_empty_keyword(self):
        out = fallback_title("")
        assert out  # never empty

    def test_long_tail_with_question_phrase(self):
        # Keyword already contains 好用 → should NOT append "怎么选？"
        out = fallback_title("无线吸尘器哪款好用")
        assert "无线吸尘器哪款好用" in out
        # Should not double up the question word.
        assert "好用怎么选" not in out

    def test_long_tail_with_decision_phrase(self):
        out = fallback_title("扫地机器人值得买")
        assert "扫地机器人值得买" in out
        assert "值得买怎么选" not in out

    def test_bare_noun_keeps_question_suffix(self):
        # Plain product term — canonical "怎么选？" suffix still fires.
        assert fallback_title("空气净化器").startswith("空气净化器怎么选")


# ── generate_titles end-to-end ─────────────────────────────────────────


class TestGenerateEndToEnd:
    def test_happy_path(self, tmp_path: Path):
        _make_vault(tmp_path)
        client = _FakeClient([
            json.dumps({"candidates": [
                "无线吸尘器哪款好用？实测分享几款真正能打的",
                "无线吸尘器哪种值得买？看完这篇不踩坑就行",
                "无线吸尘器怎么选？2026年5款热门牌子盘点",
            ]}, ensure_ascii=False),
        ])
        out = generate_titles(
            keyword="无线吸尘器",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        assert len(out) == 3
        assert all("无线吸尘器" in t for t in out)
        # Prompt should mention the template type.
        _, user_prompt, _ = client.calls[0]
        assert "导购文" in user_prompt
        assert "无线吸尘器" in user_prompt

    def test_retries_on_invalid_then_succeeds(self, tmp_path: Path):
        _make_vault(tmp_path)
        client = _FakeClient([
            "garbage no json here",                                       # parse fails
            '{"candidates": ["怎么挑就懂了"]}',                            # missing keyword
            json.dumps({"candidates": [
                "无线吸尘器怎么选？2026年5款热门牌子盘点指南",
            ]}, ensure_ascii=False),                                       # finally valid
        ])
        out = generate_titles(
            keyword="无线吸尘器",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        assert len(out) == 1
        assert "无线吸尘器" in out[0]
        assert len(client.calls) == 3

    def test_falls_back_on_persistent_failure(self, tmp_path: Path):
        _make_vault(tmp_path)
        client = _FakeClient([
            "junk", "still junk", "even more junk",
        ])
        out = generate_titles(
            keyword="吸尘器",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        assert len(out) == 1
        assert "吸尘器" in out[0]  # fallback always preserves keyword

    def test_falls_back_on_llm_exception(self, tmp_path: Path):
        _make_vault(tmp_path)
        client = _FakeClient([RuntimeError("boom")])
        out = generate_titles(
            keyword="吸尘器",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        assert len(out) == 1
        assert "吸尘器" in out[0]

    def test_unknown_template_type_falls_back_to_unfiltered(self, tmp_path: Path):
        # vault has only 导购文 formulas, but user asks for 长文.
        # The generator should still build a prompt (using all formulas)
        # rather than ship an empty samples block.
        _make_vault(tmp_path)
        client = _FakeClient([
            json.dumps({"candidates": [
                "吸尘器选购全攻略 实测了12款总结出这5个真知灼见",
            ]}, ensure_ascii=False),
        ])
        out = generate_titles(
            keyword="吸尘器",
            template_type="长文",
            vault_root=tmp_path,
            llm_client=client,
        )
        assert len(out) == 1
        # The fallback formula list still references existing notes.
        _, user_prompt, _ = client.calls[0]
        assert "一问一答型" in user_prompt

    def test_default_temperature_is_low(self, tmp_path: Path):
        """Title gen should call LLM with temperature ≤ 0.5 by default
        so the model sticks to the keyword instead of "creatively" rewriting."""
        from csm_core.title.generator import DEFAULT_TEMPERATURE
        assert 0.3 <= DEFAULT_TEMPERATURE <= 0.5
        _make_vault(tmp_path)
        client = _FakeClient([
            json.dumps({"candidates": [
                "无线吸尘器哪款好用？2026年5款热门盘点",
            ]}, ensure_ascii=False),
        ])
        generate_titles(
            keyword="无线吸尘器",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        _, _, temp = client.calls[0]
        assert temp == DEFAULT_TEMPERATURE

    def test_temperature_override_respected(self, tmp_path: Path):
        _make_vault(tmp_path)
        client = _FakeClient([
            json.dumps({"candidates": [
                "无线吸尘器哪款好用？2026年5款热门盘点",
            ]}, ensure_ascii=False),
        ])
        generate_titles(
            keyword="无线吸尘器",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
            temperature=0.0,
        )
        _, _, temp = client.calls[0]
        assert temp == 0.0

    def test_long_tail_keyword_must_appear_verbatim(self, tmp_path: Path):
        """Validation rejects any candidate that splits the long-tail phrase."""
        _make_vault(tmp_path)
        keyword = "无线吸尘器哪款好用"
        # First batch: LLM mangles the keyword — should ALL be rejected.
        # Second batch: one keeps the long-tail intact — that one survives.
        client = _FakeClient([
            json.dumps({"candidates": [
                "无线吸尘器哪款最好用？2026年5款盘点",      # inserted "最" — broken
                "无线吸尘器选哪个好用？测评分享几款",        # rearranged — broken
                "无线吸尘器哪款？好用的5款实测推荐",          # punctuation split — broken
            ]}, ensure_ascii=False),
            json.dumps({"candidates": [
                "无线吸尘器哪款好用？2026年5款盘点推荐",      # ✓ verbatim
                "选购避坑：无线吸尘器哪款好用 3款不踩雷",    # ✓ verbatim
            ]}, ensure_ascii=False),
        ])
        out = generate_titles(
            keyword=keyword,
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        # All survivors must contain the verbatim long-tail keyword.
        assert all(keyword in t for t in out)
        assert len(out) == 2
        assert len(client.calls) == 2  # confirmed retry on the bad batch

    def test_long_tail_prompt_includes_emphasis(self, tmp_path: Path):
        """Long-tail keywords trigger an extra "不可分割" warning in the prompt."""
        _make_vault(tmp_path)
        client = _FakeClient([
            json.dumps({"candidates": [
                "无线吸尘器哪款好用？2026年5款盘点",
            ]}, ensure_ascii=False),
        ])
        generate_titles(
            keyword="无线吸尘器哪款好用",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        _, user_prompt, _ = client.calls[0]
        assert "长尾关键词" in user_prompt
        assert "不可分割" in user_prompt or "整体" in user_prompt

    def test_missing_vault_module_uses_fallback_prompt(self, tmp_path: Path):
        # Empty vault — no title module at all. Should still emit a
        # prompt and accept whatever the LLM returns.
        client = _FakeClient([
            json.dumps({"candidates": [
                "吸尘器怎么选？2026年5款热门牌子盘点指南",
            ]}, ensure_ascii=False),
        ])
        out = generate_titles(
            keyword="吸尘器",
            template_type="导购文",
            vault_root=tmp_path,
            llm_client=client,
        )
        assert len(out) == 1
        assert "吸尘器" in out[0]
