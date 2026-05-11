"""Export wrapper. Adds the optional dedup-report appendix the prototype
asks for in the export dialog (toggle '附带查重报告')."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from csm_core.export.markdown import export_article

from . import config_service

ExportFormat = Literal["markdown", "docx"]


def export(
    *,
    keyword: str,
    final_text: str,
    fmt: ExportFormat = "markdown",
    out_dir: str | None = None,
    include_dedup_report: bool = False,
) -> dict[str, Any]:
    """Write the article to disk and return the export descriptor.

    ``include_dedup_report`` runs a fresh dedup check and appends the
    report markdown to the article before writing. The dedup index must
    have been built (POST /api/dedup/build-index) — if not, the appendix
    is silently skipped with a warning so export still succeeds.
    """
    cfg = config_service.load()
    candidate = out_dir or cfg.out_dir
    if not candidate:
        raise ValueError("AppConfig.out_dir is unset and no out_dir override given")
    # Path("") is truthy but resolves to '.' — explicit string check above
    # catches the empty case before we silently write to cwd.
    target_dir = Path(candidate)
    target_dir.mkdir(parents=True, exist_ok=True)

    body = final_text
    if include_dedup_report:
        try:
            from csm_core.dedup.analyzer import DedupAnalyzer  # local import: heavy
            analyzer = DedupAnalyzer()
            # dedup analyze() requires a pre-built index; if absent, skip.
            report = analyzer.analyze(final_text, kind="history")
            body = body + "\n\n---\n\n## 查重报告\n\n" + _format_report(report)
        except Exception:
            # Don't fail the export over an optional appendix.
            pass

    paths = export_article(
        out_dir=target_dir,
        keyword=keyword,
        final_text=body,
        fmt=fmt,
    )
    return paths


def _format_report(report: Any) -> str:
    """Render a DuplicateReport as markdown lines for the export appendix."""
    out: list[str] = []
    out.append(f"- 全文重复率：**{getattr(report, 'duplicate_ratio', 0):.1%}**")
    out.append(f"- 全文长度：{getattr(report, 'text_length', 0)} 字")
    matches = getattr(report, "top_matches", []) or []
    if matches:
        out.append("\n### Top 命中来源\n")
        for m in matches[:3]:
            title = getattr(m, "title", "") or getattr(m, "path", "")
            ratio = getattr(m, "ratio", 0)
            out.append(f"- {title}（重叠率 {ratio:.1%}）")
    return "\n".join(out)
