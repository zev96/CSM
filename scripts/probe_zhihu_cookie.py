"""Standalone zhihu cookie probe — bypasses the full sidecar.

Reads the latest enabled zhihu cookie from monitor.db, injects it into a
headless Chrome via DrissionPage, navigates to a real zhihu question
page, and reports:
  - whether key login fields (z_c0) are present in the cookie string
  - whether the landed URL is the question page or a signin redirect
  - how many css:.AnswerItem cards rendered after a few scrolls

Run from repo root:
    python scripts/probe_zhihu_cookie.py [question_id]

Default question_id is 302023237 (the kuaishou vacuum cleaner one from
the user's settings).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path


def find_monitor_db() -> Path:
    # Same resolution as the sidecar: <config_dir>/monitor.db
    # config_dir on Windows = %LOCALAPPDATA%\CSM\CSM
    import os
    base = Path(os.environ.get("LOCALAPPDATA") or "")
    candidate = base / "CSM" / "CSM" / "monitor.db"
    if candidate.exists():
        return candidate
    # macOS / linux fallback
    home = Path.home()
    for p in [
        home / "Library" / "Application Support" / "CSM" / "CSM" / "monitor.db",
        home / ".config" / "CSM" / "monitor.db",
    ]:
        if p.exists():
            return p
    raise SystemExit("monitor.db not found in expected locations")


def read_latest_cookie(db_path: Path) -> tuple[str, str, str]:
    """Return (label, cookies_text, user_agent) for the highest-priority
    enabled zhihu cookie. Mirrors storage.list_credentials' ordering."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT label, cookies_text, user_agent, fail_count, enabled "
        "FROM platform_credentials "
        "WHERE platform = 'zhihu_question' "
        "ORDER BY enabled DESC, fail_count ASC, last_used_at ASC NULLS FIRST "
        "LIMIT 1"
    ).fetchone()
    if row is None:
        raise SystemExit("no zhihu cookie in monitor.db — add one in the UI first")
    print(f"[db] picked cookie: label={row['label']!r} "
          f"fail_count={row['fail_count']} enabled={row['enabled']}")
    return row["label"] or "", row["cookies_text"], row["user_agent"] or ""


def parse_cookie_keys(cookies_text: str) -> list[str]:
    out: list[str] = []
    for piece in cookies_text.split(";"):
        piece = piece.strip()
        if "=" in piece:
            out.append(piece.split("=", 1)[0].strip())
    return out


