"""CLI entry point: python -m csm_core 'keyword' --template ..."""
from __future__ import annotations
from pathlib import Path
import click
from .pipeline import generate, GenerateRequest
from .llm.client import make_client


@click.command()
@click.argument("keyword")
@click.option("--template", "template_path", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--vault", "vault_root", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--out", "out_dir", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--provider", default="mock", type=click.Choice(["mock", "anthropic", "deepseek"]))
@click.option("--api-key", default=None, help="API key for provider (or use env var)")
@click.option("--model", default=None, help="Model name override")
@click.option("--skill", "skill_path", default=None, type=click.Path(exists=True, path_type=Path))
@click.option("--seed", default=0, type=int)
@click.option("--mock-response", default="mock response", help="Response text for mock provider")
def cli(keyword, template_path, vault_root, out_dir, provider, api_key, model,
        skill_path, seed, mock_response):
    """Generate an SEO article from keyword + template."""
    client_kwargs = {}
    if provider == "mock":
        client_kwargs["response"] = mock_response
    else:
        if not api_key:
            import os
            api_key = os.environ.get(f"{provider.upper()}_API_KEY", "")
        client_kwargs["api_key"] = api_key
        if model:
            client_kwargs["model"] = model
    client = make_client(provider=provider, **client_kwargs)

    skill_prompt = None
    if skill_path:
        skill_prompt = Path(skill_path).read_text(encoding="utf-8")

    result = generate(GenerateRequest(
        keyword=keyword,
        vault_root=vault_root,
        template_path=template_path,
        out_dir=out_dir,
        llm_client=client,
        user_skill_prompt=skill_prompt,
        seed=seed,
    ))
    click.echo(f"Generated: {result.markdown_path}")
    click.echo(f"Snapshot : {result.assembly_json_path}")


if __name__ == "__main__":
    cli()
