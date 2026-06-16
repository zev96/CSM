# 小红书图文笔记编辑器 · P2 图片 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给小红书编辑器加图片：上传（magic-byte 校验 + 5MB 上限，落本地盘）/ 缩略图网格 / 拖拽排序 / 设封面 / 删除，右侧手机预览显示真实封面图。

**Architecture:** 后端**1:1 镜像已验证的 mining 图片栈**——新建 `xhs_images_service.py`（仿 `mining_images_service.py`，仅把 per-video 子目录换成 per-draft、根目录换成 `xhs_images/`，并加一个删草稿级联删整目录的 `delete_draft_images`），图片路由加进**现有** `routes/xhs.py`（同一 router）。前端 `useXhs` store 加图片 actions（上传/删除/设封面/排序），新建 `ImagePanel.vue`（隐藏 file input + 缩略图网格 + 原生 HTML5 拖拽排序），`PhonePreview.vue` 用真实封面图替换占位块，`PanelRail` 把 image tab 接到 `ImagePanel`。

**Tech Stack:** 后端 Python + FastAPI（`UploadFile`/`File` multipart、`FileResponse` 静态 serve）+ stdlib（`pathlib`/`shutil`/`uuid`）+ pytest。前端 Vue 3.5 `<script setup lang="ts">` + Pinia + axios（`FormData` multipart）+ 原生拖拽 + vitest(jsdom) + @vue/test-utils。

---

## 设计依据

实现设计稿 [2026-06-16-xiaohongshu-editor-design.md](../specs/2026-06-16-xiaohongshu-editor-design.md) 的 **P2 阶段**（§1 P2、§2 后端新增、§3.2 图片、§4.5 自动保存、§8 图片孤儿清理）。

**P2 范围（in scope）**
- 图片上传：前端隐藏 `<input type=file>` 选图 → 读 `File` → `POST /api/xhs/drafts/{id}/images`（multipart）→ sidecar magic-byte 校验 + 落盘 + 返回 `{image_id, url, size}`。
- 图片管理：缩略图网格、**拖拽排序**、设封面（`cover_index`）、删除。
- 预览显示真实图：笔记页封面 = 封面图；发现页卡片封面 = 封面图（无图回退到占位渐变块）。
- 孤儿清理（§8）：删草稿级联删 `xhs_images/{draft_id}/` 整目录；删单图（PATCH 移除某 image_id）时删该文件。**不做跨草稿引用计数**（每草稿图独立）。

**P2 明确不做**：AI（P3）、自定义素材（P4）、图片裁剪/滤镜/压缩、多草稿共享图、预览转 PNG。

**P2 验收标准**（设计稿 §7 P2）
> 上传 jpg/png/webp → 缩略图 → 排序 → 设封面 → 预览封面更新 → 刷新后图片仍在；超 5MB / 非图片被拒。

---

## 前置：测试运行环境（执行者必读）

P2 **同时动后端（sidecar）和前端**，所以两套门禁都要跑。

### 后端（pytest）

`csm_core`（仓库根）与 `csm_sidecar`（`sidecar/`）是 **editable 安装在主仓 `D:\CSM`** 的包；在本 worktree 跑 pytest 默认会导入**主仓**代码而非本 worktree 的改动。且**系统 `python` 缺 fastapi/pytest，必须用 venv 的 python**。运行后端测试前（PowerShell）：

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_images_service.py -v
```

（在仓库根 `D:\CSM\.claude\worktrees\cranky-varahamihira-d53003` 执行，已设上面的 PYTHONPATH。后续后端命令同理都用 `& "D:\CSM\.venv\Scripts\python.exe" -m pytest ...`。）

### 前端（vitest / 构建）

在 `frontend/` 下：单测 `npx vitest run <spec 路径>`；全量 `npx vitest run`；类型检查 `npx vue-tsc -b`；完整构建门禁 `npm run build`（= `vue-tsc -b && vite build`）。

> ⚠ 已知坑（项目记忆）：
> - `npx vue-tsc -b` 可能 emit 出 `vite.config.js` / `*.d.ts` 产物并触发 vite 重启；类型检查后若 `git status` 出现这些被改/新增的产物，用 `git checkout -- frontend/vite.config.js` 还原、新增的 `.d.ts` 直接删。
> - **不要改 `frontend/package-lock.json`**（本机 npm 版本与 CI 不一致会重写它）；若出现 lockfile diff，`git checkout -- frontend/package-lock.json`。本计划不新增任何 npm 依赖（拖拽用原生 HTML5 DnD，不引 vuedraggable）。

每个任务最后一步是 commit，提交信息用中文（项目约定）。

---

## 文件结构（P2 落地清单）

**后端新增**
- `sidecar/csm_sidecar/services/xhs_images_service.py` —— 本地图片存储（仿 `mining_images_service.py`）
- `sidecar/tests/test_xhs_images_service.py` —— service 单测
- `sidecar/tests/test_xhs_image_routes.py` —— 路由测试

**后端改动**
- `sidecar/csm_sidecar/routes/xhs.py` —— 加图片上传/serve 路由 + 删草稿级联删图 + PATCH 移除图时删文件
- `sidecar/csm-sidecar.spec` —— hiddenimports 补 `csm_sidecar.services.xhs_images_service`

**后端不动**：`csm_core/xhs/storage.py`（`image_ids_json` / `cover_index` 列 P0 已就绪，`update_draft` 已支持二者）、`main.py`（图片路由挂在**现有** xhs router 上，已 `include_router`）。

**前端新增**
- `frontend/src/components/xhs/panels/ImagePanel.vue` —— 图片面板
- `frontend/src/components/xhs/panels/__tests__/ImagePanel.spec.ts`
- `frontend/src/components/xhs/__tests__/PhonePreview.spec.ts` —— 预览封面测试（P0 未测，P2 补）

**前端改动**
- `frontend/src/stores/xhs.ts` —— 加 `uploadImage`/`removeImage`/`setCover`/`reorderImages` action + `isEmpty`/`_ensureCreated` 改造
- `frontend/src/stores/__tests__/xhs.spec.ts` —— 追加图片 store 测试
- `frontend/src/components/xhs/PanelRail.vue` —— `image` tab 接到 `ImagePanel`（占位只剩 `ai`）
- `frontend/src/components/xhs/PhonePreview.vue` —— 封面占位块换真实图

---

## Task 1: xhs_images_service —— 本地图片存储（仿 mining）

**Files:**
- Create: `sidecar/csm_sidecar/services/xhs_images_service.py`
- Test: `sidecar/tests/test_xhs_images_service.py`

1:1 仿 `sidecar/csm_sidecar/services/mining_images_service.py`（magic-byte 校验 jpeg/png/webp、5MB 上限、uuid 文件名、`get_image_path` 的 `..` 越界防护、`delete_images` best-effort）。三处差异：①根目录 `xhs_images`（非 `mining_images`）；② `save_image` 的子目录键是 `draft_id: str`（非 `video_id: int`）；③ **新增** `delete_draft_images(draft_id)` —— 删草稿时整目录 rmtree（带同款 `..` 防护），用于 §8 级联清理。

- [ ] **Step 1: 写失败测试**

Create `sidecar/tests/test_xhs_images_service.py`：

```python
"""xhs_images_service: magic-bytes filter, size cap, path traversal, cascade."""
from pathlib import Path

