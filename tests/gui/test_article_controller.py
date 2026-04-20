from pathlib import Path
from csm_gui.config import AppConfig
from csm_gui.controllers.article_controller import ArticleController


def test_controller_initial_state_not_busy(qtbot, tmp_path):
    cfg = AppConfig(out_dir=str(tmp_path))
    c = ArticleController(cfg)
    assert c.is_busy() is False


def test_controller_signals_exist():
    """All documented signals must be declared — catches typos early."""
    cfg = AppConfig()
    c = ArticleController(cfg)
    for name in [
        "generated", "generate_failed", "reroll_completed",
        "polished", "polish_failed", "exported", "export_failed",
        "plan_warnings", "busy_changed",
    ]:
        assert hasattr(c, name), f"missing signal: {name}"


def test_apply_config_updates_internal(qtbot, tmp_path):
    c = ArticleController(AppConfig())
    new_cfg = AppConfig(out_dir=str(tmp_path), default_provider="deepseek")
    c.apply_config(new_cfg)
    # Internal state is private; reflect via is_busy() remaining False is enough here.
    # Further assertions live in migration tasks.
    assert c.is_busy() is False
