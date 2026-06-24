"""Skills service.

csm_core has no SkillRegistry — skills are .md files under AppConfig.skill_dir,
parsed at request time. Each .md's YAML frontmatter is the metadata; the
body is the prompt fragment that the article pipeline injects via
``GenerateRequest.user_skill_prompt``.

Expected frontmatter schema (best-effort — missing fields fall back gracefully):

    ---
    name: 克制理性
    desc: 短句、低饱和、少形容词
    tone: rational
    ---
    <markdown body — the actual Skill prompt>
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter


@dataclass
class Skill:
    id: str           # filename stem
    name: str         # frontmatter.name or id
    desc: str         # frontmatter.desc or ""
    tone: str         # frontmatter.tone or ""
    role: str         # frontmatter.role or "persona"（人设 persona / 去AI味 humanize）
    path: Path
    body: str         # markdown body without frontmatter

    def to_dict(self, *, include_body: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "desc": self.desc,
            "tone": self.tone,
            "role": self.role,
            "uses": 0,  # field exists in prototype mock data; sidecar returns 0 (砍 per A2)
        }
        if include_body:
            d["body"] = self.body
        return d


def list_skills(skill_dir: Path | None) -> list[Skill]:
    """Scan ``skill_dir`` for *.md files and parse each.

    Files that fail to parse are silently skipped — they shouldn't break
    the whole library load. (The settings UI can run a separate "validate
    skills" check if we want to surface them later.)
    """
    if not skill_dir or not skill_dir.exists() or not skill_dir.is_dir():
        return []
    out: list[Skill] = []
    for md in sorted(skill_dir.glob("*.md")):
        try:
            post = frontmatter.load(md)
        except Exception:
            continue
        fm = post.metadata or {}
        out.append(Skill(
            id=md.stem,
            name=str(fm.get("name") or md.stem),
            desc=str(fm.get("desc") or ""),
            tone=str(fm.get("tone") or ""),
            role=str(fm.get("role") or "persona"),
            path=md,
            body=post.content or "",
        ))
    return out


def get_skill(skill_dir: Path | None, skill_id: str) -> Skill | None:
    """Load a single Skill by id (filename stem)."""
    if not skill_dir:
        return None
    md = skill_dir / f"{skill_id}.md"
    if not md.exists():
        return None
    try:
        post = frontmatter.load(md)
    except Exception:
        return None
    fm = post.metadata or {}
    return Skill(
        id=md.stem,
        name=str(fm.get("name") or md.stem),
        desc=str(fm.get("desc") or ""),
        tone=str(fm.get("tone") or ""),
        role=str(fm.get("role") or "persona"),
        path=md,
        body=post.content or "",
    )


def _write_skill(
    skill_dir: Path,
    skill_id: str,
    name: str,
    desc: str,
    tone: str,
    role: str,
    body: str,
) -> Path:
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = skill_dir / f"{skill_id}.md"
    post = frontmatter.Post(
        body or "",
        **{
            "name": name or skill_id,
            "desc": desc or "",
            "tone": tone or "",
            "role": role or "persona",
        },
    )
    md.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return md


def create_skill(
    skill_dir: Path | None,
    skill_id: str,
    *,
    name: str,
    desc: str,
    tone: str,
    body: str,
    role: str = "persona",
) -> Skill:
    if not skill_dir:
        raise ValueError("skill_dir is not configured")
    md = skill_dir / f"{skill_id}.md"
    if md.exists():
        raise FileExistsError(f"skill id already exists: {skill_id}")
    _write_skill(skill_dir, skill_id, name, desc, tone, role, body)
    skill = get_skill(skill_dir, skill_id)
    assert skill is not None
    return skill


def update_skill(
    skill_dir: Path | None,
    skill_id: str,
    *,
    name: str,
    desc: str,
    tone: str,
    body: str,
    role: str | None = None,
) -> Skill:
    if not skill_dir:
        raise ValueError("skill_dir is not configured")
    md = skill_dir / f"{skill_id}.md"
    if not md.exists():
        raise FileNotFoundError(f"skill not found: {skill_id}")
    if role is None:                        # 前端未传 role → 保留现值，不回退
        current = get_skill(skill_dir, skill_id)
        role = current.role if current else "persona"
    _write_skill(skill_dir, skill_id, name, desc, tone, role, body)
    skill = get_skill(skill_dir, skill_id)
    assert skill is not None
    return skill


def delete_skill(skill_dir: Path | None, skill_id: str) -> None:
    if not skill_dir:
        raise ValueError("skill_dir is not configured")
    md = skill_dir / f"{skill_id}.md"
    if not md.exists():
        raise FileNotFoundError(f"skill not found: {skill_id}")
    md.unlink()
