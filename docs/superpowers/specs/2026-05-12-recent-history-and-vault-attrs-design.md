# 历史索引目录统一 + 段落筛选属性双下拉 + Templates/Skills 自动默认

- 日期：2026-05-12
- 分支：`claude/heuristic-tesla-4d047a`
- 范围：sidecar startup、AppConfig、export_service、aggregation_service、BlockEditor、SettingsView、RecentDocsCard/RecentHistoryView

## 背景

用户在 0.4.x release 上发现三个相关问题：

1. **段落筛选属性下拉拉不到数据。** BlockEditor 在新建模板编辑段落区块时，"筛选" key 下拉常驻显示 `尚未扫描素材库 — 在设置里指定 Vault 后重试`。根因是 sidecar 的 vault 索引是进程内内存缓存（`vault_service._index`），sidecar 重启就清空；前端每次冷启动都得用户手动到 Vault 管理或 dedup 重建里触发一次扫描才能填上下拉。
2. **"最近文档"和实际状态对不上。** 卡片源数据走 `/api/recent`，后端从 `out_dir`（导出目录）递归找 .md/.docx 列出；点击文档跳到 ArticleView 但显示空状态——因为 `openDoc` 只是 `router.push({ name: "article" })`，没把磁盘文件读回来。同时用户希望"历史索引目录"和"最近文档目录"是同一个概念。
3. **默认模板目录 / Skills 目录强迫用户配置。** 新装机用户进设置看到这两项都是空，得自己挑路径才能用模板/润色 skill，体验差。

## 目标

- 段落筛选两个下拉（key + value）在配置过 Vault 后**零额外操作**就能展示真实属性和取值。
- "历史索引目录"是用户一眼能找到的单一概念：它既是查重的历史源，也是 RecentDocsCard / RecentHistoryView 的数据源，也是导出时自动复制 .md 副本的目标。
- 默认模板和 Skills 目录在首次启动时自动创建并写进配置，并把仓库内置的样例填充进去，用户无需关心；保留路径选择器让用户后续可改位置。

## 非目标

- 点击最近文档**在应用内**打开历史文章（涉及 article store 改造，单独迭代）。本期点击 → Tauri `shell.open(path)` 调系统默认应用。
- "已发布 / 归档"等状态字段（当前 RecentDocsCard 全标"草稿"）。
- 历史目录的内部统计/查重重建（沿用现有 dedup 链路，不动）。

## 决策与依据

### D1：Templates/Skills 默认目录放在 `%LOCALAPPDATA%\CSM\CSM\` 下，不在安装目录

- 安装目录在 Windows NSIS 默认路径 `AppData\Local\Programs\CSM` 通常可写，但用户改装到 `Program Files` 就 ACL 受限；
- 用户数据放安装目录会被卸载/重装清掉，跨版本不可继承；
- 复用 `core_config.default_config_dir()`（已在 Win/macOS/Linux 三平台正确解析），新增 `default_templates_dir() / default_skills_dir() / default_history_dir()` 三个 helper 即可。

### D2：历史目录沿用 `AppConfig.dedup_history_dir` 字段，**不**新增字段

- 该字段已在用户的 `settings.json` 里，新增会引入"两个看起来一样的目录"的认知负担；
- 它原本就是查重历史源，扩成"成稿镜像 + 最近文档源 + 查重源"三合一是语义升级，不破坏现有 dedup 链路；
- 设置 UI 把 dedup section 的 PathField 降级为展示 + hint 指向"存储路径" section，避免双份编辑入口。

### D3：历史镜像统一存 .md，docx 也合成 .md

- 历史目录是应用内部数据源（最近文档、字数统计、未来查重索引），统一 .md 才好解析；
- 用户实际拿走的 docx 仍在 `out_dir` 不动；
- 镜像 .md 注入 frontmatter（`title / keyword / template / words / exported_at / source_format`），后续聚合不用再开 docx。

### D4：vault 属性 fallback 阈值 = 20

