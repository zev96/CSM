"""Vault service — thin wrapper around csm_core.vault.scanner.

The scan is in-process and synchronous. For large vaults (>1k notes) this
can take 1–3 seconds; that's still fast enough to not need SSE — the UI
shows a spinner. If profiling later shows it bottlenecks, we add a
progress callback to scan_vault and stream via SSE.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from csm_core.vault.note_parser import ParsedNote
from csm_core.vault.scanner import VaultIndex, scan_vault

# Cache the most recent scan in-memory so /api/vault/notes doesn't have to
# re-walk the filesystem on every page load. Invalidated on /api/vault/scan
# and on AppConfig.vault_root change (caller's responsibility).
_index: VaultIndex | None = None


def scan(root: Path) -> VaultIndex:
    """Re-scan ``root`` and replace the cached index."""
    global _index
    _index = scan_vault(Path(root))
    return _index


def cached() -> VaultIndex | None:
    return _index


def invalidate() -> None:
    global _index
    _index = None


def note_to_dict(note: ParsedNote) -> dict[str, Any]:
    """Serialize a ParsedNote for HTTP responses.

    The full ``raw_body`` is omitted from list responses (typical note runs
    1–10KB; a vault list of 1k notes would be 1–10MB). Callers needing the
    body fetch a single note via ``GET /api/vault/notes/{id}`` (added later
    if a UI screen needs it).
    """
    return {
        "id": note.id,
        "path": str(note.path),
        "frontmatter": note.frontmatter,
        "variant_count": len(note.variants),
    }


def index_summary(index: VaultIndex) -> dict[str, Any]:
    return {
        "root": str(index.root),
        "note_count": len(index.notes),
        "warnings": index.warnings,
    }
