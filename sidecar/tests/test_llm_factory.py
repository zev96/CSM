"""Tests for build_client provider resolution."""
from __future__ import annotations

import pytest

from csm_sidecar.services import config_service
from csm_sidecar.services.llm_factory import LLMConfigError, build_client


def test_build_client_raises_when_default_provider_is_none(settings_path):
    """全新用户的 settings.json 里 default_provider = None — 必须显式拒绝，
    而不是悄悄走 mock 让用户拿到 'mock response' 占位结果。"""
    cfg = config_service.load()
    assert cfg.default_provider is None
    with pytest.raises(LLMConfigError, match="尚未选择默认 provider"):
        build_client()


def test_build_client_explicit_mock_still_works(settings_path):
    """显式选 mock（开发 / 测试场景）仍然合法，不受 None-拒绝逻辑影响。"""
    client = build_client(provider="mock")
    assert client.complete(system="", user="") == "mock response"