- 后端 `/api/vault/attributes` 已对 `sample_values` 截断 20，前端阈值对齐；
- `value_count > 20` 的 key（典型如"标题"）下拉一千行没意义，回退到现有 free-text input。

### D5：点击最近文档 = `shell.open`，不做应用内打开

- 立即可见，工作量小；
- 应用内打开（读 md → 灌 store → ArticleView 历史模式）改动面大，留作后续迭代。

## 详细设计

### 1. csm_core/config.py

新增三个 path helper：

```python
def default_templates_dir() -> Path:
    return default_config_dir() / "Templates"

def default_skills_dir() -> Path:
    return default_config_dir() / "Skills"

def default_history_dir() -> Path:
    return default_config_dir() / "History"
```

没有动 `AppConfig` 字段类型/默认值（默认仍是空字符串 / `None`），首次填充由 sidecar startup 负责，让 csm_core 保持纯数据模型语义。

### 2. Sidecar startup hook

在 `csm_sidecar/main.py`（FastAPI lifespan 或现有 startup event）里新增 `ensure_default_dirs()` + `auto_scan_vault()`，**在 sidecar 监听端口前同步运行**：

```python
def ensure_default_dirs() -> None:
    cfg = config_service.load()
    patches: dict[str, Any] = {}

    for field, default_fn, seed_fn in [
        ("default_template", core_config.default_templates_dir, _seed_templates),
        ("skill_dir",        core_config.default_skills_dir,    _seed_skills),
        ("dedup_history_dir",core_config.default_history_dir,   None),
    ]:
        current = getattr(cfg, field, "") or ""
        target = Path(current) if current else default_fn()
        target.mkdir(parents=True, exist_ok=True)
        if not current:
            patches[field] = str(target)
            if seed_fn:
                seed_fn(target)

    if patches:
        config_service.patch(patches)
```

- `_seed_templates(dst)`：若 `dst` 为空，把仓库内置的 `templates/*.json` 复制进来（PyInstaller bundle 时由 `--add-data` 一并打包；dev 模式从源码 `templates/` 拷）；
- `_seed_skills(dst)`：同理用 `examples/skills/*.md`；
- 这一步幂等，重复调不会重复填。

`auto_scan_vault()`：

```python
async def auto_scan_vault() -> None:
    cfg = config_service.load()
    if not cfg.vault_root:
        return
    root = Path(cfg.vault_root)
    if not root.is_dir():
        return
    try:
        await run_in_threadpool(vault_service.scan, root)
    except Exception as e:
        logger.warning("auto vault scan failed: %s", e)
```

放在 lifespan startup，扫不到/扫挂只 log，不阻塞 sidecar 上线（vault 几百节点的扫描通常 < 2s，但放线程池避免在 event loop 里 block）。

### 3. csm_sidecar/services/export_service.py

`export()` 末尾加：

```python
mirror_path = _mirror_to_history(
    cfg=cfg,
    keyword=keyword,
    final_text=final_text,   # 不带 dedup 报告附录
    fmt=fmt,
    primary_path=paths["markdown_path"] or paths["docx_path"],
)
paths["history_path"] = str(mirror_path) if mirror_path else None
```

`_mirror_to_history()`：

```python
def _mirror_to_history(*, cfg, keyword, final_text, fmt, primary_path) -> Path | None:
    if not cfg.dedup_history_dir:
        return None
    target_dir = Path(cfg.dedup_history_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("history dir not writable, skip mirror: %s", e)
        return None

    stem = Path(primary_path).stem
    target = _dedupe_name(target_dir / f"{stem}.md")

    fm = {
        "title": extract_title(final_text) or stem,
        "keyword": keyword,
        "template": ...,  # 取自调用方传入的 template_name（新增可选参数）
        "words": _count_chars(final_text),
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source_format": fmt,
    }
    post = frontmatter.Post(content=final_text, **fm)
    try:
        target.write_text(frontmatter.dumps(post), encoding="utf-8")
        return target
    except OSError as e:
        logger.warning("history mirror write failed: %s", e)
        return None

def _dedupe_name(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while True:
        candidate = p.with_stem(f"{p.stem}-{i}")
        if not candidate.exists():
            return candidate
        i += 1
```

