"""Template CRUD routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from csm_core.template.schema import Template

from ..auth import RequireToken
from ..services import templates_service

router = APIRouter(tags=["templates"], dependencies=[RequireToken])


@router.get("/api/templates")
def list_templates() -> dict[str, Any]:
    items = templates_service.list_all()
    return {"count": len(items), "templates": items}


@router.get("/api/templates/{template_id}", response_model=Template)
def get_template(template_id: str) -> Template:
    try:
        return templates_service.get_one(template_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/api/templates", response_model=Template, status_code=201)
def create_template(template: Template) -> Template:
    try:
        templates_service.create(template)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return template


@router.patch("/api/templates/{template_id}", response_model=Template)
def update_template(template_id: str, template: Template) -> Template:
    if template.id != template_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"path id '{template_id}' does not match body id '{template.id}'",
        )
    try:
        templates_service.update(template)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return template


@router.delete("/api/templates/{template_id}", status_code=204)
def delete_template(template_id: str) -> None:
    try:
        templates_service.delete(template_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
