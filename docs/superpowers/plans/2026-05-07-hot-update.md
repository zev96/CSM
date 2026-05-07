# 应用热更新（GitHub Releases + 独立 updater.exe）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户推 git tag 触发 GitHub Actions 自动构建 + 发 Release，CSM 启动时静默检查到新版本，弹"发现新版本"对话框，用户点击后下载 + 由独立 updater.exe 替换文件并重启主程序。

**Architecture:** 三层——
1. **CI/Release**：`scripts/release.py` 一键打 tag + push；GitHub Actions 接管 PyInstaller 构建 + 发 Release。
2. **客户端**：`csm_core/updater_client/` 处理检查版本 + 下载校验；GUI 层弹对话框。
3. **Updater 子进程**：`updater/updater.exe` 等主进程退出 → 备份 → 解压 → 重启主程序，失败回滚。

**Tech Stack:** Python 3.11, httpx (GitHub API), PyInstaller, pydantic v2, PyQt6 + qfluentwidgets, GitHub Actions (windows-latest), pytest / pytest-qt

**Spec:** [docs/superpowers/specs/2026-05-07-hot-update-design.md](../specs/2026-05-07-hot-update-design.md)

**目标用户规模：** 10 人内部团队，私有 GitHub repo。

---

## File Structure

**Create:**
- `csm_gui/_version.py` — `__version__ = "0.1.0"`（单一来源）
- `CHANGELOG.md` — Keep a Changelog 格式
- `CSM.spec` — 把主仓库的 spec 提交进来（CI 需要）
- `.github/workflows/release.yml` — tag 触发的 CI
- `.gitignore` — 加 `_token.py`
- `scripts/release.py` — 一键发版（开发者侧）
- `scripts/release_check.py` — CI 校验 tag == _version
- `scripts/extract_changelog.py` — 抽 CHANGELOG 段落
- `scripts/build_manifest.py` — 生成 manifest.json + SHA256
- `csm_core/updater_client/__init__.py`
- `csm_core/updater_client/manifest.py` — UpdateInfo / parse GitHub release JSON
- `csm_core/updater_client/github_client.py` — httpx + PAT auth
- `csm_core/updater_client/checker.py` — check_for_update 编排
- `csm_core/updater_client/downloader.py` — 流式下载 + SHA256
- `csm_core/updater_client/_token.py.example` — 模板（实际 _token.py 由 CI 注入，gitignored）
- `csm_gui/widgets/update_dialog.py` — 发现新版本对话框
- `csm_gui/widgets/update_progress_dialog.py` — 下载进度
- `csm_gui/workers/update_check_worker.py` — 启动后台检查 QThread
- `updater/main.py` — 独立 updater 进程入口
- `updater/updater.spec` — PyInstaller onefile spec
- `tests/core/updater_client/__init__.py`
- `tests/core/updater_client/test_manifest.py`
- `tests/core/updater_client/test_github_client.py`
- `tests/core/updater_client/test_checker.py`
- `tests/core/updater_client/test_downloader.py`
- `tests/scripts/test_release_check.py`
- `tests/scripts/test_extract_changelog.py`
- `tests/scripts/test_build_manifest.py`
- `tests/gui/test_update_dialog.py`
- `tests/gui/test_update_progress_dialog.py`
- `tests/gui/test_update_check_worker.py`
- `tests/updater/test_updater_main.py`

**Modify:**
- `pyproject.toml` — 加 dynamic version 配置
- `csm_gui/main_window.py` — 启动后台检查 + 接信号
- `csm_gui/pages/settings_page.py` — 「关于」section + 检查更新按钮
- `tests/gui/test_main_window.py` — 集成测试
- `tests/gui/test_settings_page.py` — 关于 section 测试

---

## Task 1: 版本号单一来源 + CHANGELOG.md 初始化

**Files:**
- Create: `csm_gui/_version.py`
- Create: `CHANGELOG.md`
- Modify: `pyproject.toml`

- [ ] **Step 1: 创建 _version.py**

写文件 `csm_gui/_version.py`：

```python
"""Single source of truth for CSM's version string.

Bumped by ``scripts/release.py`` on every release. CI's
``scripts/release_check.py`` enforces that the git tag matches.
"""
__version__ = "0.1.0"
```

- [ ] **Step 2: 改 pyproject.toml 用 dynamic version**

把 `[project]` 段下的：
```toml
version = "0.1.0"
```
改为：
```toml
dynamic = ["version"]
```

并在文件末尾追加：
```toml
[tool.setuptools.dynamic]
version = { attr = "csm_gui._version.__version__" }
```

- [ ] **Step 3: 验证**

```bash
pip install -e .
python -c "import csm_gui._version; print(csm_gui._version.__version__)"
python -c "import csm; print(getattr(csm, '__version__', 'n/a'))" 2>&1 || true
pip show csm | findstr Version
```

预期：版本号都是 `0.1.0`。

- [ ] **Step 4: 创建 CHANGELOG.md**

写文件 `CHANGELOG.md`：

```markdown
# 变更日志

本项目所有可见变更都记录在这里。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Added
- 应用热更新：启动时静默检查 GitHub 私有仓库的最新 Release，发现新版本即弹窗提示，一键升级（独立 updater.exe 接管文件替换）。
- 设置页「关于 CSM」区块：显示当前版本 + 「检查更新」按钮。

## [0.2.0] - 2026-05-07

### Added
- 系统托盘后台运行：关闭按钮默认最小化到托盘，托盘菜单提供新建文章 / 模板 / Skill / 设置 / 退出快捷操作。
- 单实例锁：避免重复双击启动多份 CSM 进程。
- 内容查重：创作区右侧润色按钮下方显示「历史重复率」+「素材引用率」双指标，支持下钻查看 top 3 相似来源 + 命中段落（MinHash + LSH 候选检索 + 13-字 shingling 精算）。

## [0.1.0] - 2026-04-15

### Added
- 项目初版。
```

- [ ] **Step 5: 提交**

```bash
git add csm_gui/_version.py CHANGELOG.md pyproject.toml
git commit -m "feat(version): single-source version + CHANGELOG.md"
```

---

## Task 2: scripts/release_check.py + extract_changelog.py（CI 侧轻量脚本）

**Files:**
- Create: `scripts/release_check.py`
- Create: `scripts/extract_changelog.py`
- Create: `tests/scripts/__init__.py`
- Create: `tests/scripts/test_release_check.py`
- Create: `tests/scripts/test_extract_changelog.py`

- [ ] **Step 1: 写失败测试**

写 `tests/scripts/__init__.py`（空）。

写 `tests/scripts/test_release_check.py`:

```python
"""scripts/release_check.py — verify git tag matches _version.__version__."""
import subprocess
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_check.py"


def _run(tag: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), tag],
        capture_output=True, text=True, cwd=ROOT,
    )


def test_release_check_passes_on_match(monkeypatch, tmp_path):
    """When tag (vX.Y.Z) matches __version__ (X.Y.Z), exit 0."""
    # 先读出当前 __version__；以此 tag 跑应该通过
    from csm_gui._version import __version__
    result = _run(f"v{__version__}")
    assert result.returncode == 0, f"stderr: {result.stderr}"


def test_release_check_fails_on_mismatch():
    """Tag '99.99.99' doesn't match real version → non-zero exit + diagnostic."""
    result = _run("v99.99.99")
    assert result.returncode != 0
    assert "mismatch" in result.stderr.lower() or "mismatch" in result.stdout.lower()


def test_release_check_fails_on_invalid_semver():
    """Tag without v-prefix or with garbage → fails."""
    result = _run("not-a-tag")
    assert result.returncode != 0


def test_release_check_accepts_v_prefix():
    """Both 'v1.2.3' and '1.2.3' should be accepted as input format."""
    from csm_gui._version import __version__
    result = _run(__version__)  # no v-prefix
    assert result.returncode == 0, f"stderr: {result.stderr}"
```

写 `tests/scripts/test_extract_changelog.py`:

```python
"""scripts/extract_changelog.py — extract one version's section from CHANGELOG.md."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "extract_changelog.py"


def _run(version: str, changelog: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), version, str(changelog)],
        capture_output=True, text=True,
    )


def test_extract_extracts_named_section(tmp_path: Path):
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("""# Changelog

## [Unreleased]

### Added
- 未发布的内容

## [0.2.0] - 2026-05-07

### Added
- 系统托盘
- 内容查重

### Fixed
- 修复 XYZ

## [0.1.0] - 2026-04-15

### Added
- 初版
""", encoding="utf-8")
    result = _run("0.2.0", cl)
    assert result.returncode == 0
    assert "系统托盘" in result.stdout
    assert "内容查重" in result.stdout
    # 不应包含别的版本段落
    assert "未发布的内容" not in result.stdout
    assert "初版" not in result.stdout


def test_extract_strips_section_header(tmp_path: Path):
    """The extracted text should be the body, not the '## [0.2.0] - YYYY...' header itself."""
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("""## [0.2.0] - 2026-05-07

### Added
- A
- B

## [0.1.0] - 2026-01-01

- old
""", encoding="utf-8")
    result = _run("0.2.0", cl)
    assert result.returncode == 0
    # 头部行不应出现
    assert "## [0.2.0]" not in result.stdout
    # 内容应出现
    assert "- A" in result.stdout


def test_extract_missing_version_fails(tmp_path: Path):
    cl = tmp_path / "CHANGELOG.md"
    cl.write_text("## [0.1.0] - 2026-01-01\n\n- only\n", encoding="utf-8")
    result = _run("9.9.9", cl)
    assert result.returncode != 0
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/scripts/ -v
```

预期：脚本不存在 → 测试失败。

- [ ] **Step 3: 实现 release_check.py**

写文件 `scripts/release_check.py`:

