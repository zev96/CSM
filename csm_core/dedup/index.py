"""MinHashLSH index wrapper with pickle persistence.

Decouples the rest of the codebase from datasketch — callers see
``add_doc(text, meta)`` / ``query(text) -> [doc_id]`` and never touch
MinHash objects directly. Persistence: one ``.lsh`` (pickle of the LSH
itself) plus one ``.meta.json`` (doc_id → meta dict, including each doc's
serialized MinHash signature for the rebuild-on-update path).
"""
from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datasketch import MinHash, MinHashLSH

from .shingles import compute_shingles

logger = logging.getLogger(__name__)

NUM_PERM = 128
LSH_THRESHOLD = 0.3


def _build_minhash(text: str, num_perm: int = NUM_PERM) -> MinHash:
    m = MinHash(num_perm=num_perm)
    for s in compute_shingles(text):
        m.update(s.encode("utf-8"))
    return m


@dataclass
class _Meta:
    """In-memory state per doc: original meta + serialized MinHash hashvalues
    (numpy array) so we can re-insert into a fresh LSH on partial updates.
    """
    meta: dict[str, Any]
    hashvalues: bytes  # MinHash.hashvalues serialized via pickle


class DedupIndex:
    """High-level dedup index. Thread-affine — use one instance per QThread."""

    def __init__(self):
        self._lsh = MinHashLSH(threshold=LSH_THRESHOLD, num_perm=NUM_PERM)
        self._meta: dict[str, _Meta] = {}

    def add_doc(self, doc_id: str, text: str, meta: dict[str, Any]) -> None:
        """Insert or replace a doc.

        Replacement: removes the old entry first (LSH does not allow
        duplicate keys).
        """
        if doc_id in self._meta:
            self.remove_doc(doc_id)
        m = _build_minhash(text)
        self._lsh.insert(doc_id, m)
        self._meta[doc_id] = _Meta(meta=meta, hashvalues=pickle.dumps(m.hashvalues))

    def remove_doc(self, doc_id: str) -> None:
        if doc_id in self._meta:
            try:
                self._lsh.remove(doc_id)
            except KeyError:
                pass
            del self._meta[doc_id]

    def query(self, text: str, top_k: int = 10) -> list[str]:
        """Return up to ``top_k`` candidate doc_ids whose Jaccard estimate
        is >= ``LSH_THRESHOLD`` to ``text``.
        """
        m = _build_minhash(text)
        candidates = self._lsh.query(m)
        return list(candidates)[:top_k]

    def get_meta(self, doc_id: str) -> dict[str, Any] | None:
        if doc_id in self._meta:
            return self._meta[doc_id].meta
        return None

    def doc_count(self) -> int:
        return len(self._meta)

    # ── Persistence ────────────────────────────────────────────────────
    def save(self, dir_path: Path, *, name: str) -> None:
        """Atomic write of LSH + meta.json to dir_path/{name}.lsh + .meta.json."""
        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        lsh_path = dir_path / f"{name}.lsh"
        meta_path = dir_path / f"{name}.meta.json"

        # LSH itself pickles cleanly.
        tmp_lsh = lsh_path.with_suffix(".lsh.tmp")
        with open(tmp_lsh, "wb") as f:
            pickle.dump(self._lsh, f)
        tmp_lsh.replace(lsh_path)

        # Meta JSON — encode hashvalues bytes as hex so JSON-serializable.
        payload = {
            doc_id: {
                "meta": entry.meta,
                "hashvalues_hex": entry.hashvalues.hex(),
            }
            for doc_id, entry in self._meta.items()
        }
        tmp_meta = meta_path.with_suffix(".json.tmp")
        tmp_meta.write_text(json.dumps(payload, ensure_ascii=False),
                            encoding="utf-8")
        tmp_meta.replace(meta_path)

    @classmethod
    def load(cls, dir_path: Path, *, name: str) -> "DedupIndex":
        """Load from dir_path/{name}.lsh + .meta.json. Returns empty index on
        any error so the caller can prompt the user to rebuild.
        """
        dir_path = Path(dir_path)
        lsh_path = dir_path / f"{name}.lsh"
        meta_path = dir_path / f"{name}.meta.json"

        idx = cls()
        if not lsh_path.exists() or not meta_path.exists():
            return idx

        try:
            with open(lsh_path, "rb") as f:
                idx._lsh = pickle.load(f)
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            for doc_id, entry in payload.items():
                idx._meta[doc_id] = _Meta(
                    meta=entry["meta"],
                    hashvalues=bytes.fromhex(entry["hashvalues_hex"]),
                )
        except Exception as exc:
            logger.warning("dedup index: load failed for %s — %s", name, exc)
            return cls()  # fresh empty
        return idx
