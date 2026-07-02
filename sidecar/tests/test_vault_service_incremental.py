from pathlib import Path

import pytest

from csm_core.config import AppConfig
import csm_core.vault.index_cache as index_cache
from csm_sidecar.services import vault_service

GOOD = "---\n素材类型: 科普\n---\n\n正文①\n"


@pytest.fixture(autouse=True)
def _reset():
    vault_service.invalidate()
    yield
    vault_service.invalidate()


@pytest.fixture
def patch_cfg(monkeypatch):
    def _set(**kw):
        monkeypatch.setattr(
            vault_service.config_service, "load", lambda: AppConfig(**kw))
    return _set


def _vault(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text(GOOD, encoding="utf-8")
    return tmp_path


def _count_parses(monkeypatch):
    """双 spy：增量路径引用 index_cache.parse_one，全量路径（scan_vault）
    引用 scanner 模块自己的 parse_one —— 两处都打点才能数全。"""
    calls = []
    import csm_core.vault.scanner as scanner
    real = scanner.parse_one

    def spy(path):
        calls.append(path.name)
        return real(path)

    monkeypatch.setattr(index_cache, "parse_one", spy)
    monkeypatch.setattr(scanner, "parse_one", spy)
    return calls


def test_config_default_on():
    assert AppConfig.model_validate({}).vault_incremental is True


def test_get_incremental_and_cached(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)
    idx1 = vault_service.get(root)
    assert list(idx1.by_id) == ["a"]
    assert vault_service.cached() is idx1
    calls = _count_parses(monkeypatch)
    vault_service.get(root)
    assert calls == []                      # 第二次 get 零重解析


def test_get_config_off_falls_back_to_full(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=False)
    root = _vault(tmp_path)
    vault_service.get(root)
    calls = _count_parses(monkeypatch)
    idx = vault_service.get(root)
    # 配置关 → 每次 get 都走 scan()（scan_vault 全量），必重解析
    assert calls == ["a.md"]
    assert list(idx.by_id) == ["a"]


def test_get_exception_falls_back_to_full(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)

    def boom(_root):
        raise RuntimeError("stat 炸了")

    monkeypatch.setattr(vault_service._indexer, "refresh", boom)
    idx = vault_service.get(root)           # 不抛，回退全量；RLock 保证重入不死锁
    assert list(idx.by_id) == ["a"]


def test_scan_forces_full(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)
    vault_service.get(root)
    calls = _count_parses(monkeypatch)
    vault_service.scan(root)
    assert calls == ["a.md"]                # 强制全量重解析


def test_invalidate_resets_indexer(tmp_path, monkeypatch, patch_cfg):
    patch_cfg(vault_incremental=True)
    root = _vault(tmp_path)
    vault_service.get(root)
    vault_service.invalidate()
    assert vault_service.cached() is None
    calls = _count_parses(monkeypatch)
    vault_service.get(root)
    assert calls == ["a.md"]                # reset 后全量