调用 `export()` 的路由（`POST /api/export`）接 `template_name` 形参（前端在导出时已经持有），透传到 `_mirror_to_history` 写 frontmatter。

### 4. csm_sidecar/services/aggregation_service.py

```python
def _resolve_history_dir() -> Path | None:
    cfg = config_service.load()
    return Path(cfg.dedup_history_dir) if cfg.dedup_history_dir else None
```

`list_recent / calendar_for_month / words_for_range` 三处 `_resolve_out_dir()` 全部替换为 `_resolve_history_dir()`。

`_iter_exported` 改成只 yield `*.md`（历史目录约定只存 md）。

历史目录为空时 `list_recent` 返回 `{"count": 0, "documents": []}`，前端走空状态。

### 5. csm_sidecar/routes/vault.py

`/api/vault/attributes` 行为不动。前端 409 时主动调 `/api/vault/scan` 走"自愈"路径（前端代码段见 §6），不要在路由层硬塞 scan-on-miss——保留路由的纯查询语义，方便测试。

### 6. frontend BlockEditor.vue

**409 自愈：**

```ts
async function loadVaultAttrs() {
  attrsLoading.value = true;
  attrsError.value = null;
  try {
    vaultAttrs.value = await fetchAttrs();
  } catch (e: any) {
    if (e?.response?.status === 409) {
      try {
        await sidecar.client.post("/api/vault/scan", {});
        vaultAttrs.value = await fetchAttrs();
      } catch (inner: any) {
        attrsError.value = inner?.response?.status === 400
          ? "尚未配置素材库 — 请在设置中指定 Vault"
          : (inner?.message ?? String(inner));
        vaultAttrs.value = [];
      }
    } else {
      attrsError.value = e?.message ?? String(e);
      vaultAttrs.value = [];
    }
  } finally {
    attrsLoading.value = false;
  }
}
```

**value 多选下拉（新组件 `MultiValuePicker.vue`）：**

```vue
<MultiValuePicker
  :model-value="row.value"
  :options="valueOptionsFor(row.key)"
  :allow-free-text="valueOptionsFor(row.key).length === 0"
  placeholder="选择值…"
  @update:model-value="(v) => updateFilterRow(i, { value: v })"
/>
```

`valueOptionsFor(key)`：

```ts
function valueOptionsFor(key: string): string[] {
  const meta = vaultAttrs.value.find((a) => a.key === key);
  if (!meta) return [];
  if (meta.value_count > 20) return [];   // 阈值，回退手填
  return meta.sample_values;
}
```

组件内部行为：
- 接收/输出仍是逗号分隔字符串（与 `commitFilters` 兼容）；
- options 非空 → 渲染勾选下拉（复用 BlockEditor link 下拉的 cream + dark hover 样式）；
- options 空且 `allow-free-text=true` → 渲染当前的 free-text `<input>`。

### 7. frontend SettingsView.vue

- 「存储路径」section 增加一行：

  ```vue
  <SettingsRow
    label="历史索引目录"
    hint="成稿镜像 / 最近文档 / 查重历史 — 三合一目录"
  >
    <PathField
      :value="get('dedup_history_dir') ?? ''"
      title="选择历史索引目录"
      @update="(v) => setField('dedup_history_dir', v)"
    />
  </SettingsRow>
  ```

- 「历史查重」section 的"历史索引目录"行降级：去掉 PathField，留一行只读地址 + hint`"到「存储路径」修改"`，"重建"按钮仍在；
- 「默认模板目录」「Skills 目录」hint 加一句`"首次启动已自动建好，可改位置"`。

### 8. frontend RecentDocsCard.vue / RecentHistoryView.vue

```ts
async function openDoc(d: Doc) {
  if (!d.path) return router.push({ name: "article" });   // 兜底
  try {
    const isTauri = ...;
    if (!isTauri) return toast.info(`文件位置：${d.path}`);
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(d.path);
  } catch (e: any) {
    toast.error(`打开失败：${e?.message ?? e}`);
  }
}
```

