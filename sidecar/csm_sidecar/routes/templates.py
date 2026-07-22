"""Template CRUD routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from csm_core.template.lint import has_errors, lint_template
from csm_core.template.schema import Template

from ..auth import RequireToken
from ..services import templates_service

router = APIRouter(tags=["templates"], dependencies=[RequireToken])


def _check_structure(template: Template) -> None:
    """结构 lint —— error 拦下保存，warning 放行（由 /lint 端点展示）。

    版本标签漏标之类的问题在生成期只会静默产出残文（跨版本引用会渲染
    「缺数据」占位），所以必须在保存这一刻拦住。
    """
    issues = lint_template(template)
    if has_errors(issues):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "模板结构校验未通过",
                "issues": [i.as_dict() for i in issues],
            },
        )


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


@router.post("/api/templates/lint")
def lint_one(template: Template) -> dict[str, Any]:
    """结构检查（不保存）—— 编辑器实时提示漏标/跨版本引用等问题。"""
    issues = lint_template(template)
    return {
        "ok": not has_errors(issues),
        "issues": [i.as_dict() for i in issues],
    }


@router.post("/api/templates", response_model=Template, status_code=201)
def create_template(template: Template) -> Template:
    _check_structure(template)
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
    _check_structure(template)
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
