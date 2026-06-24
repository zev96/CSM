"""Skill library routes."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from ..auth import RequireToken
from ..services import config_service, skills_service

router = APIRouter(tags=["skills"], dependencies=[RequireToken])


def _resolve_skill_dir() -> Path | None:
    cfg = config_service.load()
    return Path(cfg.skill_dir) if cfg.skill_dir else None


def _require_skill_dir() -> Path:
    d = _resolve_skill_dir()
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="skill_dir 未配置 — 请先在「设置」里指定 Skill 目录",
        )
    return d


class SkillPayload(BaseModel):
    id: str
    name: str
    desc: str = ""
    tone: str = ""
    role: str = "persona"
    body: str = ""


class SkillUpdatePayload(BaseModel):
    name: str
    desc: str = ""
    tone: str = ""
    role: str | None = None
    body: str = ""


@router.get("/api/skills")
def list_skills() -> dict[str, Any]:
    skills = skills_service.list_skills(_resolve_skill_dir())
    return {
        "count": len(skills),
        "skills": [s.to_dict() for s in skills],
    }


@router.get("/api/skills/{skill_id}")
def get_skill(skill_id: str) -> dict[str, Any]:
    skill = skills_service.get_skill(_resolve_skill_dir(), skill_id)
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"skill not found: {skill_id}",
        )
    return skill.to_dict(include_body=True)


@router.post("/api/skills", status_code=201)
def create_skill(payload: SkillPayload) -> dict[str, Any]:
    skill_dir = _require_skill_dir()
    if not payload.id.strip():
        raise HTTPException(status_code=400, detail="id 不能为空")
    try:
        skill = skills_service.create_skill(
            skill_dir,
            payload.id.strip(),
            name=payload.name,
            desc=payload.desc,
            tone=payload.tone,
            role=payload.role,
            body=payload.body,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return skill.to_dict(include_body=True)


@router.patch("/api/skills/{skill_id}")
def update_skill(skill_id: str, payload: SkillUpdatePayload) -> dict[str, Any]:
    skill_dir = _require_skill_dir()
    try:
        skill = skills_service.update_skill(
            skill_dir,
            skill_id,
            name=payload.name,
            desc=payload.desc,
            tone=payload.tone,
            role=payload.role,
            body=payload.body,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return skill.to_dict(include_body=True)


@router.delete("/api/skills/{skill_id}", status_code=204)
def delete_skill(skill_id: str) -> None:
    skill_dir = _require_skill_dir()
    try:
        skills_service.delete_skill(skill_dir, skill_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