```python
"""CI guard: verify the git tag being released matches csm_gui._version.__version__.

Usage:
    python scripts/release_check.py <tag-or-version>

Examples:
    python scripts/release_check.py v0.2.0
    python scripts/release_check.py 0.2.0   # v-prefix optional
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Inject project root into path so we can import csm_gui without installing.
sys.path.insert(0, str(ROOT))

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?$")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: release_check.py <tag-or-version>", file=sys.stderr)
        return 2

    raw = argv[1]
    m = SEMVER_RE.match(raw)
    if not m:
        print(f"ERROR: '{raw}' is not a valid semver tag (expected vX.Y.Z)",
              file=sys.stderr)
        return 1
    tag_version = ".".join(m.group(1, 2, 3))

    try:
        from csm_gui._version import __version__
    except ImportError as e:
        print(f"ERROR: cannot import csm_gui._version: {e}", file=sys.stderr)
        return 1

    if tag_version != __version__:
        print(
            f"ERROR: tag/version mismatch — argument='{raw}' "
            f"(parsed={tag_version}) != __version__='{__version__}'",
            file=sys.stderr,
        )
        return 1

    print(f"OK — tag {raw} matches __version__ {__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: 实现 extract_changelog.py**

写文件 `scripts/extract_changelog.py`:

```python
"""Extract one version's section from CHANGELOG.md (Keep a Changelog format).

Usage:
    python scripts/extract_changelog.py <version> [<changelog-path>]

Outputs the section body (between this version's header and the next
``## [...]`` header) to stdout. The version header line itself is excluded.

CI uses this to populate the GitHub Release body from CHANGELOG.md so the
client's "发现新版本" dialog and the Release page show the same notes.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path


def extract(text: str, version: str) -> str | None:
    """Return the body of the [version] section, or None if not found."""
    # Match e.g. ## [0.2.0] - 2026-05-07  (date optional)
    pattern = re.compile(
        rf"^##\s+\[{re.escape(version)}\][^\n]*\n(.*?)(?=^##\s+\[)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(text)
    if m:
        return m.group(1).strip("\n")
    # Last section (no ## after it). Match to EOF.
    pattern_last = re.compile(
        rf"^##\s+\[{re.escape(version)}\][^\n]*\n(.*)\Z",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern_last.search(text)
    if m:
        return m.group(1).strip("\n")
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: extract_changelog.py <version> [<changelog-path>]",
              file=sys.stderr)
        return 2
    version = argv[1].lstrip("v")
    changelog_path = Path(argv[2]) if len(argv) > 2 else Path("CHANGELOG.md")
    if not changelog_path.exists():
        print(f"ERROR: {changelog_path} not found", file=sys.stderr)
        return 1
    text = changelog_path.read_text(encoding="utf-8")
    body = extract(text, version)
    if body is None:
        print(f"ERROR: section [{version}] not found in {changelog_path}",
              file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 5: 跑通过**

```bash
pytest tests/scripts/ -v
```

预期：所有测试 PASS。

- [ ] **Step 6: 提交**

```bash
git add scripts/release_check.py scripts/extract_changelog.py tests/scripts/
git commit -m "feat(release): release_check + extract_changelog CI scripts"
```

---

## Task 3: scripts/build_manifest.py — 生成 manifest.json + SHA256

**Files:**
- Create: `scripts/build_manifest.py`
- Create: `tests/scripts/test_build_manifest.py`

- [ ] **Step 1: 写失败测试**

写 `tests/scripts/test_build_manifest.py`:

```python
"""scripts/build_manifest.py — build a manifest.json from a zip and version."""
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_manifest.py"


def _make_zip(tmp_path: Path) -> Path:
    z = tmp_path / "CSM-v0.2.0.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CSM/dummy.txt", "hi")
    return z


def test_build_manifest_writes_json(tmp_path: Path):
    z = _make_zip(tmp_path)
    out = tmp_path / "manifest.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.2.0", "--zip", str(z),
         "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == "0.2.0"
    assert data["asset_size"] > 0
    assert len(data["sha256"]) == 64  # 64 hex chars
    # SHA256 should match the zip
    expected = hashlib.sha256(z.read_bytes()).hexdigest()
    assert data["sha256"] == expected


def test_build_manifest_includes_released_at(tmp_path: Path):
    z = _make_zip(tmp_path)
    out = tmp_path / "manifest.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.2.0", "--zip", str(z),
         "--out", str(out)],
        check=True, cwd=ROOT,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "released_at" in data
    # ISO 8601 with T
    assert "T" in data["released_at"]


def test_build_manifest_includes_min_compatible(tmp_path: Path):
    """--min-compatible flag is plumbed into manifest."""
    z = _make_zip(tmp_path)
    out = tmp_path / "manifest.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.2.0", "--zip", str(z),
         "--out", str(out), "--min-compatible", "0.1.0"],
        check=True, cwd=ROOT,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["min_compatible_version"] == "0.1.0"
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/scripts/test_build_manifest.py -v
```

- [ ] **Step 3: 实现**

写 `scripts/build_manifest.py`:

```python
"""Generate manifest.json from a release zip + version metadata.

Output schema:
    {
      "version": "0.2.0",
      "released_at": "2026-05-07T08:00:00Z",
      "asset_size": 243814092,
      "sha256": "abc123...",
      "min_compatible_version": "0.1.0"   # optional
    }

CI uploads this manifest alongside the zip in the GitHub Release.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, help="e.g. 0.2.0")
    parser.add_argument("--zip", required=True, type=Path,
                        help="path to the release zip")
    parser.add_argument("--out", required=True, type=Path,
                        help="output manifest.json path")
    parser.add_argument("--min-compatible", default=None,
                        help="optional minimum-compatible version")
    args = parser.parse_args(argv[1:])

    if not args.zip.exists():
        print(f"ERROR: zip not found: {args.zip}", file=sys.stderr)
        return 1

    sha = hashlib.sha256(args.zip.read_bytes()).hexdigest()
    size = args.zip.stat().st_size

    manifest = {
        "version": args.version.lstrip("v"),
        "released_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                                                 .replace("+00:00", "Z"),
        "asset_size": size,
        "sha256": sha,
    }
    if args.min_compatible:
        manifest["min_compatible_version"] = args.min_compatible.lstrip("v")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"OK — wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/scripts/test_build_manifest.py -v
```

- [ ] **Step 5: 提交**

```bash
git add scripts/build_manifest.py tests/scripts/test_build_manifest.py
git commit -m "feat(release): build_manifest.py for SHA256 + version metadata"
```

---

## Task 4: scripts/release.py — 一键发版

**Files:**
- Create: `scripts/release.py`

(测试这个脚本需要 mock git，复杂度高且收益低；用 dry-run 模式 + 手动验证。)

- [ ] **Step 1: 实现**

写文件 `scripts/release.py`:

```python
"""One-click release: bump version, update CHANGELOG, commit, tag, push.

Usage:
    python scripts/release.py 0.2.0           # actually do it
    python scripts/release.py 0.2.0 --dry-run # show what would happen

Steps:
    1. Verify git tree clean + on main/master branch
    2. Verify new version > current __version__ and is valid semver
    3. Write csm_gui/_version.py
    4. Rewrite CHANGELOG.md: rename [Unreleased] → [X.Y.Z] - YYYY-MM-DD,
       insert fresh empty [Unreleased] above it
    5. git add + commit + tag + push origin main + push origin <tag>
    6. Print URL to GitHub Actions for the user to follow
"""
from __future__ import annotations
import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "csm_gui" / "_version.py"
CHANGELOG = ROOT / "CHANGELOG.md"

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?$")


def _git(*args: str, capture: bool = False) -> str:
    out = subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    )
    return out.strip() if capture else ""


def _check_tree_clean() -> None:
    status = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if status.strip():
        print("ERROR: working tree is not clean. Commit or stash first.\n"
              + status, file=sys.stderr)
        sys.exit(1)


def _check_branch() -> None:
    branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, text=True
    ).strip()
    if branch not in ("main", "master"):
        print(f"WARN: not on main/master branch (you are on '{branch}'). "
              "Continue? [y/N] ", end="", flush=True)
        if input().strip().lower() != "y":
            sys.exit(1)


def _read_version() -> str:
    text = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"(\d+\.\d+\.\d+(?:-[\w.]+)?)"', text)
    if not m:
        print(f"ERROR: cannot parse __version__ from {VERSION_FILE}",
              file=sys.stderr)
        sys.exit(1)
    return m.group(1)


def _bump_version(new: str) -> None:
    text = VERSION_FILE.read_text(encoding="utf-8")
    text = re.sub(
        r'__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new}"',
        text,
    )
    VERSION_FILE.write_text(text, encoding="utf-8")


