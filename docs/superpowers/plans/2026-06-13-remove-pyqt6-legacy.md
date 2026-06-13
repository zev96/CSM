# ⑤ 删除 PyQt6 老栈（migration Stage D 收尾）Implementation Plan

> **For agentic workers:** 删除任务，确定性强，由主控直接执行（非 subagent 接力）+ final review 把关。Steps use `- [ ]`.

**Goal:** 移除遗留的 PyQt6 桌面栈 `csm_gui/`（v0.3.0）及其周边，使仓库只保留新栈（Tauri 2 + Vue 3 前端 + Python FastAPI sidecar + csm_core 核心）。这是 v0.4 架构迁移计划的既定 **Stage D**（见 `docs/migration/README.md` 与 `csm_gui/config.py` 注释「Once csm_gui/ is removed (migration plan stage D), this file goes too」）。

**Background:** dual-stack —— OLD `csm_gui/`（PyQt6，~150 py + assets，入口 `python -m csm_gui` / `main.py`）；NEW `frontend/` + `frontend/src-tauri/` + `sidecar/` + `csm_core/`。

## 发版安全确认（删前必查，已铁证 = GO）
调研 `release.yml` / `release.py` / `release_check.py` / `build_sidecar.py` / `pyproject.toml`：
- **CI release (`release.yml` L39-44)** 跑 `pip install -e .`（**不带 `[gui]` extra**）+ `pip install -e ./sidecar`，再 `build_sidecar.py`/`build_updater.py`/`tauri:build`。全程**零** csm_gui / PyQt6 / `main.py` / `CSM.spec` 引用。
- **`pip install -e .`（L43，发版必经）** 会触发 setuptools 解析 `[tool.setuptools.dynamic] version = {attr="csm_gui._version.__version__"}` → **这是删 csm_gui 后唯一会炸的发版点**；本计划的前置修复（attr 改指 `csm_core.__version__`）恰好治它。
- **`release.py`** bump 6 处版本（tauri.conf.json / Cargo.toml / sidecar `__init__` / package.json / package-lock×2 / CHANGELOG），**不含** csm_gui，也不 import 它。
- **`release_check.py`** 注释明示「legacy csm_gui._version 不再读，源是 tauri.conf.json」。
- 存活栈（frontend/sidecar/csm_core/updater）`grep "from csm_gui|import csm_gui"` = **0**（仅注释/历史文档/被删测试命中）。

→ **GO，发版零风险**，唯一硬接缝（version attr）已纳入修复。

## 删除清单
- `csm_gui/`（整目录）
- `tests/gui/`（整目录，35 个 GUI 测试，全部且仅有它们用 pytest-qt/PyQt）
- `CSM.spec`（老 GUI PyInstaller spec，CI 不用，build 脚本只用 sidecar/updater spec）
- `main.py`（仅老 GUI launcher：`from csm_gui.app import run`）

## 改动清单
- **`pyproject.toml`**（一次性整段重写 L47-84）：
  - `[tool.setuptools.dynamic]` version attr `csm_gui._version.__version__` → `csm_core.__version__`（**release-critical**）
  - 删 `[project.optional-dependencies].gui`（PyQt6 + PyQt6-Fluent-Widgets）
  - `dev` extra 删 `pytest-qt>=4.4`（仅 GUI 测试用）
  - 删 `[project.scripts]` 的 `csm-gui = "csm_gui.__main__:main"`
  - `[tool.setuptools.packages.find]` include 去掉 `"csm_gui*"`
  - 删 `[tool.setuptools.package-data]` 整块（仅 csm_gui assets）
- **`scripts/clear_account.py`**：清理对老栈的 stale 引用 —— 去掉注释里的 `csm_gui` 提及，并移除探测老 PyQt6 配置路径的 Qt `try/except` 块（`from PyQt6 ...`），使其成为零 PyQt6 引用的纯 stdlib 工具（保留 4 个硬编码候选路径与清字段主逻辑）。代码本就不真 import csm_gui（grep 命中的是注释）。
- **`docs/migration/README.md`**：Stage D 标记完成（PyQt6 老栈已移除）。

## 不动（保留）
- `csm_core/` `sidecar/` `frontend/` `updater/` `scripts/`(release/build/*) 全部存活栈。
- `tests/core/` `tests/csm_core/` `tests/conftest.py` `tests/__init__.py`。
- **历史记录**：`CHANGELOG.md`、`docs/superpowers/plans/2026-04~05-*.md`、`docs/superpowers/specs/*.md` 中含 csm_gui 字样的历史快照 —— 是历史，不改。

---

## Task 1: 删除 + pyproject + 周边清理

- [ ] **Step 1** — `git rm -r csm_gui tests/gui` + `git rm CSM.spec main.py`
- [ ] **Step 2** — 整段重写 `pyproject.toml` L47-84（6 处见改动清单）
- [ ] **Step 3** — `scripts/clear_account.py` 注释去 csm_gui 提及
- [ ] **Step 4** — `docs/migration/README.md` Stage D 标记完成

## Task 2: 验证
- [ ] **Step 1 — toml 合法**：`python -c "import tomllib,sys; tomllib.load(open('pyproject.toml','rb')); print('toml ok')"`（无 py 环境则跳，靠 review）
- [ ] **Step 2 — version attr 可解析**：`csm_core/__init__.py` 含 `__version__`（已确认 = "0.1.0"）→ setuptools 同款 import 必成。理想 `pip install -e . --dry-run` 或真装确认 release.yml L43 路径不炸。
- [ ] **Step 3 — 无残留真依赖**：`grep -rn "from csm_gui\|import csm_gui" frontend sidecar csm_core updater scripts` 应仅剩 clear_account.py 若有则为注释；`grep -rn "pytestqt\|from PyQt\|import PyQt" tests` 应为 0（tests/gui 已删）。
- [ ] **Step 4 — core 测试可收集**：理想 `pytest tests/core tests/csm_core --co -q`（确认删 tests/gui 不影响 core 测试收集）。

## Task 3: final review + PR
- [ ] **Step 1** — final review（origin/main..HEAD）：删除完整无遗漏、pyproject 合法且 version attr 修复正确、无存活代码 dangling import csm_gui、发版路径（`pip install -e .` → build_sidecar → tauri:build）不受影响、历史文档未被误改、clear_account.py 仍可独立运行。
- [ ] **Step 2** — commit plan + 全部改动；`git status` 确认无杂散 untracked（勿留 root node_modules 等）。
- [ ] **Step 3** — `git push -u origin claude/remove-pyqt6` + `gh pr create --base main`，返回 URL 停 pending。

---

## Self-Review
- **发版安全**：核心风险（删后 `pip install -e .` 炸）已用 release.yml L39-44 铁证定位到唯一接缝（version attr），并以「改指 csm_core.__version__」治理。CI 从不装 `.[gui]` → 删 PyQt6 deps 零影响。
- **scope 边界**：只删老栈 + 其专属测试/spec/launcher + 清理引用；存活栈、core 测试、历史文档全不动。
- **subagent 调研偏差已亲验修正**：clear_account.py 非真依赖（注释命中）；pytest-qt 仅 tests/gui。
- **不可逆性**：删除走 git rm（可 revert）；PR diff 为用户 merge 前的最终审查点。
- **后续判断项**（PR 注明，不在本次强删）：clear_account.py 探测老栈 settings.json 路径、user_name/user_product 是老 GUI 首启字段，新栈用 CSM-Data —— 该脚本是否整体退役，留给用户定夺。