import pytest

from csm_sidecar.services import xhs_images_service as images
from csm_core import config as core_config


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch) -> Path:
    """Redirect default_config_dir() to a temp dir so save_image writes
    under tmp_path/xhs_images instead of the real %LOCALAPPDATA%."""
    monkeypatch.setattr(core_config, "default_config_dir", lambda: tmp_path)
    return images.image_root()


# Real minimal headers — body past the magic bytes can be anything.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 256
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 256
HTML_BYTES = b"<html><body>hi</body></html>" + b"\x00" * 256


def test_save_jpeg_round_trip(isolated_root: Path):
    image_id = images.save_image("draftA", JPEG_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None
    assert path.suffix == ".jpg"
    assert path.read_bytes() == JPEG_BYTES


def test_save_png_round_trip(isolated_root: Path):
    image_id = images.save_image("draftA", PNG_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None and path.suffix == ".png"
    assert path.read_bytes() == PNG_BYTES


def test_save_webp_round_trip(isolated_root: Path):
    image_id = images.save_image("draftA", WEBP_BYTES)
    path = images.get_image_path(image_id)
    assert path is not None and path.suffix == ".webp"


def test_reject_html_payload(isolated_root: Path):
    with pytest.raises(ValueError, match="unsupported image type"):
        images.save_image("d", HTML_BYTES)


def test_reject_tiny_payload(isolated_root: Path):
    with pytest.raises(ValueError, match="unsupported image type"):
        images.save_image("d", b"\x00")


def test_reject_oversized(isolated_root: Path):
    too_big = PNG_BYTES + b"\x00" * (5 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="too large"):
        images.save_image("d", too_big)


def test_get_image_path_rejects_traversal(isolated_root: Path):
    assert images.get_image_path("../../etc/passwd") is None


def test_get_image_path_rejects_path_separator(isolated_root: Path):
    assert images.get_image_path("a/b") is None
    assert images.get_image_path("a\\b") is None


def test_get_image_path_empty(isolated_root: Path):
    assert images.get_image_path("") is None


def test_get_image_path_unknown_id(isolated_root: Path):
    assert images.get_image_path("deadbeef" * 4) is None


def test_delete_images_removes_files(isolated_root: Path):
    image_id = images.save_image("d7", PNG_BYTES)
    assert images.get_image_path(image_id) is not None
    images.delete_images([image_id])
    assert images.get_image_path(image_id) is None


def test_delete_images_missing_does_not_raise(isolated_root: Path):
    image_id = images.save_image("d7", PNG_BYTES)
    images.delete_images([image_id, "missing-1", "missing-2"])
    assert images.get_image_path(image_id) is None


def test_delete_empty_list_noop(isolated_root: Path):
    images.delete_images([])


def test_image_root_creates_directory(tmp_path: Path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.setattr(core_config, "default_config_dir", lambda: target)
    assert not target.exists()
    root = images.image_root()
    assert root.exists()
    assert root == target / "xhs_images"


def test_delete_draft_images_removes_whole_dir(isolated_root: Path):
    a = images.save_image("draftX", PNG_BYTES)
    b = images.save_image("draftX", JPEG_BYTES)
    assert images.get_image_path(a) is not None
    assert images.get_image_path(b) is not None
    images.delete_draft_images("draftX")
    assert images.get_image_path(a) is None
    assert images.get_image_path(b) is None
    assert not (isolated_root / "draftX").exists()


def test_delete_draft_images_rejects_traversal(isolated_root: Path):
    # Must never rmtree outside the image root.
    victim = isolated_root.parent / "victim"
    victim.mkdir()
    (victim / "keep.txt").write_text("x")
    images.delete_draft_images("../victim")
    assert victim.exists()  # untouched


def test_delete_draft_images_missing_noop(isolated_root: Path):
    images.delete_draft_images("never-existed")  # no raise
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_images_service.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'csm_sidecar.services.xhs_images_service'`。

- [ ] **Step 3: 实现 service**

Create `sidecar/csm_sidecar/services/xhs_images_service.py`：

```python
"""Local image storage for 小红书 draft attachments (P2).

1:1 仿 ``mining_images_service``，差异：
* 根目录 ``xhs_images``（非 mining_images）
* 子目录键是 draft_id(str)（非 video_id(int)）—— 每草稿一个子目录
* 多一个 ``delete_draft_images(draft_id)`` —— 删草稿时整目录清掉（§8 级联）

安全约束（与 mining 同）：
* magic-bytes 嗅探前 12 字节，只认 jpeg/png/webp（不信 Content-Type，
  防 .html 当 image/png 上传后经静态路由 XSS）
* 5MB 硬上限（写盘前）
* uuid4 image_id 不可枚举
* get_image_path / delete_draft_images 解析后校验仍在 image_root() 内，
  防 ``../`` 穿越
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from csm_core import config as core_config

logger = logging.getLogger(__name__)


_MAX_BYTES = 5 * 1024 * 1024  # 5 MB

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_WEBP_RIFF = b"RIFF"
_WEBP_FORMAT = b"WEBP"


def image_root() -> Path:
    """Per-user dir where every xhs image lives. Auto-creates; idempotent."""
    root = core_config.default_config_dir() / "xhs_images"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _detect_ext(content: bytes) -> str | None:
    """Sniff first ~12 bytes for jpeg/png/webp. None = unrecognized."""
    if len(content) < 4:
        return None
    if content.startswith(_JPEG_MAGIC):
        return "jpg"
    if content.startswith(_PNG_MAGIC):
        return "png"
    if len(content) >= 12 and content[:4] == _WEBP_RIFF and content[8:12] == _WEBP_FORMAT:
        return "webp"
    return None


def save_image(draft_id: str, content: bytes) -> str:
    """Validate, write to disk under ``xhs_images/{draft_id}/``, return image_id.

    Raises:
        ValueError("image too large") when content exceeds 5 MB.
        ValueError("unsupported image type") on magic-bytes mismatch.
    """
    if len(content) > _MAX_BYTES:
        raise ValueError("image too large")
    ext = _detect_ext(content)
    if ext is None:
        raise ValueError("unsupported image type")
    image_id = uuid.uuid4().hex
    draft_dir = image_root() / draft_id
    draft_dir.mkdir(parents=True, exist_ok=True)
    path = draft_dir / f"{image_id}.{ext}"
    path.write_bytes(content)
    return image_id


def get_image_path(image_id: str) -> Path | None:
    """Resolve image_id back to a path on disk, or None if missing.

    Scans every per-draft subdir under image_root(). Treats traversal-shaped
    IDs as not-found and re-checks the resolved path stays under the root.
    """
    if not image_id or "/" in image_id or "\\" in image_id or ".." in image_id:
        return None
    root = image_root()
    root_resolved = root.resolve()
    try:
        subdirs = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return None
    for sub in subdirs:
        for ext in ("jpg", "png", "webp"):
            candidate = sub / f"{image_id}.{ext}"
            if candidate.exists():
                try:
                    resolved = candidate.resolve()
                except OSError:
                    continue
                if not resolved.is_relative_to(root_resolved):
                    return None
                return resolved
    return None


def delete_images(image_ids: list[str]) -> None:
    """Best-effort cleanup; missing files are logged but never raise."""
    for image_id in image_ids:
        path = get_image_path(image_id)
        if path is None:
            logger.debug("delete_images: image %s already gone", image_id)
            continue
        try:
            path.unlink()
        except OSError as e:
            logger.warning("delete_images: unlink %s failed: %s", path, e)


def delete_draft_images(draft_id: str) -> None:
    """删草稿级联：整个 ``xhs_images/{draft_id}/`` 目录 rmtree（§8）。

    带 ``..`` / 分隔符防护 + resolve 后再校验仍在 root 内 —— draft_id 来自
    URL path，虽然实际只会是 DB 里的 uuid hex，仍按防御式处理，绝不 rmtree
    到 root 之外。目录不存在时静默 no-op。
    """
    if not draft_id or "/" in draft_id or "\\" in draft_id or ".." in draft_id:
        return
    root = image_root()
    target = root / draft_id
    try:
        resolved = target.resolve()
    except OSError:
        return
    if not resolved.is_relative_to(root.resolve()):
        return
    if resolved.is_dir():
        shutil.rmtree(resolved, ignore_errors=True)
```

- [ ] **Step 4: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_images_service.py -v
```
Expected: PASS（17 条全绿）。

- [ ] **Step 5: Commit**

```powershell
git add sidecar/csm_sidecar/services/xhs_images_service.py sidecar/tests/test_xhs_images_service.py
git commit -m "feat(xhs): 图片本地存储 service 仿 mining (P2 T1)"
```

---

## Task 2: 图片路由（上传 / serve）+ 级联清理 + 打包登记

**Files:**
- Modify: `sidecar/csm_sidecar/routes/xhs.py`（加 import、上传/serve 路由、改 `delete_draft` 级联、改 `patch_draft` 删孤儿）
- Modify: `sidecar/csm-sidecar.spec`（hiddenimports 补 1 条）
- Test: `sidecar/tests/test_xhs_image_routes.py`

路由仿 mining 的 `upload_comment_image` / `get_comment_image`（`mining.py` 544–583），差异：draft_id 来自 **path**（不是 `Form`），url 指向 `/api/xhs/images/{id}`。挂在**现有** xhs router 上（已 `include_router`，无需改 main.py）。

- [ ] **Step 1: 写失败测试**

Create `sidecar/tests/test_xhs_image_routes.py`：

```python
"""Routes for xhs image upload + serve + cascade cleanup (P2 T2)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from csm_core import config as core_config
from csm_sidecar.services import xhs_images_service as images

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 256
HTML_BYTES = b"<html><body>nope</body></html>" + b"\x00" * 256


@pytest.fixture
def isolated_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect image storage to tmp_path so we don't touch %LOCALAPPDATA%."""
    monkeypatch.setattr(core_config, "default_config_dir", lambda: tmp_path)
    return images.image_root()


def _new_draft(client: TestClient) -> str:
    r = client.post("/api/xhs/drafts", json={"title": "T"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_upload_png_returns_id_and_url(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    r = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["image_id"]
    assert body["url"] == f"/api/xhs/images/{body['image_id']}"
    assert body["size"] == len(PNG_BYTES)


def test_get_image_returns_bytes_and_content_type(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    image_id = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    ).json()["image_id"]
    g = client.get(f"/api/xhs/images/{image_id}")
    assert g.status_code == 200
    assert g.headers["content-type"].startswith("image/png")
    assert g.content == PNG_BYTES


def test_get_image_jpeg_content_type(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    image_id = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("a.jpg", JPEG_BYTES, "image/jpeg")},
    ).json()["image_id"]
    g = client.get(f"/api/xhs/images/{image_id}")
    assert g.status_code == 200
    assert g.headers["content-type"].startswith("image/jpeg")


def test_get_missing_image_returns_404(client: TestClient, xhs_db: Path, isolated_root: Path):
    assert client.get("/api/xhs/images/" + "deadbeef" * 4).status_code == 404


def test_upload_html_payload_returns_400(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    r = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("evil.png", HTML_BYTES, "image/png")},
    )
    assert r.status_code == 400
    assert "unsupported" in r.text.lower()


def test_upload_oversized_returns_400(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    too_big = PNG_BYTES + b"\x00" * (5 * 1024 * 1024 + 1)
    r = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("big.png", too_big, "image/png")},
    )
    assert r.status_code == 400
    assert "too large" in r.text.lower()


def test_upload_for_missing_draft_returns_404(client: TestClient, xhs_db: Path, isolated_root: Path):
    r = client.post(
        "/api/xhs/drafts/nonexistent/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    )
    assert r.status_code == 404


def test_delete_draft_cascades_images(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    image_id = client.post(
        f"/api/xhs/drafts/{did}/images",
        files={"file": ("tiny.png", PNG_BYTES, "image/png")},
    ).json()["image_id"]
    assert client.get(f"/api/xhs/images/{image_id}").status_code == 200
    assert client.delete(f"/api/xhs/drafts/{did}").status_code == 204
    # 文件随草稿级联删除
    assert client.get(f"/api/xhs/images/{image_id}").status_code == 404


def test_patch_removing_image_deletes_file(client: TestClient, xhs_db: Path, isolated_root: Path):
    did = _new_draft(client)
    a = client.post(f"/api/xhs/drafts/{did}/images", files={"file": ("a.png", PNG_BYTES, "image/png")}).json()["image_id"]
    b = client.post(f"/api/xhs/drafts/{did}/images", files={"file": ("b.png", PNG_BYTES, "image/png")}).json()["image_id"]
    # 先把两张都挂到草稿
    client.patch(f"/api/xhs/drafts/{did}", json={"image_ids": [a, b]})
    # 再 PATCH 成只留 b → a 的文件应被删
    r = client.patch(f"/api/xhs/drafts/{did}", json={"image_ids": [b]})
    assert r.status_code == 200
    assert client.get(f"/api/xhs/images/{a}").status_code == 404
    assert client.get(f"/api/xhs/images/{b}").status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_image_routes.py -v
```
Expected: FAIL —— 上传/serve 路由 404（还没加）。

- [ ] **Step 3: 改 routes/xhs.py —— imports**

在 `sidecar/csm_sidecar/routes/xhs.py` 顶部，把现有 import 段：

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from csm_core.xhs import storage as xhs_storage

from ..auth import RequireToken
```

替换为（加 `File`/`UploadFile`、`FileResponse`、images service）：

```python
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from csm_core.xhs import storage as xhs_storage

from ..auth import RequireToken
from ..services import xhs_images_service
```

- [ ] **Step 4: 改 routes/xhs.py —— `patch_draft` 删孤儿 + `delete_draft` 级联**

把现有 `patch_draft` 整个函数替换为（PATCH 带 image_ids 时，diff 旧→新、删掉被移除的文件；仿 `mining.py:527`）：

```python
@router.patch("/api/xhs/drafts/{draft_id}")
def patch_draft(draft_id: str, body: DraftPatch) -> dict[str, Any]:
    # 若本次 PATCH 改 image_ids，先取旧的，便于事后删掉被移除的图片文件（§8）。
    old = xhs_storage.get_draft(draft_id) if body.image_ids is not None else None
    updated = xhs_storage.update_draft(
        draft_id,
        title=body.title,
        body=body.body,
        topics=body.topics,
        image_ids=body.image_ids,
        cover_index=body.cover_index,
        theme_id=body.theme_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    if body.image_ids is not None and old is not None:
        removed = [i for i in old["image_ids"] if i not in body.image_ids]
        if removed:
            xhs_images_service.delete_images(removed)
    return updated
```

把现有 `delete_draft` 整个函数替换为（删草稿后级联删整张图目录）：

```python
@router.delete("/api/xhs/drafts/{draft_id}", status_code=204)
def delete_draft(draft_id: str) -> None:
    if not xhs_storage.delete_draft(draft_id):
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    # 级联删 xhs_images/{draft_id}/ 整目录（§8 孤儿清理）。
    xhs_images_service.delete_draft_images(draft_id)
```

- [ ] **Step 5: 改 routes/xhs.py —— 加上传/serve 路由**

在文件**末尾**（`delete_draft` 之后）追加：

```python
# ── 图片（P2）────────────────────────────────────────────────────────────────
_EXT_TO_MEDIA_TYPE = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


@router.post("/api/xhs/drafts/{draft_id}/images", status_code=201)
async def upload_image(draft_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Multipart 上传。bytes 走 magic-byte 嗅探 —— 不信 Content-Type/文件名。

    上传只落盘 + 返回 image_id；把 image_id 挂进草稿的 image_ids 由前端随后
    PATCH 完成（与 mining 一致）。
    """
    if xhs_storage.get_draft(draft_id) is None:
        raise HTTPException(status_code=404, detail=f"draft not found: {draft_id}")
    content = await file.read()
    try:
        image_id = xhs_images_service.save_image(draft_id, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "image_id": image_id,
        "url": f"/api/xhs/images/{image_id}",
        "size": len(content),
    }


@router.get("/api/xhs/images/{image_id}")
def get_image(image_id: str) -> FileResponse:
    path = xhs_images_service.get_image_path(image_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"image not found: {image_id}")
    media_type = _EXT_TO_MEDIA_TYPE.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(str(path), media_type=media_type)
```

- [ ] **Step 6: 补 PyInstaller hiddenimports**

在 `sidecar/csm-sidecar.spec` 的 hiddenimports 里，`"csm_sidecar.services.vault_service",` 之后加一行（routes.xhs 已在 P0 列过，service 显式登记防漏）：

```python
    "csm_sidecar.services.vault_service",
    "csm_sidecar.services.xhs_images_service",
```

- [ ] **Step 7: 跑测试确认通过**

```powershell
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_image_routes.py sidecar/tests/test_xhs_storage.py sidecar/tests/test_xhs_routes.py -v
```
Expected: PASS（图片路由 9 条 + P0 既有 storage/routes 全绿，确认改 patch/delete 没回归）。

- [ ] **Step 8: Commit**

```powershell
git add sidecar/csm_sidecar/routes/xhs.py sidecar/csm-sidecar.spec sidecar/tests/test_xhs_image_routes.py
git commit -m "feat(xhs): 图片上传/serve 路由 + 级联清理 + 打包登记 (P2 T2)"
```

---

## Task 3: store 图片 actions

**Files:**
- Modify: `frontend/src/stores/xhs.ts`
- Test: `frontend/src/stores/__tests__/xhs.spec.ts`（追加）

加 `uploadImage`/`removeImage`/`setCover`/`reorderImages` 四个 action；改 `isEmpty`（图片也算「有内容」）和 `_ensureCreated`（加 `force` 参数，让上传能给空草稿强制建 id）。`image_ids`/`cover_index` 已在 P0 的 state 与 `_payload()` 里，落盘走既有去抖 PATCH。

- [ ] **Step 1: 追加失败测试**

在 `frontend/src/stores/__tests__/xhs.spec.ts` **末尾**追加：

```typescript
describe("useXhs — 图片", () => {
  it("isEmpty 也看图片：有图即非空", () => {
    const x = useXhs();
    expect(x.isEmpty).toBe(true);
    x.$patch({ imageIds: ["a"] });
    expect(x.isEmpty).toBe(false);
  });

  it("uploadImage：空草稿也强制建 draft，再 POST 图片，把 id 推进 imageIds", async () => {
    postMock.mockResolvedValueOnce({ data: { id: "d1" } });            // _ensureCreated(force) 建草稿
    postMock.mockResolvedValueOnce({ data: { image_id: "img1", url: "/api/xhs/images/img1", size: 9 } }); // 上传
    patchMock.mockResolvedValue({ data: {} });
    const x = useXhs();
    const file = new File([new Uint8Array([1, 2, 3])], "a.png", { type: "image/png" });
    await x.uploadImage(file);
    expect(postMock).toHaveBeenCalledTimes(2);
    expect(x.draftId).toBe("d1");
    expect(postMock.mock.calls[1][0]).toBe("/api/xhs/drafts/d1/images");
    expect(x.imageIds).toEqual(["img1"]);
  });

  it("setCover 设封面下标", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b", "c"] });
    x.setCover(2);
    expect(x.coverIndex).toBe(2);
  });

  it("removeImage：删封面前的图，封面下标左移保持指向同一张", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b", "c"], coverIndex: 2 }); // 封面是 c
    x.removeImage(0); // 删 a
    expect(x.imageIds).toEqual(["b", "c"]);
    expect(x.coverIndex).toBe(1); // 仍指向 c
  });

  it("removeImage：删的就是封面，封面回退且不越界", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b"], coverIndex: 1 });
    x.removeImage(1); // 删封面 b
    expect(x.imageIds).toEqual(["a"]);
    expect(x.coverIndex).toBe(0);
  });

  it("removeImage：删到空，封面归 0", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a"], coverIndex: 0 });
    x.removeImage(0);
    expect(x.imageIds).toEqual([]);
    expect(x.coverIndex).toBe(0);
  });

  it("reorderImages：移动后封面跟随原图", () => {
    const x = useXhs();
    x.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0 }); // 封面 a
    x.reorderImages(0, 2); // a 移到末尾 → [b, c, a]
    expect(x.imageIds).toEqual(["b", "c", "a"]);
    expect(x.coverIndex).toBe(2); // 封面仍是 a
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run（`frontend/`）: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: FAIL —— `x.uploadImage is not a function` 等。

- [ ] **Step 3: 改 store**

在 `frontend/src/stores/xhs.ts` 的 `getters` 里，把 `isEmpty` 一行改为（加图片判断）：

```typescript
    isEmpty: (s): boolean =>
      s.title.trim() === "" && s.body.trim() === "" && s.imageIds.length === 0,
```

把 `_ensureCreated` 方法替换为（加 `force` 参数；上传图片时 force=true，绕过 isEmpty 门）：

```typescript
    /** 首次有内容时建草稿拿 id；空草稿不建（避免堆积）。返回 draftId 或 null。
     *  force=true 时无视 isEmpty 强制建（上传图片场景：上传动作本身即内容）。
     *  用 _creating 去重：并发调用复用同一个 in-flight POST，防止建出孤儿草稿。 */
    async _ensureCreated(force = false): Promise<string | null> {
      if (this.draftId) return this.draftId;
      if (!force && this.isEmpty) return null;
      if (_creating) return _creating;
      _creating = (async () => {
        try {
          const sidecar = useSidecar();
          const r = await sidecar.client.post("/api/xhs/drafts", this._payload());
          this.draftId = r.data.id;
          return this.draftId;
        } finally {
          _creating = null;
        }
      })();
      return _creating;
    },
```

在 `actions` 里，`deleteDraft` 之前（或任意合适位置）追加四个图片 action：

```typescript
    /** 上传一张图片：强制确保草稿存在 → multipart POST → 把 image_id 推进 imageIds → 去抖保存。
     *  失败（如 400 超限/非图）向上抛，由调用方（ImagePanel）toast。 */
    async uploadImage(file: File): Promise<void> {
      const id = await this._ensureCreated(true);
      if (!id) return;
      const sidecar = useSidecar();
      const form = new FormData();
      form.append("file", file);
      const r = await sidecar.client.post(`/api/xhs/drafts/${id}/images`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      this.imageIds.push(r.data.image_id);
      this.scheduleSave();
    },
    /** 删第 i 张图。封面下标随之修正：删封面前的图→左移；删的就是封面或越界→夹回合法范围。
     *  文件删除由后端 PATCH diff（image_ids 变化）负责。 */
    removeImage(i: number): void {
      if (i < 0 || i >= this.imageIds.length) return;
      const removedWasCover = i === this.coverIndex;
      this.imageIds.splice(i, 1);
      if (this.imageIds.length === 0) {
        this.coverIndex = 0;
      } else if (removedWasCover) {
        this.coverIndex = Math.min(this.coverIndex, this.imageIds.length - 1);
      } else if (i < this.coverIndex) {
        this.coverIndex -= 1;
      }
      this.scheduleSave();
    },
    /** 设第 i 张为封面。 */
    setCover(i: number): void {
      if (i < 0 || i >= this.imageIds.length) return;
      this.coverIndex = i;
      this.scheduleSave();
    },
    /** 把第 from 张移到 to 位；封面下标跟随原封面图。 */
    reorderImages(from: number, to: number): void {
      const n = this.imageIds.length;
      if (from === to || from < 0 || from >= n || to < 0 || to >= n) return;
      const coverId = this.imageIds[this.coverIndex];
      const [moved] = this.imageIds.splice(from, 1);
      this.imageIds.splice(to, 0, moved);
      const newCover = this.imageIds.indexOf(coverId);
      if (newCover >= 0) this.coverIndex = newCover;
      this.scheduleSave();
    },
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run src/stores/__tests__/xhs.spec.ts`
Expected: PASS（P0/P1 既有 + P2 新增 7 例全绿）。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/stores/xhs.ts frontend/src/stores/__tests__/xhs.spec.ts
git commit -m "feat(xhs): store 图片 actions uploadImage/removeImage/setCover/reorderImages (P2 T3)"
```

---

## Task 4: ImagePanel.vue + 接入 PanelRail

**Files:**
- Create: `frontend/src/components/xhs/panels/ImagePanel.vue`
- Modify: `frontend/src/components/xhs/PanelRail.vue`（image tab 接 ImagePanel）
- Test: `frontend/src/components/xhs/panels/__tests__/ImagePanel.spec.ts`

面板：顶部「上传图片」按钮（触发隐藏 `<input type=file accept=image/jpeg,image/png,image/webp multiple>`）→ 逐个 `xhs.uploadImage(f)`（try/catch + toast）；下方缩略图网格：每张 `<img :src="sseURL('/api/xhs/images/'+id)">`，带封面角标（`coverIndex`）、设为封面、删除（×）、**原生 HTML5 拖拽排序**（`@dragstart`/`@dragover.prevent`/`@drop` → `xhs.reorderImages`）。空态提示。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/panels/__tests__/ImagePanel.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({
    client: {
      get: vi.fn(),
      post: vi.fn().mockResolvedValue({ data: { id: "d1" } }),
      patch: vi.fn().mockResolvedValue({ data: {} }),
      delete: vi.fn(),
    },
    sseURL: (p: string) => `MOCK${p}`,
  }),
}));
vi.mock("@/composables/useToast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

import ImagePanel from "@/components/xhs/panels/ImagePanel.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("ImagePanel", () => {
  it("无图时显示空态、有图时渲染缩略图（sseURL）", async () => {
    const store = useXhs();
    let w = mount(ImagePanel);
    expect(w.findAll("img.xhs-thumb-img")).toHaveLength(0);
    w.unmount();

    store.$patch({ imageIds: ["a", "b"], coverIndex: 0 });
    w = mount(ImagePanel);
    const imgs = w.findAll("img.xhs-thumb-img");
    expect(imgs).toHaveLength(2);
    expect(imgs[0].attributes("src")).toBe("MOCK/api/xhs/images/a");
    w.unmount();
  });

  it("选文件 → 逐个 uploadImage", async () => {
    const store = useXhs();
    const spy = vi.spyOn(store, "uploadImage").mockResolvedValue();
    const w = mount(ImagePanel);
    const input = w.find('input[type="file"]');
    const f1 = new File([new Uint8Array([1])], "a.png", { type: "image/png" });
    const f2 = new File([new Uint8Array([2])], "b.png", { type: "image/png" });
    Object.defineProperty(input.element, "files", { value: [f1, f2], configurable: true });
    await input.trigger("change");
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenNthCalledWith(1, f1);
    expect(spy).toHaveBeenNthCalledWith(2, f2);
    w.unmount();
  });

  it("点删除 → removeImage(i)", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b"], coverIndex: 0 });
    const spy = vi.spyOn(store, "removeImage");
    const w = mount(ImagePanel);
    await w.findAll(".xhs-thumb-del")[1].trigger("click");
    expect(spy).toHaveBeenCalledWith(1);
    w.unmount();
  });

  it("点设为封面 → setCover(i)", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b"], coverIndex: 0 });
    const spy = vi.spyOn(store, "setCover");
    const w = mount(ImagePanel);
    await w.findAll(".xhs-thumb-cover")[1].trigger("click");
    expect(spy).toHaveBeenCalledWith(1);
    w.unmount();
  });

  it("drop 到另一张 → reorderImages(from,to)", async () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b", "c"], coverIndex: 0 });
    const spy = vi.spyOn(store, "reorderImages");
    const w = mount(ImagePanel);
    const thumbs = w.findAll(".xhs-thumb");
    await thumbs[0].trigger("dragstart");
    await thumbs[2].trigger("drop");
    expect(spy).toHaveBeenCalledWith(0, 2);
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/panels/__tests__/ImagePanel.spec.ts`
Expected: FAIL —— 无法解析 `@/components/xhs/panels/ImagePanel.vue`。

- [ ] **Step 3: 实现 ImagePanel.vue**

Create `frontend/src/components/xhs/panels/ImagePanel.vue`：

```vue
<script setup lang="ts">
/**
 * 图片面板（设计稿 §5「图片」/ P2）。上传 / 缩略图 / 拖拽排序 / 设封面 / 删除。
 * 上传走 store.uploadImage（强制建草稿 → multipart POST → 推 imageIds）；
 * 缩略图 src = sseURL("/api/xhs/images/{id}")；排序用原生 HTML5 拖拽。
 */
import { ref } from "vue";
import Icon from "@/components/ui/Icon.vue";
import { useXhs } from "@/stores/xhs";
import { useSidecar } from "@/stores/sidecar";
import { useToast } from "@/composables/useToast";

const xhs = useXhs();
const sidecar = useSidecar();
const toast = useToast();

const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const dragIndex = ref<number | null>(null);

function thumbUrl(id: string): string {
  return sidecar.sseURL(`/api/xhs/images/${id}`);
}

function openPicker() {
  fileInput.value?.click();
}

async function onFilesPicked(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  if (!files.length) return;
  uploading.value = true;
  try {
    for (const f of files) {
      try {
        await xhs.uploadImage(f);
      } catch {
        toast.error(`「${f.name}」上传失败（仅支持 5MB 内的 jpg/png/webp）`);
      }
    }
  } finally {
    uploading.value = false;
    input.value = ""; // 允许重选同一文件
  }
}

function onDragStart(i: number) {
  dragIndex.value = i;
}
function onDrop(i: number) {
  if (dragIndex.value !== null && dragIndex.value !== i) {
    xhs.reorderImages(dragIndex.value, i);
  }
  dragIndex.value = null;
}
function onDragEnd() {
  dragIndex.value = null;
}
</script>

<template>
  <div class="flex h-full flex-col" :style="{ gap: '12px' }">
    <!-- 上传 -->
    <button type="button" class="xhs-upload-btn" :disabled="uploading" @click="openPicker">
      <Icon name="upload" :size="15" />
      {{ uploading ? '上传中…' : '上传图片' }}
    </button>
    <input
      ref="fileInput"
      type="file"
      accept="image/jpeg,image/png,image/webp"
      multiple
      :style="{ display: 'none' }"
      @change="onFilesPicked"
    />
    <div :style="{ fontSize: '11px', color: 'var(--ink-2)', flexShrink: 0 }">
      支持 jpg / png / webp，单张 ≤ 5MB；拖动缩略图可排序，第一张或设为封面的那张是笔记封面。
    </div>

    <!-- 空态 -->
    <div
      v-if="!xhs.imageIds.length"
      class="flex flex-col items-center justify-center"
      :style="{
        flex: 1, gap: '8px', color: 'var(--ink-2)', fontSize: '13px', textAlign: 'center',
        border: '1px dashed var(--line-2)', borderRadius: '12px', padding: '28px 16px',
      }"
    >
      <Icon name="image" :size="26" />
      <div>还没有图片，点上方「上传图片」添加</div>
    </div>

    <!-- 缩略图网格 -->
    <div
      v-else
      class="min-h-0 flex-1 overflow-y-auto"
      :style="{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', alignContent: 'flex-start' }"
    >
      <div
        v-for="(id, i) in xhs.imageIds"
        :key="id"
        class="xhs-thumb"
        draggable="true"
        :style="{
          position: 'relative', aspectRatio: '1 / 1', borderRadius: '10px', overflow: 'hidden',
          border: i === xhs.coverIndex ? '2px solid var(--primary)' : '1px solid var(--line-2)',
          opacity: dragIndex === i ? 0.4 : 1, cursor: 'grab',
        }"
        @dragstart="onDragStart(i)"
        @dragover.prevent
        @drop="onDrop(i)"
        @dragend="onDragEnd"
      >
        <img
          class="xhs-thumb-img"
          :src="thumbUrl(id)"
          :style="{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }"
          draggable="false"
        />
        <!-- 封面角标 -->
        <span
          v-if="i === xhs.coverIndex"
          :style="{
            position: 'absolute', top: '4px', left: '4px', fontSize: '10px', color: '#fff',
            background: 'var(--primary)', borderRadius: '6px', padding: '1px 6px',
          }"
        >封面</span>
        <!-- 删除 -->
        <button
          type="button"
          class="xhs-thumb-del"
          title="删除"
          :style="{
            position: 'absolute', top: '4px', right: '4px', width: '20px', height: '20px',
            borderRadius: '999px', background: 'rgba(0,0,0,0.5)', color: '#fff', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }"
          @click="xhs.removeImage(i)"
        ><Icon name="x" :size="12" /></button>
        <!-- 设为封面 -->
        <button
          v-if="i !== xhs.coverIndex"
          type="button"
          class="xhs-thumb-cover"
          :style="{
            position: 'absolute', bottom: '0', left: '0', right: '0', fontSize: '10px',
            background: 'rgba(0,0,0,0.45)', color: '#fff', cursor: 'pointer', padding: '2px 0',
            border: 'none',
          }"
          @click="xhs.setCover(i)"
        >设为封面</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.xhs-upload-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-shrink: 0;
  font-size: 13px;
  padding: 9px 14px;
  border-radius: 10px;
  border: 1px solid var(--primary);
  background: var(--primary);
  color: #fff;
  cursor: pointer;
  transition: filter 0.15s;
}
.xhs-upload-btn:hover {
  filter: brightness(0.97);
}
.xhs-upload-btn:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
```

- [ ] **Step 4: 接入 PanelRail**

在 `frontend/src/components/xhs/PanelRail.vue` 的 `<script setup>`：① 在其它 panel import 旁加 `import ImagePanel from "./panels/ImagePanel.vue";`；② 在 `PANEL_COMPONENTS` 对象里加 `image: ImagePanel,`（放在 `decoration` 之后）。其余不动（`ai` 仍走占位）。改完后 `PANEL_COMPONENTS` 形如：

```typescript
const PANEL_COMPONENTS: Partial<Record<XhsPanel, Component>> = {
  template: TemplatePanel,
  theme: ThemePanel,
  emoji: EmojiPanel,
  title: TitlePanel,
  copy: CopyPanel,
  topic: TopicPanel,
  decoration: DecorationPanel,
  image: ImagePanel,
};
```

- [ ] **Step 5: 跑测试 + 类型检查确认通过**

Run: `npx vitest run src/components/xhs/panels/__tests__/ImagePanel.spec.ts`
Expected: PASS（空态/缩略图/选文件/删除/设封面/拖拽 5 例全绿）。

Run: `npx vue-tsc -b`
Expected: 零错误（PanelRail 接入 ImagePanel 类型正确；产物按前置说明还原）。

- [ ] **Step 6: Commit**

```powershell
git add frontend/src/components/xhs/panels/ImagePanel.vue frontend/src/components/xhs/panels/__tests__/ImagePanel.spec.ts frontend/src/components/xhs/PanelRail.vue
git commit -m "feat(xhs): 图片面板 ImagePanel（上传/缩略图/拖拽排序/封面/删除）+ 接入 PanelRail (P2 T4)"
```

---

## Task 5: PhonePreview 显示真实封面

**Files:**
- Modify: `frontend/src/components/xhs/PhonePreview.vue`
- Test: `frontend/src/components/xhs/__tests__/PhonePreview.spec.ts`（新建）

把笔记页与发现页的**封面占位渐变块**换成：有图时 `<img>` 显示封面图（`sseURL` + `coverIndex`，越界回退首张），无图时保留占位渐变块（文案去掉「P2 上传」字样）。

- [ ] **Step 1: 写失败测试**

Create `frontend/src/components/xhs/__tests__/PhonePreview.spec.ts`：

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";

vi.mock("@/stores/sidecar", () => ({
  useSidecar: () => ({ sseURL: (p: string) => `MOCK${p}` }),
}));
vi.mock("@/stores/config", () => ({
  useConfig: () => ({ data: { user_name: "测试号" } }),
}));

import PhonePreview from "@/components/xhs/PhonePreview.vue";
import { useXhs, _resetXhsModuleState } from "@/stores/xhs";

beforeEach(() => {
  setActivePinia(createPinia());
  _resetXhsModuleState();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("PhonePreview 封面", () => {
  it("无图时不渲染封面 img", () => {
    useXhs();
    const w = mount(PhonePreview);
    expect(w.find("img.xhs-cover-img").exists()).toBe(false);
    w.unmount();
  });

  it("笔记页有图时封面渲染真实 img（按 coverIndex）", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a", "b"], coverIndex: 1, previewTab: "note" });
    const w = mount(PhonePreview);
    const img = w.find("img.xhs-cover-img");
    expect(img.exists()).toBe(true);
    expect(img.attributes("src")).toBe("MOCK/api/xhs/images/b");
    w.unmount();
  });

  it("coverIndex 越界时回退首张", () => {
    const store = useXhs();
    store.$patch({ imageIds: ["a"], coverIndex: 5, previewTab: "note" });
    const w = mount(PhonePreview);
    expect(w.find("img.xhs-cover-img").attributes("src")).toBe("MOCK/api/xhs/images/a");
    w.unmount();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run src/components/xhs/__tests__/PhonePreview.spec.ts`