def _bump_changelog(new: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    today = dt.date.today().isoformat()
    # Replace the literal "[Unreleased]" header with [<new>] - <date>,
    # and insert a fresh [Unreleased] above it.
    if "## [Unreleased]" not in text:
        print("ERROR: CHANGELOG.md is missing '## [Unreleased]' section",
              file=sys.stderr)
        sys.exit(1)
    text = text.replace(
        "## [Unreleased]",
        f"## [Unreleased]\n\n## [{new}] - {today}",
        1,
    )
    CHANGELOG.write_text(text, encoding="utf-8")


def _semver_gt(new: str, old: str) -> bool:
    """Strict semver comparison ignoring prerelease tags."""
    n = SEMVER_RE.match(new)
    o = SEMVER_RE.match(old)
    if not n or not o:
        return False
    return tuple(int(x) for x in n.group(1, 2, 3)) > \
           tuple(int(x) for x in o.group(1, 2, 3))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="new version, e.g. 0.2.0")
    parser.add_argument("--dry-run", action="store_true",
                        help="don't write files / git anything; just print")
    parser.add_argument("--allow-non-main", action="store_true",
                        help="skip the main/master check")
    args = parser.parse_args(argv[1:])

    new_version = args.version.lstrip("v")
    if not SEMVER_RE.match(new_version):
        print(f"ERROR: '{args.version}' is not valid semver", file=sys.stderr)
        return 1

    if not args.dry_run:
        _check_tree_clean()
        if not args.allow_non_main:
            _check_branch()

    current = _read_version()
    if not _semver_gt(new_version, current):
        print(f"ERROR: new version {new_version} is not greater than "
              f"current {current}", file=sys.stderr)
        return 1

    print(f"Bumping version: {current} → {new_version}")

    if args.dry_run:
        print("[dry-run] would write _version.py with new version")
        print("[dry-run] would rewrite CHANGELOG.md (Unreleased → "
              f"[{new_version}] - {dt.date.today().isoformat()})")
        print(f"[dry-run] would: git add -A && git commit -m 'release: v{new_version}'")
        print(f"[dry-run] would: git tag v{new_version}")
        print("[dry-run] would: git push origin HEAD --tags")
        return 0

    _bump_version(new_version)
    _bump_changelog(new_version)
    subprocess.check_call(
        ["git", "add", "csm_gui/_version.py", "CHANGELOG.md"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "commit", "-m", f"release: v{new_version}"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "tag", f"v{new_version}"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "push", "origin", "HEAD"], cwd=ROOT,
    )
    subprocess.check_call(
        ["git", "push", "origin", f"v{new_version}"], cwd=ROOT,
    )
    print(f"\n✓ Pushed v{new_version}.\n  Watch CI: "
          "https://github.com/<you>/<repo>/actions  (auto-replace user/repo above)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 2: dry-run 烟测**

```bash
python scripts/release.py 0.2.1 --dry-run --allow-non-main
```

预期：打印各步骤的预期动作，**不**修改任何文件，**不** push。

- [ ] **Step 3: 提交**

```bash
git add scripts/release.py
git commit -m "feat(release): one-click release.py with dry-run"
```

---

## Task 5: csm_core/updater_client/manifest.py + GitHub release JSON 解析

**Files:**
- Create: `csm_core/updater_client/__init__.py`
- Create: `csm_core/updater_client/manifest.py`
- Create: `tests/core/updater_client/__init__.py`
- Create: `tests/core/updater_client/test_manifest.py`

- [ ] **Step 1: 创建空 init**

```bash
mkdir -p csm_core/updater_client tests/core/updater_client
```

写 `csm_core/updater_client/__init__.py`：

```python
"""Update check + download client (GitHub Releases backend)."""
```

写 `tests/core/updater_client/__init__.py`（空）。

- [ ] **Step 2: 写失败测试**

写 `tests/core/updater_client/test_manifest.py`:

```python
"""UpdateInfo + parse GitHub release JSON."""
import pytest
from csm_core.updater_client.manifest import (
    UpdateInfo, parse_release_json, ManifestError,
)


def _release_json(version="0.2.0", manifest_in_assets=True, zip_in_assets=True):
    """Mimic GitHub's /repos/.../releases/latest response."""
    assets = []
    if zip_in_assets:
        assets.append({
            "name": f"CSM-v{version}.zip",
            "size": 232_000_000,
            "browser_download_url": f"https://example.com/CSM-v{version}.zip",
        })
    if manifest_in_assets:
        assets.append({
            "name": "manifest.json",
            "size": 320,
            "browser_download_url": "https://example.com/manifest.json",
        })
    return {
        "tag_name": f"v{version}",
        "name": f"CSM v{version}",
        "body": "### Added\n- 系统托盘\n",
        "published_at": "2026-05-07T08:00:00Z",
        "assets": assets,
    }


def test_parse_release_json_minimal():
    info = parse_release_json(_release_json())
    assert isinstance(info, UpdateInfo)
    assert info.version == "0.2.0"
    assert info.tag_name == "v0.2.0"
    assert info.zip_url.endswith(".zip")
    assert info.manifest_url.endswith("manifest.json")
    assert "系统托盘" in info.changelog
    assert info.published_at == "2026-05-07T08:00:00Z"


def test_parse_release_strips_v_prefix():
    info = parse_release_json(_release_json(version="1.0.0"))
    assert info.version == "1.0.0"


def test_parse_release_missing_zip_raises():
    with pytest.raises(ManifestError):
        parse_release_json(_release_json(zip_in_assets=False))


def test_parse_release_missing_manifest_raises():
    with pytest.raises(ManifestError):
        parse_release_json(_release_json(manifest_in_assets=False))


def test_parse_release_garbage_input_raises():
    with pytest.raises(ManifestError):
        parse_release_json({"unrelated": True})


def test_update_info_has_update_when_newer():
    info = UpdateInfo(
        version="0.2.0", tag_name="v0.2.0",
        zip_url="x", manifest_url="y",
        changelog="cl", published_at="t", asset_size=1,
    )
    assert info.is_newer_than("0.1.0") is True
    assert info.is_newer_than("0.2.0") is False
    assert info.is_newer_than("0.3.0") is False


def test_update_info_handles_v_prefix():
    info = UpdateInfo(
        version="0.2.0", tag_name="v0.2.0",
        zip_url="x", manifest_url="y",
        changelog="cl", published_at="t", asset_size=1,
    )
    assert info.is_newer_than("v0.1.0") is True
```

- [ ] **Step 3: 跑失败**

```bash
pytest tests/core/updater_client/test_manifest.py -v
```

- [ ] **Step 4: 实现**

写 `csm_core/updater_client/manifest.py`:

```python
"""Parse a GitHub /releases/latest JSON into our UpdateInfo dataclass."""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?$")


class ManifestError(Exception):
    """Raised when the GitHub release JSON does not match what we expect."""


@dataclass
class UpdateInfo:
    """Subset of a GitHub release we care about."""
    version: str            # bare X.Y.Z (no v-prefix)
    tag_name: str           # "vX.Y.Z" as GitHub stored it
    zip_url: str            # asset download URL
    manifest_url: str       # asset download URL for manifest.json
    changelog: str          # body markdown
    published_at: str       # ISO timestamp
    asset_size: int         # bytes of the zip

    def is_newer_than(self, other: str) -> bool:
        """Strict semver-tuple compare. v-prefix tolerated on input."""
        a = SEMVER_RE.match(self.version.lstrip("v"))
        b = SEMVER_RE.match(other.lstrip("v"))
        if not a or not b:
            return False
        return tuple(int(x) for x in a.group(1, 2, 3)) > \
               tuple(int(x) for x in b.group(1, 2, 3))


def parse_release_json(payload: dict[str, Any]) -> UpdateInfo:
    """Validate + extract the fields we need from a GitHub release JSON.

    Raises ManifestError if anything required is missing or malformed.
    """
    try:
        tag = payload["tag_name"]
        body = payload.get("body", "") or ""
        published = payload.get("published_at", "") or ""
        assets = payload["assets"]
    except (KeyError, TypeError) as e:
        raise ManifestError(f"missing required release field: {e}") from e

    m = SEMVER_RE.match(tag)
    if not m:
        raise ManifestError(f"tag_name '{tag}' is not valid semver")

    zip_asset = next(
        (a for a in assets if a.get("name", "").endswith(".zip")),
        None,
    )
    if not zip_asset:
        raise ManifestError("release has no .zip asset")

    manifest_asset = next(
        (a for a in assets if a.get("name") == "manifest.json"),
        None,
    )
    if not manifest_asset:
        raise ManifestError("release has no manifest.json asset")

    return UpdateInfo(
        version=".".join(m.group(1, 2, 3)),
        tag_name=tag,
        zip_url=zip_asset["browser_download_url"],
        manifest_url=manifest_asset["browser_download_url"],
        changelog=body,
        published_at=published,
        asset_size=int(zip_asset.get("size", 0)),
    )
```

- [ ] **Step 5: 跑通过**

```bash
pytest tests/core/updater_client/test_manifest.py -v
```

预期：7 PASS。

- [ ] **Step 6: 提交**

```bash
git add csm_core/updater_client/__init__.py csm_core/updater_client/manifest.py tests/core/updater_client/
git commit -m "feat(updater): UpdateInfo + GitHub release JSON parser"
```

---

## Task 6: csm_core/updater_client/github_client.py — httpx + PAT auth

**Files:**
- Create: `csm_core/updater_client/github_client.py`
- Create: `csm_core/updater_client/_token.py.example`
- Modify: `.gitignore`
- Create: `tests/core/updater_client/test_github_client.py`

- [ ] **Step 1: 加 .gitignore**

If `.gitignore` exists, append:
```
csm_core/updater_client/_token.py
```

If it doesn't, create it with that line + standard Python ignores:
```
__pycache__/
*.pyc
.venv/
build/
dist/
*.egg-info/

csm_core/updater_client/_token.py
```

- [ ] **Step 2: 创建 _token.py.example**

写 `csm_core/updater_client/_token.py.example`:

```python
"""Template for the CI-injected GitHub PAT.

Copy this to ``_token.py`` for local testing OR let CI populate it during
the build (the real ``_token.py`` is gitignored).

The PAT must have ``Contents: Read`` permission on the CSM private repo.
"""
TOKEN = ""
```

- [ ] **Step 3: 写失败测试**

写 `tests/core/updater_client/test_github_client.py`:

```python
"""GitHubClient: thin httpx wrapper with PAT auth + error mapping."""
from unittest.mock import patch, MagicMock
import httpx
import pytest
from csm_core.updater_client.github_client import (
    GitHubClient, GitHubAuthError, GitHubNetworkError, GitHubNotFoundError,
)


def _mock_response(status: int, json_data=None, content: bytes = b""):
    r = MagicMock(spec=httpx.Response)
    r.status_code = status
    r.json.return_value = json_data or {}
    r.content = content
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"http {status}", request=MagicMock(), response=r,
        )
    return r


def test_get_latest_release_happy_path():
    client = GitHubClient(repo="zev96/csm", token="t-fake")
    payload = {"tag_name": "v0.2.0", "assets": []}
    with patch("httpx.Client.get", return_value=_mock_response(200, payload)) as mocked:
        result = client.get_latest_release()
    assert result == payload
    args, kwargs = mocked.call_args
    # Authorization header should carry the token
    assert "Authorization" in kwargs.get("headers", {}) or \
           "Authorization" in client._client.headers


def test_get_latest_release_401_raises_auth_error():
    client = GitHubClient(repo="zev96/csm", token="bad")
    with patch("httpx.Client.get", return_value=_mock_response(401)):
        with pytest.raises(GitHubAuthError):
            client.get_latest_release()


def test_get_latest_release_403_raises_auth_error():
    client = GitHubClient(repo="zev96/csm", token="rate-limited")
    with patch("httpx.Client.get", return_value=_mock_response(403)):
        with pytest.raises(GitHubAuthError):
            client.get_latest_release()


def test_get_latest_release_404_raises_not_found():
    client = GitHubClient(repo="zev96/csm", token="t")
    with patch("httpx.Client.get", return_value=_mock_response(404)):
        with pytest.raises(GitHubNotFoundError):
            client.get_latest_release()


def test_get_latest_release_network_error():
    client = GitHubClient(repo="zev96/csm", token="t")
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("dns")):
        with pytest.raises(GitHubNetworkError):
            client.get_latest_release()


def test_empty_token_works_for_public_unauth_calls():
    """If TOKEN is empty (e.g. local dev w/o injection), client still constructs."""
    client = GitHubClient(repo="zev96/csm", token="")
    # No exception
    assert client._client is not None
```

- [ ] **Step 4: 跑失败**

```bash
pytest tests/core/updater_client/test_github_client.py -v
```

- [ ] **Step 5: 实现**

写 `csm_core/updater_client/github_client.py`:

```python
"""Thin httpx wrapper around the GitHub REST API.

We only use one endpoint: GET /repos/{owner}/{repo}/releases/latest.
Wraps it with PAT auth + maps HTTP errors to our own exception hierarchy
so the caller (checker.py) can decide what to do.
"""
from __future__ import annotations
from typing import Any

import httpx

DEFAULT_TIMEOUT = 5.0  # seconds


class GitHubError(Exception):
    """Base class for GitHub API errors surfaced to the rest of CSM."""


class GitHubAuthError(GitHubError):
    """401 / 403 — token missing, expired, or rate-limited."""


class GitHubNotFoundError(GitHubError):
    """404 — repo doesn't exist or no releases yet."""


class GitHubNetworkError(GitHubError):
    """DNS / TCP / TLS failure or timeout."""


class GitHubClient:
    """GitHub release reader. Token-optional (anonymous works for public repos)."""

    def __init__(self, repo: str, token: str = "",
                 timeout: float = DEFAULT_TIMEOUT):
        """``repo`` is "<owner>/<name>" (e.g. "zev96/csm")."""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._repo = repo
        self._client = httpx.Client(
            base_url="https://api.github.com",
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def get_latest_release(self) -> dict[str, Any]:
        url = f"/repos/{self._repo}/releases/latest"
        try:
            resp = self._client.get(url)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError) as e:
            raise GitHubNetworkError(str(e)) from e
        if resp.status_code in (401, 403):
            raise GitHubAuthError(f"GitHub returned HTTP {resp.status_code}")
        if resp.status_code == 404:
            raise GitHubNotFoundError(
                f"no releases found for {self._repo}")
        if resp.status_code >= 400:
            raise GitHubError(f"unexpected HTTP {resp.status_code}")
        return resp.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
```

- [ ] **Step 6: 跑通过**

```bash
pytest tests/core/updater_client/test_github_client.py -v
```

预期：6 PASS。

- [ ] **Step 7: 提交**

```bash
git add .gitignore csm_core/updater_client/_token.py.example csm_core/updater_client/github_client.py tests/core/updater_client/test_github_client.py
git commit -m "feat(updater): GitHubClient with PAT auth + error mapping"
```

---

## Task 7: csm_core/updater_client/checker.py — check_for_update 编排

**Files:**
- Create: `csm_core/updater_client/checker.py`
- Create: `tests/core/updater_client/test_checker.py`

- [ ] **Step 1: 写失败测试**

写 `tests/core/updater_client/test_checker.py`:

```python
"""check_for_update: orchestrates GitHubClient → manifest.parse → UpdateInfo."""
from unittest.mock import patch, MagicMock
import pytest
from csm_core.updater_client.checker import (
    check_for_update, CheckResult,
)
from csm_core.updater_client.github_client import (
    GitHubAuthError, GitHubNetworkError, GitHubNotFoundError,
)


def _release(version="0.2.0"):
    return {
        "tag_name": f"v{version}",
        "name": f"CSM v{version}",
        "body": "notes",
        "published_at": "2026-05-07T08:00:00Z",
        "assets": [
            {"name": f"CSM-v{version}.zip",
             "size": 1, "browser_download_url": "u1"},
            {"name": "manifest.json",
             "size": 1, "browser_download_url": "u2"},
        ],
    }


def test_check_finds_newer():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.return_value = _release("0.2.0")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.1.0")
    assert isinstance(result, CheckResult)
    assert result.has_update is True
    assert result.info is not None
    assert result.info.version == "0.2.0"
    assert result.error is None


def test_check_already_at_latest():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.return_value = _release("0.2.0")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.2.0")
    assert result.has_update is False
    assert result.info is not None  # still surfaced for "已是最新" message
    assert result.error is None


def test_check_handles_network_error():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.side_effect = GitHubNetworkError("dns")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.1.0")
    assert result.has_update is False
    assert result.info is None
    assert result.error is not None
    assert "network" in result.error.lower() or "dns" in result.error.lower()


def test_check_handles_auth_error():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.side_effect = GitHubAuthError("401")
        result = check_for_update(repo="x/y", token="bad",
                                  current_version="0.1.0")
    assert result.has_update is False
    assert "auth" in result.error.lower()


def test_check_handles_not_found():
    with patch("csm_core.updater_client.checker.GitHubClient") as Cls:
        inst = Cls.return_value.__enter__.return_value
        inst.get_latest_release.side_effect = GitHubNotFoundError("404")
        result = check_for_update(repo="x/y", token="t",
                                  current_version="0.1.0")
    assert result.has_update is False
    assert "not" in result.error.lower() or "404" in result.error
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/core/updater_client/test_checker.py -v
```

- [ ] **Step 3: 实现**

写 `csm_core/updater_client/checker.py`:

```python
"""check_for_update: one-shot orchestration of GitHub client + manifest parse.

Returns a CheckResult that the GUI can interpret without knowing about the
underlying httpx / parser exceptions.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from .github_client import (
    GitHubClient, GitHubAuthError, GitHubNetworkError, GitHubNotFoundError,
    GitHubError,
)
from .manifest import UpdateInfo, parse_release_json, ManifestError

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Outcome of one check_for_update call."""
    has_update: bool
    info: UpdateInfo | None
    error: str | None  # human-readable message, None on success


def check_for_update(
    *, repo: str, token: str, current_version: str,
    timeout: float = 5.0,
) -> CheckResult:
    """Check the latest release of ``repo`` against ``current_version``.

    On any failure (network / auth / parse), returns a CheckResult with
    ``error`` set to a human-readable string. The caller decides whether to
    show the user a notification or stay silent.
    """
    try:
        with GitHubClient(repo=repo, token=token, timeout=timeout) as gh:
            payload = gh.get_latest_release()
    except GitHubAuthError as e:
        return CheckResult(False, None, f"auth failed: {e}")
    except GitHubNotFoundError as e:
        return CheckResult(False, None, f"not found: {e}")
    except GitHubNetworkError as e:
        return CheckResult(False, None, f"network error: {e}")
    except GitHubError as e:
        return CheckResult(False, None, f"github error: {e}")

    try:
        info = parse_release_json(payload)
    except ManifestError as e:
        return CheckResult(False, None, f"manifest error: {e}")

    has_update = info.is_newer_than(current_version)
    return CheckResult(has_update=has_update, info=info, error=None)
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/core/updater_client/test_checker.py -v
```

预期：5 PASS.

- [ ] **Step 5: 提交**

```bash
git add csm_core/updater_client/checker.py tests/core/updater_client/test_checker.py
git commit -m "feat(updater): check_for_update orchestrating client + parser"
```

---

## Task 8: csm_core/updater_client/downloader.py — 流式下载 + SHA256

**Files:**
- Create: `csm_core/updater_client/downloader.py`
- Create: `tests/core/updater_client/test_downloader.py`

- [ ] **Step 1: 写失败测试**

写 `tests/core/updater_client/test_downloader.py`:

```python
"""Streaming downloader with SHA256 verification."""
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx
import pytest
from csm_core.updater_client.downloader import (
    download_with_verification, DownloadError, DownloadCancelled,
)


def _mock_streaming_response(content: bytes, status: int = 200):
    """Mimic an httpx.Client.stream() context manager response."""
    resp = MagicMock()
    resp.status_code = status
    # Iterate yields chunks
    resp.iter_bytes.return_value = iter([content[i:i+8192] for i in range(0, len(content), 8192)])
    resp.headers = {"content-length": str(len(content))}
    return resp


def _patch_stream(content: bytes, status: int = 200):
    """Patch httpx.Client to yield a streaming response."""
    resp = _mock_streaming_response(content, status)
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = None
    return patch("httpx.Client.stream", return_value=cm)


def test_download_writes_file_and_returns_sha(tmp_path: Path):
    content = b"hello world" * 100
    expected_sha = hashlib.sha256(content).hexdigest()
    out = tmp_path / "out.zip"

    with _patch_stream(content):
        sha = download_with_verification(
            url="https://x/y.zip",
            target=out,
            expected_sha256=expected_sha,
        )
    assert sha == expected_sha
    assert out.read_bytes() == content


def test_download_sha_mismatch_raises_and_deletes(tmp_path: Path):
    content = b"actual content" * 50
    out = tmp_path / "out.zip"

    with _patch_stream(content):
        with pytest.raises(DownloadError, match="sha256"):
            download_with_verification(
                url="https://x/y.zip",
                target=out,
                expected_sha256="0" * 64,
            )
    # 校验失败后文件应被删除
    assert not out.exists()


def test_download_progress_callback(tmp_path: Path):
    content = b"a" * 10000
    sha = hashlib.sha256(content).hexdigest()
    out = tmp_path / "out.zip"
    progress_calls = []

    with _patch_stream(content):
        download_with_verification(
            url="x", target=out, expected_sha256=sha,
            progress_cb=lambda done, total: progress_calls.append((done, total)),
        )
    assert progress_calls
    # 最后一次回调应到达 total
    last = progress_calls[-1]
    assert last[0] == last[1] == 10000


def test_download_cancellation(tmp_path: Path):
    content = b"x" * 100000
    sha = hashlib.sha256(content).hexdigest()
    out = tmp_path / "out.zip"

    cancelled = [False]
    def is_cancelled():
        if not cancelled[0]:
            cancelled[0] = True
            return False
        return True

    with _patch_stream(content):
        with pytest.raises(DownloadCancelled):
            download_with_verification(
                url="x", target=out, expected_sha256=sha,
                is_cancelled=is_cancelled,
            )
    assert not out.exists()


def test_download_http_error_raises(tmp_path: Path):
    out = tmp_path / "out.zip"
    with _patch_stream(b"", status=500):
        with pytest.raises(DownloadError):
            download_with_verification(
                url="x", target=out, expected_sha256="0" * 64,
            )
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/core/updater_client/test_downloader.py -v
```

- [ ] **Step 3: 实现**

写 `csm_core/updater_client/downloader.py`:

```python
"""Stream-download a file + verify SHA256.

Designed for the GUI: emits progress periodically via a callback, supports
cooperative cancellation via a polling lambda, and atomically deletes the
target on any failure (including SHA mismatch and user cancel) so the
client never sees a half-written zip.
"""
from __future__ import annotations
import hashlib
import logging
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

CHUNK_SIZE = 8192   # bytes — keeps mem usage flat
PROGRESS_INTERVAL = 256 * 1024  # ~256 KB between callbacks


class DownloadError(Exception):
    """Network failure / HTTP error / SHA mismatch."""


class DownloadCancelled(Exception):
    """User cancelled the download mid-stream."""


def download_with_verification(
    *,
    url: str,
    target: Path,
    expected_sha256: str,
    progress_cb: Callable[[int, int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    timeout: float = 60.0,
) -> str:
    """Download ``url`` to ``target`` and verify SHA256.

    ``progress_cb(done_bytes, total_bytes)`` is called every ``PROGRESS_INTERVAL``
    bytes. ``is_cancelled()`` is polled every chunk; if it returns True we
    raise ``DownloadCancelled`` and delete any partial file.

    Returns the actual computed SHA256 hex string on success.

    Raises:
        DownloadError on network / HTTP / SHA failure
        DownloadCancelled on cooperative cancel
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    total = 0
    bytes_since_progress = 0

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise DownloadError(
                        f"HTTP {resp.status_code} from {url}")
                content_length = int(resp.headers.get("content-length", 0))
                with open(target, "wb") as f:
                    for chunk in resp.iter_bytes(CHUNK_SIZE):
                        if is_cancelled and is_cancelled():
                            raise DownloadCancelled()
                        if not chunk:
                            continue
                        f.write(chunk)
                        hasher.update(chunk)
                        total += len(chunk)
                        bytes_since_progress += len(chunk)
                        if progress_cb and bytes_since_progress >= PROGRESS_INTERVAL:
                            progress_cb(total, content_length or total)
                            bytes_since_progress = 0
                # Final progress at 100%
                if progress_cb:
                    progress_cb(total, content_length or total)
    except httpx.HTTPError as e:
        _cleanup(target)
        raise DownloadError(str(e)) from e
    except DownloadCancelled:
        _cleanup(target)
        raise
    except DownloadError:
        _cleanup(target)
        raise

    actual_sha = hasher.hexdigest()
    if actual_sha != expected_sha256:
        _cleanup(target)
        raise DownloadError(
            f"sha256 mismatch — expected {expected_sha256}, got {actual_sha}"
        )
    return actual_sha


def _cleanup(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as e:
        logger.warning("downloader: failed to clean %s — %s", path, e)
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/core/updater_client/test_downloader.py -v
```

预期：5 PASS.

- [ ] **Step 5: 提交**

```bash
git add csm_core/updater_client/downloader.py tests/core/updater_client/test_downloader.py
git commit -m "feat(updater): streaming downloader with SHA256 verification"
```

---

## Task 9: csm_gui/widgets/update_dialog.py — 发现新版本对话框

**Files:**
- Create: `csm_gui/widgets/update_dialog.py`
- Create: `tests/gui/test_update_dialog.py`

- [ ] **Step 1: 写失败测试**

写 `tests/gui/test_update_dialog.py`:

```python
"""UpdateDialog: shows version info + changelog + "立即升级 / 稍后再说" buttons."""
from csm_gui.widgets.update_dialog import UpdateDialog
from csm_core.updater_client.manifest import UpdateInfo


def _info(version="0.2.0"):
    return UpdateInfo(
        version=version, tag_name=f"v{version}",
        zip_url="u", manifest_url="m",
        changelog="### Added\n- 系统托盘\n- 内容查重\n",
        published_at="2026-05-07T08:00:00Z", asset_size=1_000_000,
    )


def test_dialog_renders_versions(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    text = dlg.summary_label.text()
    assert "0.1.0" in text
    assert "0.2.0" in text


def test_dialog_renders_changelog(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    cl = dlg.changelog_view.toPlainText() if hasattr(dlg.changelog_view, "toPlainText") else dlg.changelog_view.text()
    assert "系统托盘" in cl


def test_dialog_upgrade_button_emits(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.upgrade_requested, timeout=1000):
        dlg.upgrade_button.click()


def test_dialog_later_button_closes(qtbot):
    dlg = UpdateDialog(info=_info(), current_version="0.1.0")
    qtbot.addWidget(dlg)
    dlg.later_button.click()
    # later button rejects the dialog
    assert dlg.result() == 0  # QDialog.Rejected
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_update_dialog.py -v
```

- [ ] **Step 3: 实现**

写 `csm_gui/widgets/update_dialog.py`:

```python
"""UpdateDialog — modal: 'Found new version' with changelog + buttons."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton,
)
from qfluentwidgets import StrongBodyLabel, BodyLabel, PrimaryPushButton

from csm_core.updater_client.manifest import UpdateInfo


class UpdateDialog(QDialog):
    """Shows new-version notice + changelog. Two buttons: 立即升级 / 稍后再说."""

    upgrade_requested = pyqtSignal()

    def __init__(self, info: UpdateInfo, current_version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发现新版本")
        self.resize(620, 480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        # Header summary
        self.summary_label = StrongBodyLabel(
            f"新版本：v{info.version}    （当前：v{current_version}）",
            self,
        )
        root.addWidget(self.summary_label)

        published = BodyLabel(f"发布时间：{info.published_at}", self)
        root.addWidget(published)

        # Changelog (rendered as plain markdown text)
        cl_label = StrongBodyLabel("变更日志", self)
        root.addWidget(cl_label)

        self.changelog_view = QTextBrowser(self)
        self.changelog_view.setOpenExternalLinks(True)
        self.changelog_view.setMarkdown(info.changelog or "(无)")
        root.addWidget(self.changelog_view, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.later_button = QPushButton("稍后再说", self)
        self.later_button.clicked.connect(self.reject)
        btn_row.addWidget(self.later_button)
        self.upgrade_button = PrimaryPushButton("立即升级", self)
        self.upgrade_button.clicked.connect(self._on_upgrade)
        btn_row.addWidget(self.upgrade_button)
        root.addLayout(btn_row)

    def _on_upgrade(self) -> None:
        self.upgrade_requested.emit()
        self.accept()
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_update_dialog.py -v
```

预期：4 PASS.

- [ ] **Step 5: 提交**

```bash
git add csm_gui/widgets/update_dialog.py tests/gui/test_update_dialog.py
git commit -m "feat(updater): 'Found new version' dialog with changelog"
```

---

## Task 10: csm_gui/widgets/update_progress_dialog.py — 下载进度对话框

**Files:**
- Create: `csm_gui/widgets/update_progress_dialog.py`
- Create: `tests/gui/test_update_progress_dialog.py`

- [ ] **Step 1: 写失败测试**

写 `tests/gui/test_update_progress_dialog.py`:

```python
"""UpdateProgressDialog: progress bar + cancel button + speed display."""
from csm_gui.widgets.update_progress_dialog import UpdateProgressDialog


def test_progress_dialog_initial_state(qtbot):
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    assert dlg.progress_bar.value() == 0
    assert dlg.cancel_button.isEnabled()


def test_progress_dialog_set_progress(qtbot):
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    dlg.set_progress(500_000, 1_000_000)
    assert dlg.progress_bar.value() == 50  # percent


def test_progress_dialog_set_progress_unknown_total(qtbot):
    """If total is 0/unknown, still don't crash; show indeterminate."""
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    dlg.set_progress(500_000, 0)
    # No assertion on bar — just verify no exception


def test_progress_dialog_cancel_emits(qtbot):
    dlg = UpdateProgressDialog()
    qtbot.addWidget(dlg)
    with qtbot.waitSignal(dlg.cancel_requested, timeout=1000):
        dlg.cancel_button.click()
    assert dlg.is_cancelled() is True
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_update_progress_dialog.py -v
```

- [ ] **Step 3: 实现**

写 `csm_gui/widgets/update_progress_dialog.py`:

```python
"""UpdateProgressDialog — modal progress + cancel during download."""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QProgressBar, QPushButton,
)
from qfluentwidgets import BodyLabel


def _human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    f = float(n)
    for u in units:
        if f < 1024 or u == "GB":
            return f"{f:.1f} {u}"
        f /= 1024
    return f"{f:.1f} GB"


class UpdateProgressDialog(QDialog):
    """Progress dialog used during the download phase."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("正在下载新版本")
        self.setMinimumWidth(420)
        self._cancelled = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        self.status_label = BodyLabel("准备下载…", self)
        root.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        root.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_button = QPushButton("取消", self)
        self.cancel_button.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.cancel_button)
        root.addLayout(btn_row)

    def set_progress(self, done: int, total: int) -> None:
        if total > 0:
            pct = min(100, int(done * 100 / total))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.status_label.setText(
                f"已下载 {_human_bytes(done)} / {_human_bytes(total)} ({pct}%)"
            )
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate
            self.status_label.setText(f"已下载 {_human_bytes(done)}")

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _on_cancel(self) -> None:
        self._cancelled = True
        self.cancel_button.setEnabled(False)
        self.status_label.setText("正在取消…")
        self.cancel_requested.emit()
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_update_progress_dialog.py -v
```

预期：4 PASS.

- [ ] **Step 5: 提交**

```bash
git add csm_gui/widgets/update_progress_dialog.py tests/gui/test_update_progress_dialog.py
git commit -m "feat(updater): UpdateProgressDialog with cancel + speed display"
```

---

## Task 11: csm_gui/workers/update_check_worker.py — 后台启动检查 QThread

**Files:**
- Create: `csm_gui/workers/update_check_worker.py`
- Create: `tests/gui/test_update_check_worker.py`

- [ ] **Step 1: 写失败测试**

写 `tests/gui/test_update_check_worker.py`:

```python
"""UpdateCheckWorker: runs check_for_update in a QThread."""
from unittest.mock import patch
from csm_gui.workers.update_check_worker import UpdateCheckWorker
from csm_core.updater_client.checker import CheckResult
from csm_core.updater_client.manifest import UpdateInfo


def _info(version="0.2.0"):
    return UpdateInfo(
        version=version, tag_name=f"v{version}",
        zip_url="u", manifest_url="m",
        changelog="cl", published_at="t", asset_size=1,
    )


def test_check_worker_emits_finished_with_result(qtbot):
    fake = CheckResult(has_update=True, info=_info(), error=None)
    with patch("csm_gui.workers.update_check_worker.check_for_update",
               return_value=fake):
        worker = UpdateCheckWorker(
            repo="x/y", token="t", current_version="0.1.0",
        )
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
    assert blocker.args[0] is fake


def test_check_worker_emits_on_error_too(qtbot):
    """If checker raises, worker still emits a CheckResult with error set."""
    err_result = CheckResult(False, None, "network: dns failed")
    with patch("csm_gui.workers.update_check_worker.check_for_update",
               return_value=err_result):
        worker = UpdateCheckWorker(
            repo="x/y", token="t", current_version="0.1.0",
        )
        with qtbot.waitSignal(worker.finished, timeout=5000) as blocker:
            worker.start()
    result = blocker.args[0]
    assert result.has_update is False
    assert result.error is not None
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_update_check_worker.py -v
```

- [ ] **Step 3: 实现**

写 `csm_gui/workers/update_check_worker.py`:

```python
"""QThread wrapper for the (synchronous httpx) update check."""
from __future__ import annotations
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from csm_core.updater_client.checker import CheckResult, check_for_update

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    """Run check_for_update off the UI thread. Emits finished(CheckResult)."""

    finished = pyqtSignal(CheckResult)

    def __init__(self, *, repo: str, token: str, current_version: str,
                 timeout: float = 5.0, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._token = token
        self._current = current_version
        self._timeout = timeout

    def run(self) -> None:
        try:
            result = check_for_update(
                repo=self._repo,
                token=self._token,
                current_version=self._current,
                timeout=self._timeout,
            )
        except Exception as exc:
            logger.warning("UpdateCheckWorker unexpected error: %s", exc)
            result = CheckResult(False, None, f"unexpected: {exc}")
        self.finished.emit(result)
```

- [ ] **Step 4: 跑通过**

```bash
pytest tests/gui/test_update_check_worker.py -v
```

预期：2 PASS.

- [ ] **Step 5: 提交**

```bash
git add csm_gui/workers/update_check_worker.py tests/gui/test_update_check_worker.py
git commit -m "feat(updater): QThread worker for background update check"
```

---

## Task 12: SettingsPage 加「关于」section + 检查更新按钮

**Files:**
- Modify: `csm_gui/pages/settings_page.py`
- Modify: `tests/gui/test_settings_page.py`

- [ ] **Step 1: 探查（必读）**

Read `csm_gui/pages/settings_page.py` to find the existing card-add idiom (you found it in Task 12 of feature 2: `_SettingsCard("name", "subtitle")` + `_SettingsRow` + `set_control()` + `self._add_panel(self._build_X())` registered into `_GROUPS`).

- [ ] **Step 2: 写失败测试**

Append to `tests/gui/test_settings_page.py`:

```python
def test_settings_page_has_about_section(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    cfg = AppConfig()
    page = SettingsPage(config=cfg, on_save=lambda c: None)
    qtbot.addWidget(page)
    assert hasattr(page, "current_version_label")
    assert hasattr(page, "check_update_button")


def test_settings_page_about_shows_current_version(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    from csm_gui._version import __version__
    page = SettingsPage(config=AppConfig(), on_save=lambda c: None)
    qtbot.addWidget(page)
    assert __version__ in page.current_version_label.text()


def test_settings_page_check_update_emits_signal(qtbot):
    from csm_gui.config import AppConfig
    from csm_gui.pages.settings_page import SettingsPage
    page = SettingsPage(config=AppConfig(), on_save=lambda c: None)
    qtbot.addWidget(page)
    with qtbot.waitSignal(page.check_update_requested, timeout=1000):
        page.check_update_button.click()
```

- [ ] **Step 3: 跑失败**

```bash
pytest tests/gui/test_settings_page.py -k about -v
```

- [ ] **Step 4: 实现**

In `csm_gui/pages/settings_page.py`:

a) **Add signal**:
```python
class SettingsPage(QWidget):
    # ...existing signals...
    check_update_requested = pyqtSignal()
```

