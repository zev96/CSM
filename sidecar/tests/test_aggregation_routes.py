"""Tests for /api/recent, /api/calendar, /api/stats/words."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


def _write_doc(p: Path, *, content: str = "", mtime: datetime | None = None,
               with_frontmatter: bool = True, title: str = "测试标题",
               template: str | None = "导购文-基础") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if with_frontmatter:
        fm_lines = ["---", f"title: {title}"]
        if template:
            fm_lines.append(f"template: {template}")
        fm_lines.append("---")
        body = "\n".join(fm_lines) + "\n" + content
    else:
        body = content
    p.write_text(body, encoding="utf-8")
    if mtime is not None:
        ts = mtime.timestamp()
        os.utime(p, (ts, ts))


# ── /api/recent ─────────────────────────────────────────────────────────────
def test_recent_empty_when_history_unset(client: TestClient):
    resp = client.get("/api/recent")
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "documents": []}


def test_recent_lists_files_newest_first(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})

    now = datetime.now()
    _write_doc(history / "old.md", content="x" * 50, mtime=now - timedelta(days=2),
               title="old article")
    _write_doc(history / "new.md", content="y" * 50, mtime=now - timedelta(hours=1),
               title="new article")

    data = client.get("/api/recent").json()
    assert data["count"] == 2
    # Newest first.
    assert data["documents"][0]["title"] == "new article"
    assert data["documents"][1]["title"] == "old article"
    assert data["documents"][0]["template_name"] == "导购文-基础"


def test_recent_drops_files_outside_window(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    now = datetime.now()
    _write_doc(history / "fresh.md", mtime=now - timedelta(days=2))
    _write_doc(history / "stale.md", mtime=now - timedelta(days=30))

    data = client.get("/api/recent", params={"days": 7}).json()
    assert data["count"] == 1
    assert data["documents"][0]["filename"] == "fresh.md"


def test_recent_limit_respected(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    now = datetime.now()
    for i in range(8):
        _write_doc(history / f"d{i}.md", mtime=now - timedelta(hours=i))
    data = client.get("/api/recent", params={"limit": 3}).json()
    assert data["count"] == 3


def test_recent_only_lists_markdown(client: TestClient, tmp_path: Path):
    """History dir holds .md mirrors only — any stray .docx must be ignored."""
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    _write_doc(history / "yes.md", title="md only")
    (history / "no.docx").write_bytes(b"not really a docx")
    data = client.get("/api/recent").json()
    assert data["count"] == 1
    assert data["documents"][0]["filename"] == "yes.md"


# ── /api/calendar ───────────────────────────────────────────────────────────
def test_calendar_returns_zeros_when_no_files(client: TestClient, tmp_path: Path):
    client.patch("/api/config", json={"dedup_history_dir": str(tmp_path / "history")})
    today = date.today()
    data = client.get("/api/calendar").json()
    assert data["year"] == today.year
    assert data["month"] == today.month
    assert all(d == 0 for d in data["done"])
    # 'scheduled' is the placeholder — same length, all zeros.
    assert len(data["scheduled"]) == data["days"]
    assert all(s == 0 for s in data["scheduled"])


def test_calendar_counts_per_day(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    # Drop two articles on day 5, one on day 10 of *this* month.
    now = date.today()
    if now.day < 11:
        # Test runs early-month; use last month so we have a stable past day.
        target_year = (now.replace(day=1) - timedelta(days=1)).year
        target_month = (now.replace(day=1) - timedelta(days=1)).month
    else:
        target_year, target_month = now.year, now.month
    _write_doc(history / "a.md", mtime=datetime(target_year, target_month, 5, 12, 0))
    _write_doc(history / "b.md", mtime=datetime(target_year, target_month, 5, 13, 0))
    _write_doc(history / "c.md", mtime=datetime(target_year, target_month, 10, 9, 0))

    resp = client.get(
        "/api/calendar", params={"month": f"{target_year}-{target_month:02d}"}
    ).json()
    assert resp["done"][4] == 2  # day 5 → index 4
    assert resp["done"][9] == 1  # day 10 → index 9


def test_calendar_invalid_month_400(client: TestClient):
    resp = client.get("/api/calendar", params={"month": "not-a-month"})
    assert resp.status_code == 400


def test_calendar_invalid_month_number_400(client: TestClient):
    resp = client.get("/api/calendar", params={"month": "2026-13"})
    assert resp.status_code == 400


# ── /api/stats/words ────────────────────────────────────────────────────────
def test_stats_words_returns_per_day_breakdown(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    today = datetime.now()
    # Plain content (no frontmatter so wordcount only counts the body).
    _write_doc(history / "today.md", content="一二三四五" * 10, mtime=today,
               with_frontmatter=False)

    data = client.get("/api/stats/words", params={"range": "this-week"}).json()
    assert data["range"] == "this-week"
    assert data["total_words"] == 50  # 5 chars × 10 reps
    bars = data["by_day"]
    # this-week starts Mon, ends tomorrow → at least 1 bar.
    assert len(bars) >= 1
    # Today's bar should have 50 words.
    today_iso = today.date().isoformat()
    today_bar = next(b for b in bars if b["date"] == today_iso)
    assert today_bar["words"] == 50
    assert today_bar["polished"] == 0  # placeholder per A2


def test_stats_words_yesterday_counts_yesterday(client: TestClient, tmp_path: Path):
    history = tmp_path / "history"
    client.patch("/api/config", json={"dedup_history_dir": str(history)})
    yesterday = datetime.now() - timedelta(days=1)
    _write_doc(history / "y.md", content="一" * 30, mtime=yesterday,
               with_frontmatter=False)

    data = client.get("/api/stats/words", params={"range": "yesterday"}).json()
    assert data["range"] == "yesterday"
    assert data["total_words"] == 30


def test_stats_words_invalid_range_400(client: TestClient):
    resp = client.get("/api/stats/words", params={"range": "next-quarter"})
    assert resp.status_code == 400


def test_stats_words_no_history_returns_zeros(client: TestClient):
    data = client.get("/api/stats/words", params={"range": "this-week"}).json()
    assert data["total_words"] == 0
    assert all(b["words"] == 0 for b in data["by_day"])