def main() -> int:
    qid = sys.argv[1] if len(sys.argv) > 1 else "302023237"
    url = f"https://www.zhihu.com/question/{qid}"

    db = find_monitor_db()
    print(f"[db] reading from {db}")
    label, cookies_text, ua = read_latest_cookie(db)

    keys = parse_cookie_keys(cookies_text)
    print(f"[cookie] {len(keys)} cookies in string")
    print(f"[cookie] keys: {', '.join(keys)}")
    critical = ["z_c0", "q_c1", "_zap", "d_c0"]
    missing = [k for k in critical if k not in keys]
    if "z_c0" not in keys:
        print("[cookie] !!! z_c0 MISSING — this is the login session cookie.")
        print("[cookie] !!! without z_c0, zhihu treats you as a guest.")
    if missing:
        print(f"[cookie] missing critical fields: {missing}")
    else:
        print("[cookie] all 4 critical login fields present")

    print()
    print(f"[browser] launching headless Chrome for {url}")
    import tempfile
    try:
        from DrissionPage import ChromiumPage, ChromiumOptions
    except ImportError as e:
        print(f"[browser] DrissionPage import failed: {e}")
        return 2

    opts = ChromiumOptions()
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if Path(chrome_path).is_file():
        opts.set_browser_path(chrome_path)
        print(f"[browser] chrome at {chrome_path}")
    user_data_dir = str(Path(tempfile.gettempdir()) / "csm-drission-probe")
    try:
        opts.set_user_data_path(user_data_dir)
    except AttributeError:
        opts.set_paths(user_data_path=user_data_dir)
    try:
        opts.auto_port()
    except AttributeError:
        pass
    # 没用 --headless：zhihu 反爬精准识别 headless Chrome
    opts.set_argument("--disable-blink-features=AutomationControlled")
    opts.set_argument("--no-sandbox")
    opts.set_argument("--window-size=1000,700")
    if ua:
        opts.set_user_agent(ua)
    else:
        opts.set_user_agent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        )

    try:
        page = ChromiumPage(opts)
    except Exception as e:
        print(f"[browser] launch failed: {e!r}")
        return 3
    print("[browser] launched")

    # Inject cookies on zhihu domain
    try:
        page.get("https://www.zhihu.com/")
        cookies_to_set = []
        for piece in cookies_text.split(";"):
            piece = piece.strip()
            if not piece or "=" not in piece:
                continue
            k, _, v = piece.partition("=")
            cookies_to_set.append({"name": k.strip(), "value": v.strip(),
                                    "domain": ".zhihu.com"})
        page.set.cookies(cookies_to_set)
        print(f"[browser] injected {len(cookies_to_set)} cookies (.zhihu.com)")
        # Also try plain zhihu.com domain
        for c in cookies_to_set:
            c["domain"] = "zhihu.com"
        page.set.cookies(cookies_to_set)
        print(f"[browser] re-injected {len(cookies_to_set)} cookies (zhihu.com)")
    except Exception as e:
        print(f"[browser] cookie injection failed: {e!r}")

    # Read back cookies the browser actually has
    try:
        readback = page.cookies(as_dict=True)
        print(f"[browser] readback: {len(readback)} cookies in browser context")
        for k in ("z_c0", "q_c1", "_zap", "d_c0"):
            v = readback.get(k, "")
            print(f"[browser]   {k} = {'<set>' if v else '<MISSING>'}")
    except Exception as e:
        print(f"[browser] cookie readback failed: {e!r}")

    # Navigate to the question
    print(f"[browser] navigating to {url}")
    try:
        page.get(url)
    except Exception as e:
        print(f"[browser] navigation failed: {e!r}")
        page.quit()
        return 4
    try:
        landed = page.url
        title = page.title or ""
    except Exception:
        landed = "?"
        title = "?"
    print(f"[browser] landed URL: {landed}")
    print(f"[browser] page title: {title}")
    if "signin" in landed or "login" in landed:
        print("[browser] !!! redirected to signin")
        page.quit()
        return 5
    if "unhuman" in landed:
        print("[browser] !!! hit zhihu anti-bot wall (/account/unhuman)")
        page.quit()
        return 6

    # CSS 缩高 + 隐图 —— 跟 zhihu adapter 同款逻辑
    try:
        page.run_js("""
            const css = `
                .AnswerItem { max-height: 200px !important; overflow: hidden !important; }
                .AnswerItem .RichContent { max-height: 100px !important; overflow: hidden !important; }
                img, picture, video, figure { display: none !important; }
            `;
            const s = document.createElement('style');
            s.textContent = css;
            document.head.appendChild(s);
        """)
        print("[browser] CSS shrink injected (collapse cards + hide images)")
    except Exception as e:
        print(f"[browser] CSS inject failed: {e!r}")

    # Wait up to 15s for initial cards to mount —— zhihu lazy-mounts via JS
    # after navigation, eles() can return 0 if checked too early.
    print("[browser] waiting for initial cards (up to 15s)...")
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        n = len(page.eles("css:.AnswerItem"))
        if n > 0:
            print(f"[browser]   initial render: {n} cards")
            break
        time.sleep(1.0)

    # Scroll pattern: 到底 → 回弹 -200px → 等 2s （触发 IntersectionObserver）
    print("[browser] scrolling to load lazy answers (bottom + bounce + wait)...")
    for i in range(10):
        prev = len(page.eles("css:.AnswerItem"))
        try:
            page.run_js("""
                window.scrollTo(0, document.body.scrollHeight);
                setTimeout(() => window.scrollBy(0, -200), 300);
            """)
        except Exception:
            page.run_js("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2.0)
        cur = len(page.eles("css:.AnswerItem"))
        print(f"[browser]   scroll {i + 1}: {prev} -> {cur} cards")
        if cur >= 20:
            break
        if prev == cur and i >= 3:
            break  # stuck

    cards = page.eles("css:.AnswerItem")
    print(f"[browser] final: {len(cards)} AnswerItem cards rendered")

    if cards:
        print()
        print("[result] OK — cookie works, zhihu rendered answers")
        # Sample first card's author + content
        try:
            first = cards[0]
            author_el = first.ele("css:.AuthorInfo-name", timeout=0.3)
            content_el = first.ele("css:.RichContent-inner", timeout=0.3)
            print(f"[result] #1 author = {author_el.text if author_el else '?'!r}")
            content = content_el.text if content_el else ""
            print(f"[result] #1 preview = {content[:80]!r}")
        except Exception as e:
            print(f"[result] sample read failed: {e!r}")
    else:
        print()
        print("[result] FAIL — cookie did NOT yield answers, see landed URL + title above")
        print("[result] likely causes:")
        print("[result]   - z_c0 not in cookie")
        print("[result]   - cookie expired (re-login + re-copy)")
        print("[result]   - zhihu showing captcha or anti-bot wall")

    page.quit()
    return 0 if cards else 1


if __name__ == "__main__":
    sys.exit(main())