b) **Add `_build_about` method**:

```python
    def _build_about(self) -> None:
        """关于 CSM section — current version + check for update button."""
        from csm_gui._version import __version__
        card = _SettingsCard("关于 CSM", "版本信息与更新")

        row_ver = _SettingsRow("当前版本")
        self.current_version_label = BodyLabel(f"v{__version__}", self)
        row_ver.set_control(self.current_version_label)
        card.add_row(row_ver)

        row_btn = _SettingsRow("更新")
        self.check_update_button = PushButton("检查更新", self)
        self.check_update_button.clicked.connect(
            self.check_update_requested.emit
        )
        row_btn.set_control(self.check_update_button)
        card.add_row(row_btn)

        self._add_card(card)  # use the file's actual card-add idiom
```

c) **Call `self._build_about()` in `__init__`** at the end of build sequence.

d) **Add navigation entry** in `_GROUPS` (if applicable):

```python
("about", "关于", FluentIcon.INFO),
```

(Use whatever icon is appropriate — INFO or HELP fits.)

- [ ] **Step 5: 跑通过**

```bash
pytest tests/gui/test_settings_page.py -v
```

预期：3 new + all existing PASS.

- [ ] **Step 6: 提交**

```bash
git add csm_gui/pages/settings_page.py tests/gui/test_settings_page.py
git commit -m "feat(settings): about section with current version + check update button"
```

