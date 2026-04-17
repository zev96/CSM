"""Scan an entire Obsidian Vault directory and build a queryable index."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .note_parser import ParsedNote, parse_note


@dataclass
class VaultIndex:
    root: Path
    notes: list[ParsedNote] = field(default_factory=list)
    by_id: dict[str, ParsedNote] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def get(self, note_id: str) -> ParsedNote | None:
        return self.by_id.get(note_id)

    def by_module(self, module: str) -> list[ParsedNote]:
        """Return notes whose path contains the module path parts in order.

        The module string is a '/'-separated sequence of directory names that
        must appear as an ordered (not necessarily contiguous) subsequence of
        the note's relative path parts under ``root``.
        """
        wanted = [p for p in module.replace("\\", "/").split("/") if p]
        matches: list[ParsedNote] = []
        for n in self.notes:
            try:
                rel_parts = n.path.relative_to(self.root).parts[:-1]
            except ValueError:
                continue
            i = 0
            for part in rel_parts:
                if i < len(wanted) and part == wanted[i]:
                    i += 1
            if i == len(wanted):
                matches.append(n)
        return matches

    def query(
        self,
        *,
        module: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[ParsedNote]:
        candidates = self.by_module(module) if module else list(self.notes)
        if not filters:
            return candidates
        return [
            n for n in candidates
            if all(n.frontmatter.get(k) == v for k, v in filters.items())
        ]


def scan_vault(root: Path) -> VaultIndex:
    index = VaultIndex(root=root)
    for md_path in sorted(root.rglob("*.md")):
        try:
            note = parse_note(md_path)
            if not note.frontmatter:
                index.warnings.append(f"{md_path.name}: 缺少 frontmatter")
                continue
            index.notes.append(note)
            index.by_id[note.id] = note
        except Exception as exc:
            index.warnings.append(f"{md_path.name}: 解析失败 — {exc}")
    return index