Expected: FAIL —— 找不到 `img.xhs-cover-img`（当前是占位 div）。

- [ ] **Step 3: 改 PhonePreview.vue**

在 `<script setup>` 里，`const cfg = useConfig();` 之后加 sidecar + 封面 URL computed：

```typescript
import { useSidecar } from "@/stores/sidecar";
```

（把这行加到顶部 import 区，与现有 `import { useConfig } ...` 同段。）然后在 `const cfg = useConfig();` 之后加：

```typescript
const sidecar = useSidecar();

const coverUrl = computed<string | null>(() => {
  if (!xhs.imageIds.length) return null;
  const idx = xhs.coverIndex >= 0 && xhs.coverIndex < xhs.imageIds.length ? xhs.coverIndex : 0;
  return sidecar.sseURL(`/api/xhs/images/${xhs.imageIds[idx]}`);
});
```

**笔记页封面**：把现有「封面（P0 占位）」那个 `<div>`（`width:100%; aspectRatio:3/4; ... 封面图（P2 上传）`）整块替换为：

```vue
        <!-- 封面：有图显示真实封面，无图占位 -->
        <img
          v-if="coverUrl"
          class="xhs-cover-img"
          :src="coverUrl"
          :style="{ width: '100%', aspectRatio: '3 / 4', objectFit: 'cover', display: 'block', borderRadius: '20px 20px 0 0' }"
        />
        <div
          v-else
          :style="{
            width: '100%', aspectRatio: '3 / 4',
            background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'var(--primary)', fontSize: '13px', borderRadius: '20px 20px 0 0',
          }"
        >
          暂无封面（左侧「图片」上传）
        </div>
```

