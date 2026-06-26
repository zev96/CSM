"""Deterministic vault note writer — render structured material → 规范 .md.

Writes obey the *real* vault (CLAUDE.md has drifted): backlink tail targets the
nearest-ancestor index discovered by scanning (not §5.2's stale table), and the
note is registered only in a writer-owned "## App 新增" block — never the
hand-curated index tables. plan_note is pure (no disk write); commit_note writes
and refuses to overwrite; undo_write is best-effort single-level.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .note_parser import VARIANT_MARKERS

_APP_BLOCK = "## App 新增（待人工归入）"
_YAML_BARE_BOOL_NULL = {"true", "false", "null", "yes", "no", "on", "off", "~"}


def _needs_quote(s: str) -> bool:
    if s == "" or s != s.strip():
        return True
    if re.search(r":(\s|$)", s):          # colon-space or trailing colon
        return True
    if s[0] in "[]{}#&*!|>%@`\"',?-":      # YAML-special leading chars
        return True
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", s):   # number-literal → keep as string
        return True
    if s.lower() in _YAML_BARE_BOOL_NULL:
        return True
    return False


def _yaml_scalar(v: object) -> str:
    s = str(v)
    if _needs_quote(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


@dataclass(frozen=True)
class NotePlan:
    rel_folder: str
    filename: str
    rel_path: str
    frontmatter: dict[str, Any]
    body: str
    backlink_tail: str
    full_text: str
    index_rel: str | None
    index_line: str | None
    conflict: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WriteReceipt:
    created_rel: str
    content_sha: str
    index_rel: str | None = None
    index_line: str | None = None


def _render_frontmatter(fm: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            lines.extend(f"  - {_yaml_scalar(item)}" for item in v)
        else:
            lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


def _render_body(body_shape, variants, spec_rows) -> str:
    if body_shape == "variants":
        items = variants or []
        if len(items) > len(VARIANT_MARKERS):
            raise ValueError(f"变体数 {len(items)} 超过上限 {len(VARIANT_MARKERS)}")
        return "\n\n".join(
            f"{VARIANT_MARKERS[i]} {str(t).strip()}" for i, t in enumerate(items))
    if body_shape == "spec_table":
        groups: dict[str, list[tuple[str, str]]] = {}
        for r in spec_rows or []:
            groups.setdefault(r.get("group") or "参数", []).append(
                (str(r["key"]), str(r["value"])))
        chunks = []
        for g, rows in groups.items():
            t = [f"## {g}", "", "| 参数 | 数值 |", "|------|------|"]
            t.extend(f"| {k} | {v} |" for k, v in rows)
            chunks.append("\n".join(t))
        return "\n\n".join(chunks)
    return ""


def _find_index(vault_root: Path, rel_folder: str) -> Path | None:
    cur = vault_root / rel_folder
    while True:
        matches = sorted(cur.glob("*索引*.md"))
        if matches:
            return matches[0]
        if cur == vault_root:
            return None
        cur = cur.parent


def _backlink_tail(index_stem: str | None) -> str:
    home = "**返回主页**: [[关联数据库]]"
    if index_stem:
        return f"---\n**返回上层**: [[{index_stem}|{index_stem}]] | {home}"
    return f"---\n{home}"


def plan_note(
    vault_root: Path, *,
    rel_folder: str, filename: str,
    frontmatter: dict[str, Any], body_shape: str, today: str,
    variants: list[str] | None = None,
    spec_rows: list[dict[str, Any]] | None = None,
) -> NotePlan:
    """Render a structured note into a NotePlan (pure — no disk write).

    Callers MUST pre-validate input: ``filename`` non-empty, ends with ``.md``,
    no path separators; ``rel_folder`` non-empty. The engine assumes sanitized
    input (the sidecar service enforces this) — 3b reuses the engine, so keep
    that contract.
    """
    vault_root = Path(vault_root)
    warnings: list[str] = []
    rel_path = f"{rel_folder}/{filename}"
    body = _render_body(body_shape, variants, spec_rows)

    idx = _find_index(vault_root, rel_folder)
    if idx is None:
        warnings.append("无祖先索引，跳过登记")
        index_rel = index_line = index_stem = None
    else:
        index_rel = idx.relative_to(vault_root).as_posix()
        index_stem = idx.stem
        stem = filename[:-3] if filename.endswith(".md") else filename
        index_line = f"- [[{stem}]] · {frontmatter.get('素材类型', '')} · {today}"

    tail = _backlink_tail(index_stem)
    full_text = f"{_render_frontmatter(frontmatter)}\n\n{body}\n\n{tail}\n"
    conflict = (vault_root / rel_path).exists()
    return NotePlan(
        rel_folder=rel_folder, filename=filename, rel_path=rel_path,
        frontmatter=frontmatter, body=body, backlink_tail=tail, full_text=full_text,
        index_rel=index_rel, index_line=index_line, conflict=conflict, warnings=warnings)


def _append_index_line(idx_path: Path, line: str) -> None:
    raw = idx_path.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    m = re.search(r"\[\[([^\]]+)\]\]", line)
    link = f"[[{m.group(1)}]]" if m else line
    if any(link in l for l in lines):
        return  # idempotent by wikilink
    try:
        h = next(i for i, l in enumerate(lines) if l.strip() == _APP_BLOCK)
    except StopIteration:
        idx_path.write_text(raw.rstrip() + f"\n\n{_APP_BLOCK}\n{line}\n", encoding="utf-8")
        return
    last = h
    for k in range(h + 1, len(lines)):
        if lines[k].startswith("- "):
            last = k
        elif lines[k].strip() == "":
            continue
        else:
            break
    lines.insert(last + 1, line)
    idx_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def commit_note(plan: NotePlan, vault_root: Path) -> WriteReceipt:
    vault_root = Path(vault_root)
    target = vault_root / plan.rel_path
    if target.exists():
        raise FileExistsError(plan.rel_path)
    target.write_text(plan.full_text, encoding="utf-8")
    sha = hashlib.sha256(plan.full_text.encode("utf-8")).hexdigest()
    if plan.index_rel and plan.index_line:
        _append_index_line(vault_root / plan.index_rel, plan.index_line)
    return WriteReceipt(
        created_rel=plan.rel_path, content_sha=sha,
        index_rel=plan.index_rel, index_line=plan.index_line)


def undo_write(receipt: WriteReceipt, vault_root: Path) -> list[str]:
    vault_root = Path(vault_root)
    warnings: list[str] = []
    target = vault_root / receipt.created_rel
    if target.exists():
        cur = hashlib.sha256(target.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
        if cur == receipt.content_sha:
            target.unlink()
        else:
            warnings.append(f"{receipt.created_rel} 已被改动，未删除")
    else:
        warnings.append(f"{receipt.created_rel} 不存在")
    if receipt.index_rel and receipt.index_line:
        idx = vault_root / receipt.index_rel
        if idx.exists():
            lines = idx.read_text(encoding="utf-8-sig").splitlines()
            if receipt.index_line in lines:
                lines.remove(receipt.index_line)
                idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
            else:
                warnings.append("索引登记行未找到，跳过")
    return warnings
