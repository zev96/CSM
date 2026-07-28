from pathlib import Path
from unittest.mock import patch, MagicMock
from csm_core.pipeline import generate, GenerateRequest
from csm_core.llm.providers.mock import MockClient
from csm_core.assembler.plan import AssemblyPlan


def _make_req(tmp_path: Path, user_skill_prompt=None) -> GenerateRequest:
    template_path = Path(__file__).parent.parent.parent / "templates" / "daogou-changjing-renqun.json"
    client = MockClient(response="# 洗稿后文章\n\n内容")
    return GenerateRequest(
        keyword="宠物吸尘器推荐",
        vault_root=tmp_path / "vault",
        template_path=template_path,
        out_dir=tmp_path,
        llm_client=client,
        user_skill_prompt=user_skill_prompt,
        seed=42,
        user_config={"brand_competitors": 2},
    ), client


def _fake_plan() -> AssemblyPlan:
    plan = MagicMock(spec=AssemblyPlan)
    plan.keyword = "宠物吸尘器推荐"
    plan.warnings = []
    return plan


def test_generate_system_prompt_is_empty_when_no_skill(tmp_path: Path):
    """With user_skill_prompt=None the system layer is empty."""
    req, client = _make_req(tmp_path)
    fake_plan = _fake_plan()

    with patch("csm_core.pipeline.scan_vault"), \
         patch("csm_core.pipeline.build_brand_registry"), \
         patch("csm_core.pipeline.load_template"), \
         patch("csm_core.pipeline.assemble_plan", return_value=fake_plan), \
         patch("csm_core.pipeline.compose_draft", return_value="毛坯草稿内容"), \
         patch("csm_core.pipeline.export_article", return_value={
             # 现行契约是 document/format/title。这个桩原来返回早已废弃的
             # markdown/assembly_json，和同样读废弃键的 pipeline 互相对齐 ——
             # 两边一起错，测试反而是绿的，把 `python -m csm_core` 的 KeyError
             # 锁在了盲区里。
             "document": str(tmp_path / "out.md"),
             "format": "markdown",
             "title": "T",
         }):
        result = generate(req)

    # 返回值也要断言 —— 不然 pipeline 读错键这类问题测试永远看不见
    assert result.markdown_path == str(tmp_path / "out.md")
    assert len(client.calls) == 1
    # user_skill_prompt=None → system layer is empty string
    assert client.calls[0]["system"] == ""
    # keyword and draft appear in user message
    assert "宠物吸尘器推荐" in client.calls[0]["user"]
    assert "毛坯草稿内容" in client.calls[0]["user"]


def test_generate_user_skill_prompt_becomes_system_layer(tmp_path: Path):
    """When a skill prompt is supplied it becomes the LLM system message."""
    skill_text = "你是专业的内容改写专家，请按照以下规则润色。"
    req, client = _make_req(tmp_path, user_skill_prompt=skill_text)
    fake_plan = _fake_plan()

    with patch("csm_core.pipeline.scan_vault"), \
         patch("csm_core.pipeline.build_brand_registry"), \
         patch("csm_core.pipeline.load_template"), \
         patch("csm_core.pipeline.assemble_plan", return_value=fake_plan), \
         patch("csm_core.pipeline.compose_draft", return_value="毛坯草稿内容"), \
         patch("csm_core.pipeline.export_article", return_value={
             # 现行契约是 document/format/title。这个桩原来返回早已废弃的
             # markdown/assembly_json，和同样读废弃键的 pipeline 互相对齐 ——
             # 两边一起错，测试反而是绿的，把 `python -m csm_core` 的 KeyError
             # 锁在了盲区里。
             "document": str(tmp_path / "out.md"),
             "format": "markdown",
             "title": "T",
         }):
        result = generate(req)

    assert result.markdown_path == str(tmp_path / "out.md")
    assert len(client.calls) == 1
    assert client.calls[0]["system"] == skill_text
    assert "宠物吸尘器推荐" in client.calls[0]["user"]
