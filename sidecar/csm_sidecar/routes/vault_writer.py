"""Vault 写入器路由（同步：本地文件操作快，无需 SSE）。"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from ..auth import RequireToken
from ..services import vault_writer_service

router = APIRouter(tags=["vault_writer"], dependencies=[RequireToken])


class SpecRow(BaseModel):
    group: str = ""
    key: str
    value: str


class NoteBody(BaseModel):
    rel_folder: str = Field(min_length=1)
    filename: str = Field(min_length=1)
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    body_shape: Literal["variants", "spec_table"]
    variants: list[str] | None = None
    spec_rows: list[SpecRow] | None = None


class UndoBody(BaseModel):
    created_rel: str
    content_sha: str
    index_rel: str | None = None
    index_line: str | None = None


def _spec_rows(body: NoteBody):
    return [r.model_dump() for r in body.spec_rows] if body.spec_rows else None


@router.get("/api/vault/writable-folders")
def writable_folders() -> dict[str, Any]:
    try:
        return {"folders": vault_writer_service.list_folders()}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/api/vault/plan")
def plan(body: NoteBody) -> dict[str, Any]:
    try:
        return vault_writer_service.plan(
            rel_folder=body.rel_folder, filename=body.filename,
            frontmatter=body.frontmatter, body_shape=body.body_shape,
            variants=body.variants, spec_rows=_spec_rows(body),
            today=date.today().isoformat())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/api/vault/commit")
def commit(body: NoteBody) -> dict[str, Any]:
    try:
        return vault_writer_service.commit(
            rel_folder=body.rel_folder, filename=body.filename,
            frontmatter=body.frontmatter, body_shape=body.body_shape,
            variants=body.variants, spec_rows=_spec_rows(body),
            today=date.today().isoformat())
    except FileExistsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"同名笔记已存在: {e}")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"写入失败：素材库不可写（共享盘断开或文件被占用）: {e}")


@router.post("/api/vault/undo")
def undo(body: UndoBody) -> dict[str, Any]:
    try:
        return vault_writer_service.undo(body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"撤销失败：素材库不可写（共享盘断开或文件被占用）: {e}")