---

## Task 13: MainWindow 集成 — 启动检查 + 升级流程接线

**Files:**
- Modify: `csm_gui/main_window.py`
- Modify: `tests/gui/test_main_window.py`

- [ ] **Step 1: 写失败测试**

Append to `tests/gui/test_main_window.py`:

```python
def test_main_window_check_update_button_dispatches(qtbot, tmp_path, monkeypatch):
    """Settings page emits check_update_requested → MainWindow starts a worker."""
    from csm_gui.main_window import MainWindow
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)

    started = []
    monkeypatch.setattr(win, "_start_update_check_manual",
                        lambda: started.append(True))
    win.settings.check_update_requested.emit()
    assert started == [True]


def test_main_window_handles_update_check_no_update(qtbot, tmp_path):
    """When CheckResult has no update, no dialog should be shown."""
    from csm_gui.main_window import MainWindow
    from csm_core.updater_client.checker import CheckResult
    win = MainWindow(config_dir=tmp_path)
    qtbot.addWidget(win)
    # Should not crash; explicit no-update path
    win._on_update_check_done(CheckResult(False, None, None), is_manual=False)
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/gui/test_main_window.py -k update_check -v
```

- [ ] **Step 3: 实现 — MainWindow 改动**

In `csm_gui/main_window.py`:

