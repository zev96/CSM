from pathlib import Path
from click.testing import CliRunner
from csm_core.__main__ import cli


def test_cli_runs_with_mock_provider(mini_vault_path: Path, tmp_path: Path):
    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "宠物吸尘器推荐",
        "--template", str(template_path),
        "--vault", str(mini_vault_path),
        "--out", str(tmp_path),
        "--provider", "mock",
        "--mock-response", "# 测试输出",
        "--seed", "42",
    ])
    assert result.exit_code == 0, result.output
    md_files = list(tmp_path.glob("*.md"))
    assert len(md_files) == 1
    assert md_files[0].read_text(encoding="utf-8") == "# 测试输出"
