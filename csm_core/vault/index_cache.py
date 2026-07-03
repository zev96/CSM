"""增量 vault 索引：stat 巡走，仅重解析变更文件。

刷新语义：每次 refresh 都全量 stat 巡走（快，纯元数据），
(mtime_ns, size) 双键判变——共享盘 mtime 粒度粗时 size 兜底。
输出与 scan_vault 全量扫逐字段一致（notes 按 path 序、警告同序）。
巡走间被删/不可读的文件本轮跳过，下轮稳定后再收。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .note_parser import ParsedNote
from .scanner import VaultIndex, parse_one


@dataclass
class _Entry:
    mtime_ns: int
    size: int
    note: ParsedNote | None      # None = 该文件是警告项（缺 frontmatter/解析失败）
    warning: str | None


class IncrementalIndexer:
    """增量索引器。非线程安全：调用方必须串行化 refresh/reset
    （sidecar 在 vault_service 层加锁）。同一 root 上 refresh 幂等。"""

    def __init__(self) -> None:
        self._root: Path | None = None
        self._files: dict[Path, _Entry] = {}

    def reset(self) -> None:
        self._root = None
        self._files.clear()

    def refresh(self, root: Path) -> VaultIndex:
        root = Path(root)
        if self._root != root:
            self.reset()
            self._root = root
        seen: set[Path] = set()
        for md_path in sorted(root.rglob("*.md")):
            try:
                st = md_path.stat()
            except OSError:
                continue                     # 巡走间被删/锁：本轮跳过
            seen.add(md_path)
            entry = self._files.get(md_path)
            if (entry is not None
                    and entry.mtime_ns == st.st_mtime_ns
                    and entry.size == st.st_size):
                continue
            note, warning = parse_one(md_path)
            self._files[md_path] = _Entry(st.st_mtime_ns, st.st_size, note, warning)
        for stale in set(self._files) - seen:
            del self._files[stale]

        index = VaultIndex(root=root)
        for path in sorted(self._files):
            e = self._files[path]
            if e.warning:
                index.warnings.append(e.warning)
            if e.note is not None:
                index.notes.append(e.note)
                index.by_id[e.note.id] = e.note
        return index
