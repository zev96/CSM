"""One-shot migration: fold template.system_prompt_default + template.seo_defaults
into a standalone .md skill file and strip those fields from the template JSON.

Usage:
    python -m scripts.migrate_template_to_skill <templates_dir> <skill_dir>

Idempotent: re-running on an already-migrated template is a no-op. The original
JSON is backed up as <file>.bak before rewriting.
"""
from __future__ import annotations
import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LEGACY_FIELDS = ("version", "system_prompt_default", "seo_defaults")


def _render_skill_md(tid: str, sys_prompt: str, seo: dict) -> str:
    """Build the markdown body for the migrated skill file."""
    parts: list[str] = []
    if sys_prompt.strip():
        parts.append(sys_prompt.strip())

    seo_lines: list[str] = ["## SEO 约束"]
    wc = seo.get("target_word_count") or [1500, 2000]
    kd = seo.get("keyword_density") or [5, 8]
    seo_lines.append(f"- 目标字数：{wc[0]}-{wc[1]} 字")
    seo_lines.append(f"- 主关键词密度：{kd[0]}-{kd[1]}%")
    seo_lines.append(f"- 语气风格：{seo.get('tone', '').strip() or '自然'}")
    if seo.get("force_h2"):
        seo_lines.append("- 必须使用 H2 (##) 段落标题分隔核心板块")
    long_tail = seo.get("long_tail_keywords") or []
    if long_tail:
        seo_lines.append(f"- 长尾关键词（自然嵌入）：{', '.join(long_tail)}")
    parts.append("\n".join(seo_lines))

    body = "\n\n".join(parts).rstrip() + "\n"
    header = f"# {tid} — 迁移自模板基础设置\n\n"
    return header + body


def migrate_file(tpl_path: Path, skill_dir: Path) -> Path | None:
    """Migrate one template file. Returns the path to the new skill .md, or
    None if the template had no legacy fields (already migrated / never had any)."""
    tpl_path = Path(tpl_path); skill_dir = Path(skill_dir)
    data = json.loads(tpl_path.read_text(encoding="utf-8"))

    if not any(k in data for k in LEGACY_FIELDS):
        logger.info("%s: no legacy fields, skipping", tpl_path.name)
        return None

    tid = data.get("id") or tpl_path.stem
    new_skill_id = f"{tid}-migrated"
    skill_path = skill_dir / f"{new_skill_id}.md"

    backup = tpl_path.with_suffix(tpl_path.suffix + ".bak")
    shutil.copy2(tpl_path, backup)

    skill_dir.mkdir(parents=True, exist_ok=True)
    body = _render_skill_md(
        tid=tid,
        sys_prompt=data.get("system_prompt_default", ""),
        seo=data.get("seo_defaults") or {},
    )
    skill_path.write_text(body, encoding="utf-8")

    cleaned = {k: v for k, v in data.items() if k not in LEGACY_FIELDS}
    cleaned["default_skill_id"] = new_skill_id
    tpl_path.write_text(
        json.dumps(cleaned, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("migrated %s -> %s", tpl_path.name, skill_path.name)
    return skill_path


def migrate_directory(tpl_dir: Path, skill_dir: Path) -> list[Path]:
    """Migrate every *.json directly under tpl_dir."""
    results: list[Path] = []
    for p in sorted(Path(tpl_dir).glob("*.json")):
        out = migrate_file(p, skill_dir)
        if out is not None:
            results.append(out)
    return results


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("templates_dir", type=Path)
    ap.add_argument("skill_dir", type=Path)
    args = ap.parse_args(argv)

    if not args.templates_dir.is_dir():
        print(f"error: {args.templates_dir} is not a directory", file=sys.stderr)
        return 2
    migrated = migrate_directory(args.templates_dir, args.skill_dir)
    print(f"migrated {len(migrated)} template(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