**发现页封面**：把发现页卡片里的封面 `<div>`（`width:100%; aspectRatio:3/4; ... 封面`）整块替换为：

```vue
          <img
            v-if="coverUrl"
            class="xhs-cover-img"
            :src="coverUrl"
            :style="{ width: '100%', aspectRatio: '3 / 4', objectFit: 'cover', display: 'block' }"
          />
          <div
            v-else
            :style="{
              width: '100%', aspectRatio: '3 / 4',
              background: 'linear-gradient(135deg, #ffe3d3, #ffd0b5)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--primary)', fontSize: '11px',
            }"
          >封面</div>
```

> 其余（作者条 / 标题 / 正文 / 话题 / 互动栏）一律不动。

- [ ] **Step 4: 跑测试 + 类型检查确认通过**

Run: `npx vitest run src/components/xhs/__tests__/PhonePreview.spec.ts`
Expected: PASS（无图/笔记页封面/越界回退 3 例绿）。

Run: `npx vue-tsc -b`
Expected: 零错误。

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/components/xhs/PhonePreview.vue frontend/src/components/xhs/__tests__/PhonePreview.spec.ts
git commit -m "feat(xhs): 预览显示真实封面图 + PhonePreview 测试 (P2 T5)"
```

---

## Task 6: 全量验证 + 手动验收

**Files:** 无（仅验证）

- [ ] **Step 1: 全量后端测试**

```powershell
$env:PYTHONPATH = "D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\sidecar;D:\CSM\.claude\worktrees\cranky-varahamihira-d53003"
& "D:\CSM\.venv\Scripts\python.exe" -m pytest sidecar/tests/test_xhs_images_service.py sidecar/tests/test_xhs_image_routes.py sidecar/tests/test_xhs_storage.py sidecar/tests/test_xhs_routes.py sidecar/tests/test_health.py -v
```
Expected: PASS（图片 service 17 + 图片路由 9 + 草稿 storage/routes（P0）+ health；确认 patch/delete 改动无回归、app 仍能起）。

- [ ] **Step 2: 全量前端测试**

Run（`frontend/`）: `npx vitest run`
Expected: PASS（既有 193 + P2 新增：store 图片 7 + ImagePanel 5 + PhonePreview 3 = 15，共 ~208）。

- [ ] **Step 3: 类型检查 + 构建门禁**

Run: `npx vue-tsc -b` → 零错误（产物按前置还原）。
Run: `npm run build` → 成功。

- [ ] **Step 4: 手动验收（启动浏览器 dev）**

双击 `D:\CSM\.claude\worktrees\cranky-varahamihira-d53003\.csm-dev\启动小红书测试.bat`（跑 worktree 源码 + PYTHONPATH 覆盖，sidecar 会带上 P2 图片路由），打开 `http://localhost:5173/#/xhs`，逐条对照设计稿 §7 P2：

  1. 左栏「图片」面板：点「上传图片」→ 选 jpg/png/webp → 缩略图出现；连传多张。
  2. 拖动缩略图换序 → 顺序变；首张/封面那张角标「封面」。
  3. 点某张「设为封面」→ 角标移动；右侧预览（笔记页）封面图随之更新。
  4. 点缩略图「×」删除 → 缩略图消失；若删的是封面，封面回退到剩余某张。
  5. 右侧预览：笔记页大图封面 = 封面图；发现页卡片封面 = 封面图；无图时回退占位渐变块。
  6. 停 ~1 秒自动保存（顶部「已保存」）；**刷新页面 / 重开该草稿 → 图片与封面仍在**。
  7. 删整篇草稿（顶部草稿下拉的删除）→ 该草稿图片文件级联清除（可在 `%LOCALAPPDATA%\CSM-Data\xhs_images\{draftId}\` 确认目录已删）。
  8. 异常：传一个 > 5MB 的图 / 传一个 .txt 改名 .png（非真图）→ toast 报错、不入网格。

- [ ] **Step 5: 收尾**

确认 `git status` 干净（无残留 `vite.config.js` / `.d.ts` / `package-lock.json` 改动 / `.log`）。P2 全部任务已各自 commit，无需额外提交。

---

## Self-Review（写完计划后自查）

**1. Spec coverage（设计稿 §1 P2 / §2 / §3.2 / §8）**
- 上传（multipart + magic-byte + 5MB）→ service T1 + 路由 T2 ✓
- 落盘 `xhs_images/{draft_id}/{uuid}.{ext}` + uuid 不可枚举 + `..` 防护 → T1 `save_image`/`get_image_path` ✓
- 前端取图 `sseURL("/api/xhs/images/{id}")` → ImagePanel T4 + PhonePreview T5 ✓
- 缩略图 / 拖拽排序 / 设封面 / 删除 → store T3 + ImagePanel T4 ✓
- 预览显真实图（笔记页轮播首图=封面 / 发现页卡片=封面）→ PhonePreview T5 ✓（P2 先显单张封面，不做多图轮播——§4.3 措辞是「首图=封面」，单图封面已满足；多图轮播非 §7 验收项）
- 删草稿级联删目录 + 删单图删文件（§8）→ T1 `delete_draft_images` + T2 `delete_draft`/`patch_draft` diff ✓
- 打包：service 新模块 → T2 spec hiddenimport ✓（routes.xhs 已 P0 登记；catch-all 数据文件无需改）

**2. Placeholder scan**：无 TBD/TODO；每步含完整代码 / 命令 / 期望输出。

**3. Type consistency**：
- service 三函数贯穿一致：`save_image(draft_id: str, content) -> str`、`get_image_path(image_id) -> Path|None`、`delete_images(list[str])`、`delete_draft_images(draft_id: str)`（T1 定义，T2 路由调用一致）。
- 上传响应形状 `{image_id, url, size}`（T2 路由）↔ store `uploadImage` 读 `r.data.image_id`（T3）↔ ImagePanel 不直接读响应（走 store）一致。
- store 新增 `uploadImage(file)`/`removeImage(i)`/`setCover(i)`/`reorderImages(from,to)` + `_ensureCreated(force=false)`（T3 定义；ImagePanel T4 调用一致）。
- `imageIds`/`coverIndex` state + `_payload()` 的 `image_ids`/`cover_index`（P0 已有，未改名）；后端 `update_draft(image_ids=, cover_index=)`（P0 已有）。
- 测试类名钩子：`.xhs-thumb`/`.xhs-thumb-img`/`.xhs-thumb-del`/`.xhs-thumb-cover`（ImagePanel T4）、`.xhs-cover-img`（PhonePreview T5）—— 实现与测试两侧对齐。
- `sseURL` 用法：组件内 `sidecar.sseURL("/api/xhs/images/"+id)`（T4/T5），与 mining `FloorItem` 惯例一致。

---

## Execution Handoff

依赖顺序：**T1（service）→ T2（路由，依赖 T1）** 是后端；**T3（store）** 前端地基；**T4（ImagePanel，依赖 T3）→ T5（PhonePreview，依赖 T3）** 前端 UI；**T6** 收尾。T4/T5 都只依赖 T3，可顺序做。

两种执行方式：
1. **子代理逐任务（推荐）** —— 每任务派新 subagent + 两阶段评审（规格 → 质量），与 P0/P1 同套路。
2. **本会话内逐任务执行** —— executing-plans，批量带检查点。
