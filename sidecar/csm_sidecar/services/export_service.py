"""Export wrapper. Adds the optional dedup-report appendix the prototype
asks for in the export dialog (toggle '附带查重报告'), plus a .md mirror
to ``AppConfig.dedup_history_dir`` so the history index always contains
parsable markdown regardless of the user's chosen export format."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import frontmatter

from csm_core.export.markdown import export_article, extract_title

from . import config_service

logger = logging.getLogger(__name__)

ExportFormat = Literal["markdown", "docx"]


def export(
    *,
    keyword: str,
    final_text: str,
    fmt: ExportFormat = "markdown",
    out_dir: str | None = None,
    include_dedup_report: bool = False,
    template_name: str | None = None,
) -> dict[str, Any]:
    """Write the article to disk and return the export descriptor.

    ``include_dedup_report`` runs a fresh dedup check and appends the
    report markdown to the article before writing. The dedup index must
    have been built (POST /api/dedup/build-index) — if not, the appendix
    is silently skipped with a warning so export still succeeds.

    Always mirrors a .md copy of ``final_text`` (without the dedup report
    appendix) to ``cfg.dedup_history_dir`` if configured. The mirror's
    frontmatter carries ``title / keyword / template / words /
    exported_at / source_format`` for downstream aggregation.
    """
    cfg = config_service.load()
    candidate = out_dir or cfg.out_dir
    if not candidate:
        raise ValueError("AppConfig.out_dir is unset and no out_dir override given")
    target_dir = Path(candidate)
    target_dir.mkdir(parents=True, exist_ok=True)

    body_for_export = final_text
    if include_dedup_report:
        try:
            from csm_core.dedup.analyzer import DedupAnalyzer  # local import: heavy
            analyzer = DedupAnalyzer()
            report = analyzer.analyze(final_text, kind="history")
            body_for_export = body_for_export + "\n\n---\n\n## 查重报告\n\n" + _format_report(report)
        except Exception:
            # User opted-in to dedup-on-export and we silently dropped it —
            # surface the reason in logs so we can diagnose, but keep the
            # export itself going. The article without a dedup appendix is
            # still strictly better than failing the whole export.
            logger.warning(
                "dedup report skipped on export: analyzer raised", exc_info=True,
            )

    paths = export_article(
        out_dir=target_dir,
        keyword=keyword,
        final_text=body_for_export,
        fmt=fmt,
    )

    mirror = _mirror_to_history(
        history_dir=cfg.dedup_history_dir,
        keyword=keyword,
        final_text=final_text,            # without dedup appendix
        fmt=fmt,
        template_name=template_name,
        primary_path=paths["document"],
    )
    paths["history_path"] = str(mirror) if mirror else None
    return paths


def _mirror_to_history(
    *,
    history_dir: str,
    keyword: str,
    final_text: str,
    fmt: ExportFormat,
    template_name: str | None,
    primary_path: str,
) -> Path | None:
    """Write a .md copy of ``final_text`` into ``history_dir``. Returns
    the resulting Path on success, None on any failure (logged, never
    raises — the primary export must not fail because of mirror trouble).
    """
    if not history_dir:
        return None
    target_dir = Path(history_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("history dir not writable, skipping mirror: %s", e)
        return None

    stem = Path(primary_path).stem
    target = _dedupe_name(target_dir / f"{stem}.md")

    post = frontmatter.Post(
        content=final_text,
        title=extract_title(final_text) or stem,
        keyword=keyword,
        template=template_name,
        words=_count_chars(final_text),
        exported_at=datetime.now().isoformat(timespec="seconds"),
        source_format=fmt,
    )
    try:
        target.write_text(frontmatter.dumps(post), encoding="utf-8")
        return target
    except OSError as e:
        logger.warning("history mirror write failed: %s", e)
        return None


def _dedupe_name(p: Path) -> Path:
    """Suffix ``-2``, ``-3``, ... until the filename is free."""
    if not p.exists():
        return p
    i = 2
    while True:
        candidate = p.with_name(f"{p.stem}-{i}{p.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


# Excluding whitespace + markdown punctuation matches what the legacy
# GUI 字数 panel showed and what aggregation_service uses.
_WS_OR_MD_PUNCT = re.compile(r"[\s\*#`>\-_]")


def _count_chars(text: str) -> int:
    return len(_WS_OR_MD_PUNCT.sub("", text or ""))


def _format_report(report: Any) -> str:
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