a) **Top imports** (after existing):

```python
from csm_gui._version import __version__
from .workers.update_check_worker import UpdateCheckWorker
from .widgets.update_dialog import UpdateDialog
from .widgets.update_progress_dialog import UpdateProgressDialog
```

b) **GitHub repo + token constants** (near top of file, after imports):

```python
# Hard-coded for now — user's private CSM repo. Adjust during release prep.
_GITHUB_REPO = "zev96/csm"

def _read_token() -> str:
    """Read the CI-injected PAT, return '' if not present (local dev)."""
    try:
        from csm_core.updater_client._token import TOKEN
        return TOKEN
    except ImportError:
        return ""
```

c) **In `__init__`** — at the end:

```python
        # ── Update checker ───────────────────────────────────────────
        self._update_workers: list = []
        self.settings.check_update_requested.connect(
            self._start_update_check_manual
        )
        # Silent check 2 seconds after startup
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, self._start_update_check_silent)
```

d) **Add new methods**:

```python
    def _start_update_check_silent(self) -> None:
        self._dispatch_update_check(is_manual=False)

    def _start_update_check_manual(self) -> None:
        self._dispatch_update_check(is_manual=True)

    def _dispatch_update_check(self, *, is_manual: bool) -> None:
        worker = UpdateCheckWorker(
            repo=_GITHUB_REPO,
            token=_read_token(),
            current_version=__version__,
            parent=self,
        )
        worker.finished.connect(
            lambda result, m=is_manual: self._on_update_check_done(result, is_manual=m)
        )
        worker.finished.connect(
            lambda *_: self._update_workers.remove(worker)
            if worker in self._update_workers else None
        )
        self._update_workers.append(worker)
        worker.start()

    def _on_update_check_done(self, result, *, is_manual: bool) -> None:
        from qfluentwidgets import InfoBar, InfoBarPosition
        if result.error:
            if is_manual:
                InfoBar.error("检查更新失败", result.error,
                              parent=self, position=InfoBarPosition.TOP, duration=4000)
            return
        if not result.has_update:
            if is_manual:
                InfoBar.success(
                    "已是最新", f"当前版本 v{__version__} 已是最新",
                    parent=self, position=InfoBarPosition.TOP, duration=3000)
            return
        # 弹升级对话框
        info = result.info
        dlg = UpdateDialog(info=info, current_version=__version__, parent=self)
        dlg.upgrade_requested.connect(lambda i=info: self._on_upgrade_clicked(i))
        dlg.exec()

    def _on_upgrade_clicked(self, info) -> None:
        """User clicked '立即升级'. Download zip, then spawn updater.exe."""
        from csm_core.updater_client.downloader import (
            download_with_verification, DownloadError, DownloadCancelled,
        )
        import os
        import sys
        import tempfile
        import subprocess
        from pathlib import Path
        # Read SHA256 from manifest (HTTP GET manifest_url, parse JSON)
        import httpx
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True,
                              headers={"Authorization": f"Bearer {_read_token()}"}
                              if _read_token() else {}) as c:
                m = c.get(info.manifest_url).json()
            expected_sha = m["sha256"]
        except Exception as e:
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error("升级失败", f"无法读取 manifest: {e}",
                          parent=self, position=InfoBarPosition.TOP, duration=4000)
            return

        # Show progress dialog + start download
        progress = UpdateProgressDialog(self)
        zip_path = Path(tempfile.gettempdir()) / "csm_update" / f"CSM-{info.tag_name}.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        # Download in a thread so UI stays responsive
        from PyQt6.QtCore import QThread, pyqtSignal as _sig
        class _DownloadThread(QThread):
            finished_ok = _sig(str)
            failed = _sig(str)
            cancelled = _sig()
            progress = _sig(int, int)

            def __init__(self, url, target, sha, parent=None):
                super().__init__(parent)
                self._url, self._target, self._sha = url, target, sha
                self._cancel = False

            def cancel(self): self._cancel = True

            def run(self):
                try:
                    download_with_verification(
                        url=self._url, target=self._target,
                        expected_sha256=self._sha,
                        progress_cb=lambda d, t: self.progress.emit(d, t),
                        is_cancelled=lambda: self._cancel,
                    )
                    self.finished_ok.emit(str(self._target))
                except DownloadCancelled:
                    self.cancelled.emit()
                except DownloadError as e:
                    self.failed.emit(str(e))

        dl = _DownloadThread(info.zip_url, zip_path, expected_sha, parent=self)
        dl.progress.connect(progress.set_progress)
        dl.finished_ok.connect(lambda p: self._on_download_ok(progress, info, Path(p)))
        dl.failed.connect(lambda msg: self._on_download_failed(progress, msg))
        dl.cancelled.connect(lambda: progress.reject())
        progress.cancel_requested.connect(dl.cancel)
        self._update_workers.append(dl)
        dl.start()
        progress.exec()

    def _on_download_ok(self, progress_dlg, info, zip_path) -> None:
        progress_dlg.accept()
        # Locate updater.exe (sibling of CSM.exe in onedir layout)
        import sys
        from pathlib import Path
        if hasattr(sys, "frozen") and getattr(sys, "frozen"):
            exe_dir = Path(sys.executable).parent
            updater = exe_dir / "updater.exe"
        else:
            # Dev mode — point to the source updater path
            updater = Path(__file__).resolve().parents[1] / "updater" / "main.py"
        if not updater.exists():
            from qfluentwidgets import InfoBar, InfoBarPosition
            InfoBar.error("升级失败", f"updater 不存在: {updater}",
                          parent=self, position=InfoBarPosition.TOP, duration=5000)
            return
        # Spawn updater + exit main process
        import os, subprocess
        target_dir = exe_dir if hasattr(sys, "frozen") else Path.cwd()
        cmd = [str(updater) if updater.suffix == ".exe" else sys.executable,
               *([] if updater.suffix == ".exe" else [str(updater)]),
               "--pid", str(os.getpid()),
               "--zip", str(zip_path),
               "--target", str(target_dir)]
        subprocess.Popen(cmd, close_fds=True)
        # Exit the main process so updater can replace files
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _on_download_failed(self, progress_dlg, msg: str) -> None:
        progress_dlg.reject()
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.error("下载失败", msg,
                      parent=self, position=InfoBarPosition.TOP, duration=5000)
```