`capabilities/default.json` 已 allow `shell:allow-open`，无需新增权限。

RecentHistoryView 的「打开」按钮文案：`"打开" → "用默认应用打开"`，icon 仍是 `edit`。

## 数据迁移

无 schema 迁移。`dedup_history_dir` 字段已存在；旧用户如果该字段为空，sidecar startup 会一次性填上默认值（`%LOCALAPPDATA%\CSM\CSM\History`）并 mkdir。**旧用户的"最近文档"在第一次导出新文章前会暂时为空**——可以接受，因为旧 `out_dir` 里的历史文章和"历史索引目录"是两个语义，新概念上线后历史归零是正常的。

需要在 0.4.x → 0.5.0 release notes 提一句"最近文档历史从导出目录改为历史索引目录"。

## 风险与回退

- **风险 A：sidecar startup 时 vault 扫描阻塞太久。** Mitigation：在 lifespan 里 fire-and-forget（`asyncio.create_task`），即使扫描 30s 也不影响 sidecar 上线；前端拿到 409 仍能走自愈路径。
- **风险 B：用户已经手动把 dedup_history_dir 指到非空目录，里面文件不是应用导出的镜像。** Mitigation：`list_recent` 把任何 .md 都列出（频道开放），用户原有 md 文件也会出现在最近文档里——这不是 bug，是新语义。
- **风险 C：seed 内置模板覆盖用户已有同名文件。** Mitigation：`_seed_templates` 只在**首次**（即用户没设过 default_template）执行；且写入前 `if not target.exists()`，撞名跳过。
- **回退路线：** 全部修改在一个 PR、可单独 revert；`dedup_history_dir` 字段保持向后兼容（语义升级不破坏 dedup 模块本身）。

## 测试计划

### Sidecar
- `tests/test_startup_hooks.py`：
  - `ensure_default_dirs` 在空 config 上填充三个字段并 mkdir；
  - 已有字段不被覆盖；
  - `_seed_templates` 把仓库样例复制到空目录，目录非空时不再复制。
- `tests/test_export_history_mirror.py`：
  - markdown 导出 → 历史目录有同名 .md，frontmatter 含 keyword/template/words/exported_at；
  - docx 导出 → 历史目录有 .md 且正文是 `final_text`；
  - 撞名 → 出现 `<name>-2.md`；
  - `dedup_history_dir` 不可写 → log warning，主导出仍成功。
- `tests/test_aggregation_routes.py`（更新）：
  - `list_recent` 数据源从 history dir 取，out_dir 里的文件不再出现；
  - history dir 不存在 → 返回空。
- `tests/test_vault_routes.py`（更新）：
  - `/api/vault/attributes` 409 行为不变；
  - 启动钩子触发的扫描后 attributes 可拿。

### Frontend
- `BlockEditor.test.ts`：
  - 409 → 触发 `/api/vault/scan` → 再 GET attributes；
  - `value_count <= 20` → MultiValuePicker 渲染 options；
  - `value_count > 20` → 回退 input；
- `RecentDocsCard.test.ts`：点击 → `shell.open` 被调用（mock plugin）；
- 手工 smoke：
  - Win11 release 安装包，全新用户 → 打开应用 → 设置「存储路径」三个默认目录都自动填好；
  - 设置 Vault → 重启应用 → BlockEditor 段落筛选下拉直接可用；
  - 导出一篇 md → 历史索引目录出现镜像 .md → 首页「最近文档」立刻显示。

## 实现顺序

1. csm_core helper（3 个 default_*_dir）
2. sidecar startup hook（ensure_default_dirs + auto_scan_vault）+ 单测
3. export_service mirror + 单测
4. aggregation_service 切换数据源 + 单测更新
5. SettingsView UI 调整（PathField 加一行 / dedup section 降级）
6. RecentDocsCard / RecentHistoryView 改 `openDoc` 走 shell.open
7. BlockEditor 409 自愈 + MultiValuePicker 新组件
8. release notes 一行

每步独立 commit，整体一个 PR。
