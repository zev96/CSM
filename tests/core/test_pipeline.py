from pathlib import Path
from csm_core.pipeline import generate, GenerateRequest
from csm_core.llm.providers.mock import MockClient


def test_generate_runs_end_to_end(mini_vault_path: Path, tmp_path: Path):
    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    client = MockClient(response="# 洗稿后文章\n\n内容")
    req = GenerateRequest(
        keyword="宠物吸尘器推荐",
        vault_root=mini_vault_path,
        template_path=template_path,
        out_dir=tmp_path,
        llm_client=client,
        user_skill_prompt=None,
        seed=42,
        user_config={"brand_competitors": 2},
    )
    result = generate(req)
    assert Path(result.markdown_path).exists()
    assert Path(result.assembly_json_path).exists()
    assert "# 洗稿后文章" in Path(result.markdown_path).read_text(encoding="utf-8")
    assert len(client.calls) == 1
    assert "SEO" in client.calls[0]["system"]