- [ ] **Step 4: 跑测试**

```bash
pytest tests/gui/test_main_window.py --deselect tests/gui/test_main_window.py::test_export_action_writes_files -v
```

预期：所有测试 PASS（除 pre-existing 失败）。

- [ ] **Step 5: 提交**

```bash
git add csm_gui/main_window.py tests/gui/test_main_window.py
git commit -m "feat(updater): wire MainWindow update check + upgrade flow"
```

---

## Task 14: updater/main.py + updater/updater.spec

**Files:**
- Create: `updater/__init__.py`（空）
- Create: `updater/main.py`
- Create: `updater/updater.spec`
- Create: `tests/updater/__init__.py`
- Create: `tests/updater/test_updater_main.py`

- [ ] **Step 1: 写失败测试（核心逻辑可单测，不需要 PyInstaller）**

写 `tests/updater/__init__.py`（空）。

写 `tests/updater/test_updater_main.py`:

```python
"""Updater core logic — file replacement + rollback."""
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch
import pytest


def _make_zip(tmp_path: Path, name: str = "test.zip") -> Path:
    z = tmp_path / name
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CSM/CSM.exe", "fake new exe content")
        zf.writestr("CSM/data.txt", "new data")
    return z


def test_replace_directory_atomic(tmp_path: Path):
    """replace_directory: backup → extract → move → cleanup."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater.main import replace_directory

    target = tmp_path / "CSM"
    target.mkdir()
    (target / "CSM.exe").write_text("old", encoding="utf-8")

    z = _make_zip(tmp_path)

    replace_directory(target=target, zip_path=z)
    # New content should be in place
    assert (target / "CSM.exe").read_text(encoding="utf-8") == "fake new exe content"
    assert (target / "data.txt").read_text(encoding="utf-8") == "new data"


def test_replace_rolls_back_on_failure(tmp_path: Path, monkeypatch):
    """If extraction or move fails, .bak is restored."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater import main as updater_main

    target = tmp_path / "CSM"
    target.mkdir()
    (target / "CSM.exe").write_text("OLD-CONTENT", encoding="utf-8")
    z = _make_zip(tmp_path)

    # Force the extraction step to fail
    real_extractall = zipfile.ZipFile.extractall
    def boom(self, *a, **kw):
        raise OSError("simulated extraction failure")
    monkeypatch.setattr(zipfile.ZipFile, "extractall", boom)

    with pytest.raises(OSError):
        updater_main.replace_directory(target=target, zip_path=z)

    # After rollback, target should still hold old content
    assert (target / "CSM.exe").read_text(encoding="utf-8") == "OLD-CONTENT"


def test_wait_for_pid_exit_returns_quickly_if_not_running(tmp_path: Path):
    """A nonexistent PID should be considered already-exited."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from updater.main import wait_for_pid_exit
    # 2^32 - 1 is virtually guaranteed not to exist
    wait_for_pid_exit(pid=4294967295, timeout_s=2)  # should return without raising
```

- [ ] **Step 2: 跑失败**

```bash
pytest tests/updater/ -v
```

- [ ] **Step 3: 实现 updater/main.py**

```bash
mkdir -p updater
```

写 `updater/__init__.py`（空）。

写 `updater/main.py`:

```python
"""CSM updater: replace install dir + restart main app.

Spawned by the main CSM process when the user accepts an upgrade. Receives
the main process PID, the downloaded zip path, and the install dir target.
We wait for the main process to exit, then atomically swap the directory.

Usage:
    updater.exe --pid 12345 --zip "C:\\Temp\\CSM-v0.2.0.zip" --target "C:\\Apps\\CSM"
"""
from __future__ import annotations
import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO,
                    format="[updater] %(asctime)s %(levelname)s %(message)s")


def wait_for_pid_exit(pid: int, timeout_s: float = 10.0) -> None:
    """Poll until the OS reports the PID has exited, or timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    logger.warning("pid %d still alive after %.1fs — proceeding anyway", pid, timeout_s)


def _pid_alive(pid: int) -> bool:
    """Return True iff a process with that PID is currently alive."""
    if sys.platform.startswith("win"):
        # Use tasklist as a portable check
        try:
            out = subprocess.check_output(
                ["tasklist", "/fi", f"PID eq {pid}", "/fo", "csv", "/nh"],
                text=True, stderr=subprocess.DEVNULL,
            )
            return str(pid) in out
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return False
    # POSIX
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def replace_directory(*, target: Path, zip_path: Path) -> None:
    """Atomically swap the install directory with the contents of ``zip_path``.

    Steps:
        1. Rename target → target.bak
        2. Extract zip to target.parent (zip contains 'CSM/...' tree, so it
           lands as target.parent/<dirname>)
        3. Move extracted dir → target
        4. Remove target.bak

    On any failure, attempt to roll back: remove partial target, restore .bak.
    """
    target = Path(target).resolve()
    zip_path = Path(zip_path).resolve()
    backup = target.with_name(target.name + ".bak")
    extract_root = target.parent

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

    # 1. Move current install aside
    if target.exists():
        shutil.move(str(target), str(backup))

    extracted_inner = None
    try:
        # 2. Extract the zip — should produce extract_root/<top-level-dir>/
        with zipfile.ZipFile(zip_path) as zf:
            top_levels = sorted({Path(n).parts[0] for n in zf.namelist() if n})
            zf.extractall(str(extract_root))
        if not top_levels:
            raise RuntimeError("zip is empty")
        # Pick the first top-level dir as the source
        extracted_inner = extract_root / top_levels[0]
        if not extracted_inner.exists():
            raise RuntimeError(f"expected {extracted_inner} to exist after extract")

        # 3. Rename extracted dir to target
        if extracted_inner.resolve() != target.resolve():
            shutil.move(str(extracted_inner), str(target))

        # 4. Cleanup .bak
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        # Rollback
        logger.exception("replace failed — rolling back")
        try:
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
        except OSError:
            pass
        if backup.exists():
            try:
                shutil.move(str(backup), str(target))
            except OSError:
                logger.error("rollback failed — install dir may be inconsistent")
        if extracted_inner and extracted_inner.exists() and extracted_inner != target:
            shutil.rmtree(extracted_inner, ignore_errors=True)
        raise


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args(argv[1:])

    logger.info("waiting for main pid %d to exit", args.pid)
    wait_for_pid_exit(args.pid, timeout_s=10)

    try:
        replace_directory(target=args.target, zip_path=args.zip)
    except Exception as e:
        logger.error("update failed: %s", e)
        # Try to relaunch old app via the .bak that we restored
        exe = args.target / "CSM.exe"
        if exe.exists():
            subprocess.Popen([str(exe)], close_fds=True)
        return 1

    # Cleanup downloaded zip
    try:
        args.zip.unlink()
    except OSError:
        pass

    # Relaunch new app
    new_exe = args.target / "CSM.exe"
    if new_exe.exists():
        subprocess.Popen([str(new_exe)], close_fds=True)
        logger.info("relaunched %s", new_exe)
    else:
        logger.warning("new exe not found at %s", new_exe)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: 写 updater/updater.spec**

```python
# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt6', 'PyQt5', 'PySide2', 'PySide6',
              'qfluentwidgets', 'pytest', 'numpy', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,  # Show a console window so users can see updater progress
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

- [ ] **Step 5: 跑通过**

```bash
pytest tests/updater/ -v
```

预期：3 PASS.

- [ ] **Step 6: 提交**

```bash
git add updater/ tests/updater/
git commit -m "feat(updater): independent updater process + onefile spec"
```

---

## Task 15: 把 CSM.spec 提交进来 + .github/workflows/release.yml

**Files:**
- Create: `CSM.spec`（从主仓库 `D:\CSM\CSM.spec` 复制内容）
- Create: `.github/workflows/release.yml`

- [ ] **Step 1: 复制 CSM.spec 进来**

把 `D:\CSM\CSM.spec` 的内容复制到 worktree 根 `CSM.spec`。具体内容（已知）：

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ('csm_gui/assets', 'csm_gui/assets'),
    ('examples', 'examples'),
    ('templates', 'templates'),
    ('README.md', '.'),
]
datas += collect_data_files('qfluentwidgets')
datas += collect_data_files('PyQt6')
datas += collect_data_files('docx')
datas += collect_data_files('anthropic')

hiddenimports = [
    'csm_gui',
    'csm_core',
    'docx',
    'frontmatter',
    'anthropic',
    'httpx',
    'tenacity',
    'pydantic',
    'click',
    'datasketch',
    'datasketch.minhash',
    'datasketch.lsh',
    # LLM providers are conditionally imported inside make_client();
    # list them so PyInstaller bundles every provider.
    'csm_core.llm.providers.mock',
    'csm_core.llm.providers.anthropic',
    'csm_core.llm.providers.openai',
    'csm_core.llm.providers.openai_compat',
    'csm_core.llm.providers.deepseek',
    'csm_core.llm.providers.gemini',
    'csm_core.llm.providers.qwen',
    # Dedup module + tray module (added during feature work)
    'csm_core.dedup',
    'csm_core.dedup.shingles',
    'csm_core.dedup.corpus',
    'csm_core.dedup.index',
    'csm_core.dedup.analyzer',
    'csm_core.dedup.report',
    'csm_gui.tray',
    'csm_gui.tray.manager',
    'csm_gui.tray.menu',
    'csm_gui.tray.icon',
    'csm_gui.tray.single_instance',
    'csm_gui.workers.dedup_worker',
    'csm_gui.widgets.dedup_panel',
    'csm_gui.widgets.dedup_drill_dialog',
    # Updater client
    'csm_core.updater_client',
    'csm_core.updater_client.manifest',
    'csm_core.updater_client.checker',
    'csm_core.updater_client.downloader',
    'csm_core.updater_client.github_client',
    'csm_gui.workers.update_check_worker',
    'csm_gui.widgets.update_dialog',
    'csm_gui.widgets.update_progress_dialog',
]
hiddenimports += collect_submodules('docx')
hiddenimports += collect_submodules('qfluentwidgets')
hiddenimports += collect_submodules('anthropic')
hiddenimports += collect_submodules('datasketch')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pytest', 'PyQt5', 'PySide2', 'PySide6'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CSM',
    icon='csm_gui/assets/csm.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CSM',
)
```

- [ ] **Step 2: 创建 .github/workflows/release.yml**

```bash
mkdir -p .github/workflows
```

写 `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*.*.*'

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: 校验 tag 与 _version 一致
        run: python scripts/release_check.py "${{ github.ref_name }}"

      - name: 安装项目依赖
        run: |
          python -m pip install --upgrade pip
          pip install -e .[gui]
          pip install pyinstaller

      - name: 注入 PAT 到 _token.py
        shell: pwsh
        run: |
          @"
          TOKEN = "${{ secrets.CSM_RELEASE_PAT }}"
          "@ | Set-Content -Path csm_core\updater_client\_token.py -Encoding utf8

      - name: 构建主程序
        run: pyinstaller CSM.spec

      - name: 构建 updater
        run: pyinstaller updater/updater.spec --distpath dist/updater

      - name: 把 updater.exe 拷到主分发目录
        shell: pwsh
        run: |
          Copy-Item dist\updater\updater.exe dist\CSM\updater.exe

      - name: 打包 zip
        shell: pwsh
        run: |
          Compress-Archive -Path dist\CSM -DestinationPath "CSM-${{ github.ref_name }}.zip"

      - name: 生成 manifest.json
        run: |
          python scripts/build_manifest.py --version "${{ github.ref_name }}" --zip "CSM-${{ github.ref_name }}.zip" --out manifest.json

      - name: 抽取 CHANGELOG 段落
        id: changelog
        shell: pwsh
        run: |
          $body = python scripts/extract_changelog.py "${{ github.ref_name }}"
          # Encode for outputs (multi-line safe)
          $body = $body -replace "`r`n", "`n"
          $delim = "EOF_$(Get-Random)"
          "body<<$delim" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
          "$body" | Out-File -FilePath $env:GITHUB_OUTPUT -Append
          "$delim" | Out-File -FilePath $env:GITHUB_OUTPUT -Append

      - name: 创建 GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          body: ${{ steps.changelog.outputs.body }}
          files: |
            CSM-${{ github.ref_name }}.zip
            manifest.json
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

- [ ] **Step 3: 提交**

```bash
git add CSM.spec .github/workflows/release.yml
git commit -m "build(ci): GitHub Actions release workflow + bring CSM.spec on-branch"
```

---

## Task 16: PyInstaller 冒烟（手动 — 交给用户）+ E2E 验证清单

**Files:** None — manual

- [ ] **Step 1: 主程序 PyInstaller 冒烟**

```bash
pyinstaller CSM.spec
```

确认 `dist/CSM/CSM.exe` 生成。如缺模块，根据报错追加 hiddenimports。

- [ ] **Step 2: updater PyInstaller 冒烟**

```bash
pyinstaller updater/updater.spec --distpath dist/updater
```

确认 `dist/updater/updater.exe` 生成（约 30 MB）。手动用 cmd 跑一次 `dist/updater/updater.exe --pid 0 --zip nonexistent.zip --target nonexistent` 应能解析 args 并立即报错（不会闪退）。

- [ ] **Step 3: 端到端验证清单（用户在本地 / GitHub 实施）**

> 这一步需要你（用户）配合：

1. **GitHub 准备**
   - 在私有 repo 的 Settings → Secrets → Actions 添加 `CSM_RELEASE_PAT`（Fine-grained PAT，权限：Contents Read on repo）
   - 把 `_GITHUB_REPO = "zev96/csm"` 改成你的实际 repo 名（main_window.py）

2. **首次发版**
   ```bash
   python scripts/release.py 0.2.1 --dry-run    # 预演
   python scripts/release.py 0.2.1               # 实际推
   ```
   推 tag 后 5–10 分钟看 Actions 应跑完，Release 页面应有 zip + manifest.json。

3. **客户端升级**
   - 在另一台机器（或刷掉的同一台）装 v0.1.x 旧版（dist/CSM 文件夹）
   - 启动 → 等待启动检查 → 弹「发现新版本」对话框
   - 点「立即升级」→ 进度条跑完 → 主程序退出 → updater.exe 运行 → 新版自动启动
   - 验证 `<install>/CSM.bak` 已被清理（成功后删除）

4. **回滚验证**
   - 强行 break 升级（如把 zip 文件改坏）→ updater 应回滚 .bak → 旧版主程序重启
   - 验证 `<config_dir>/update_error.log` 有错误记录

- [ ] **Step 4: README/CHANGELOG 收尾（已在 Task 1 部分覆盖，确保 [Unreleased] 段把热更新功能列入）**

无需另写 commit，本任务即手动验证即可。

---

## Self-Review Checklist

完成所有 Task 后：

- [ ] 全量测试 `pytest tests/` 全部 PASS（除 pre-existing 失败）
- [ ] PyInstaller 主程序 + updater 都能打包成功
- [ ] CI 已配置 `CSM_RELEASE_PAT` secret
- [ ] `csm_core/updater_client/_token.py` 不在 git history 中（gitignored）
- [ ] `_GITHUB_REPO` 常量已改成实际 repo 名
- [ ] 推一个 test tag 触发 CI，Release 自动生成
- [ ] 老版本启动能收到升级提示并完成升级
- [ ] git log 应有 14–16 个 commit

---

## 风险点 / 易错处

1. **`_token.py` 泄露** — 必须 gitignored；CI 注入；本地不要 commit。
2. **PyInstaller 漏掉 hiddenimports** — datasketch / docx / 我们的子包都已在 spec 列出。如发版后报缺，在 spec 追加。
3. **Windows 文件锁** — 主程序 .exe 自己锁住自己时无法覆盖。updater 通过 `wait_for_pid_exit + 重命名 + 解压` 三步走避免；前提是主程序 quit() 后真的释放了所有句柄。
4. **CHANGELOG.md 段落格式严苛** — `## [version]` 行必须严格匹配（regex 是 `^##\s+\[X.Y.Z\]`）；首字符必须是 `## `。
5. **GitHub PAT 6 个月轮换** — 到期后客户端无法检查更新，但不阻塞 CSM 主功能。建议设日历提醒。
6. **release.py push 后无法撤回** — 推错 tag 不能删了重推（GitHub 不允许 force-push tag），只能再发一个版本号修复。`--dry-run` 用起来。
7. **manifest_url 鉴权** — 私有 repo 的 asset 下载需要 token；downloader.py 当前不带 token。**修订点**：在 Task 13 的 `_on_upgrade_clicked` 把 token 加到 download_with_verification 的请求 header 里（修改 downloader.py 加 `headers` 参数）。**这是已知缺口**，会在 Task 13 实施时一并解决。
8. **CI 上 `pip install -e .[gui]`** 需要 PyQt6 在 Windows runner 上能装；通常 OK，但首次会比较慢（6.5.x 几百 MB）。
