# Vault 写入器 + 手动录入（Phase 3a）— 设计稿

- 日期：2026-06-26
- 范围：Phase 3「素材入库 + 自动归类」的**地基子项目 3a**。建一个确定性 **Vault 写入器** + `MaterialsView`「录入」tab 的**手动录入表单**，把结构化素材安全写回共享盘 vault（规范 frontmatter / 命名 / 双链 / 索引登记，diff 预览 / 不覆盖 / 可撤销）。**无 AI。**
- 不在本稿范围（留给 **3b**）：粘贴长文 → AI 拆条归类 → 抽 frontmatter → 生成变体 → 待确认方案审阅。3b **复用** 3a 的写入器引擎与「确认入库」UI。
- 上游总纲：[创作台升级路线图](2026-06-23-creation-studio-upgrade-roadmap-design.md) §Phase 3。

---

## 1. 关键发现（实勘真实 vault，2026-06-26，决定了整套方案）

写入器最难的不是写文件，而是「忠于真实库」。实勘 `D:\家电组共享\DATA` 得到三条硬约束：

1. **写入器根本不存在**。`csm_core/vault/` 仅 4 文件（`note_parser`/`scanner`/`brand_registry`/`__init__`），全是读取。`MaterialsView` 的「浏览/录入」是「建设中」占位。Phase 1 设想的「写入器 v1」从未交付。

2. **`CLAUDE.md` 是「理想稿」，真实库才是事实源——二者已严重漂移**：
   - **索引文件名漂移**：§5.2 说产品类回链 `[[吸尘器产品与技术总索引]]`，真实文件叫 `CEWEY产品与技术总索引.md`；§5.2 说人群类 `[[用户人群索引]]`，真实是 `用户人群总索引.md`。
   - **素材类型值漂移**：§3.2 列 10 个标准值，真实库扫出 **21 个**细分值（`科普选购`/`竞品推荐理由`/`引言痛点`/`引言过渡`/`次要技术`/`动力系统`…），且一篇真实科普笔记 `素材类型: 科普选购`——不在标准 10 个里。
   - **索引是人工精编的语义文档**：`吸尘器科普内容索引.md` 含挑选攻略表格、「按技术点查找」、避雷踩坑表格、常见陷阱速查、用户人群关联、被引用笔记等多段交叉引用，链接用**友好显示名**（`吸力选购 | [[吸尘器-吸力参数选购]]`），连自带 dataview 路径都 stale（`FROM ".../科普内容/..."`，真实是 `科普模块`）。→ **自动结构化插入这种索引极易破坏人工编排。**
   - **Obsidian vault 根 = `DATA`**（`关联数据库.md`、`CLAUDE.md` 在此），`营销资料库` 只是子目录；`[[关联数据库]]` 在 vault 全局解析。

3. **三种笔记形状坍缩成两种 body**：
   - **变体 body（①②③…）**：原子内容素材**与技术话术笔记共用**（技术话术 = 变体正文 + `品牌`/`适用型号` frontmatter，与内容素材同形）。
   - **参数表 body（`## 分组` + `| 参数 | 数值 |`）**：仅产品参数笔记用。
   - 真实双链尾本身也不一致（有的缺「返回主页」、有的双 `返回上层`）——属历史脏数据，写入器统一产出**规范尾**。

---

## 2. 决策（已与用户确认）

| # | 决策 | 取舍理由 |
|---|---|---|
| D1 | **先做写入器地基 3a，再做 AI 拆条 3b** | 写入器是 3b 的地基；先把高风险共享盘写入路径（不覆盖/撤销/索引）单独测透，再叠 AI 不确定性。3a 独立可验收。 |
| D2 | **索引策略①**：写入器只写笔记 + 规范双链尾，索引靠 Dataview（按 frontmatter+文件夹查）自动发现；另在对应索引底部一个写入器专属 `## App 新增（待人工归入）` 块幂等追加一行指针，**绝不碰人工表格** | 真实索引是人工语义文档且已漂移，自动结构化插入风险极高；Dataview 本就按 frontmatter 查，笔记落对地方即可见。 |
| D3 | **词表来源 = 扫真实 vault，新笔记对齐邻居** | 选「放进哪个现有文件夹」，写入器从该文件夹现有笔记**推断 frontmatter 形状 + body 形状**，保证与邻居一致、绕开 `CLAUDE.md` 漂移、对新产品线/新类型免维护。 |
| D4 | **3a 覆盖两类笔记：原子内容素材 + 品牌型号记忆** | 内容素材是 3b 的产出形状；品牌记忆（产品参数/技术话术）顺带补 `MaterialsView`「缺参数/缺话术」缺口。二者坍缩成变体/参数表两个 body 渲染器，共用一个写入器引擎。 |

**架构选型**：A「邻居镜像写入器」（D3 落地，已锁）。否决 B「规范 schema」（与漂移打架）、C「裸编辑器+lint」（不结构化）。

---

## 3. 架构总览

```
csm_core/vault/
  folder_profile.py  🆕  邻居推断：扫一个文件夹的现有笔记 → 推断该写什么形状
  writer.py          🆕  确定性写入引擎：plan(纯计算) / commit(落盘+登记) / undo(撤销)
sidecar/csm_sidecar/
  services/vault_writer_service.py  🆕  薄接线：解析 cfg.vault_root、校验路径、盖日期、委托引擎
  routes/vault_writer.py            🆕  GET writable-folders / POST plan|commit|undo
frontend/src/
  views/MaterialsView.vue           ♻️  假 tab 条 → 真 tab（品牌型号 | 录入）
  components/materials/IntakeForm.vue 🆕  文件夹选择 → 自适应表单 → diff 预览 → 确认/撤销
  stores/materials.ts               ♻️  加 intake 动作 + 持最近 receipt
```

**复用现有**：`scan_vault` / `parse_note`（读模型）、`AppConfig.vault_root`（路径）、`SplitPane`/`Pill`/`Spinner`（UI）、brand_memory 真实库测试约定（只读回归门禁）。

---

## 4. 后端核心

### 4.1 邻居推断 `folder_profile.py`

```python
@dataclass(frozen=True)
class FolderProfile:
    rel_folder: str              # POSIX，相对 vault_root，如 "科普模块/吸尘器/挑选攻略"
    frontmatter_keys: list[str]  # 邻居 frontmatter 键的保序并集（产品/素材类型/核心关键词/…）
    defaults: dict[str, str]     # 高频标量值预填（如 {产品: 吸尘器, 素材类型: 科普选购}）
    body_shape: str              # "variants" | "spec_table" | "unknown"
    sample_count: int            # 推断所用邻居数

def profile_folder(index: VaultIndex, rel_folder: str) -> FolderProfile: ...
def list_writable_folders(index: VaultIndex) -> list[FolderProfile]: ...
    # 所有直接含 ≥1 笔记的叶子内容文件夹，各自 profile
```

- **frontmatter_keys**：并集，保序——`产品`/`素材类型`/`核心关键词` 若出现则置顶，余按首见序。
- **defaults**：某标量键在 ≥半数邻居取同一值 → 预填；多值键（核心关键词/型号）不预填只显字段。
- **body_shape 探测**：邻居中含圈码 ①②…（`note.variants` 多条或 raw_body 命中圈码）占多数 → `variants`；含 markdown 表格行（`|---|` 或 `| 参数 | 数值 |`）占多数 → `spec_table`；否则 `unknown`。
- **sample_count=0**（空文件夹）：`frontmatter_keys=[]`、`body_shape="unknown"`，表单回退手填。

### 4.2 写入引擎 `writer.py`（纯函数，不依赖 sidecar）

```python
@dataclass(frozen=True)
class NotePlan:
    rel_folder: str
    filename: str                # 含 .md
    rel_path: str                # rel_folder/filename
    frontmatter: dict[str, Any]  # 按写入序
    body: str                    # 渲染后的 body（变体或参数表）
    backlink_tail: str
    full_text: str               # frontmatter YAML + body + 尾 —— 即 diff 预览展示的文件全文
    index_rel: str | None        # 最近祖先索引（相对路径），无则 None
    index_line: str | None       # 将追加的指针行，无索引则 None
    conflict: bool               # rel_path 已存在
    warnings: list[str]          # 如「无祖先索引，跳过登记」

@dataclass(frozen=True)
class WriteReceipt:
    created_rel: str
    content_sha: str             # 写入内容 sha256，供安全撤销比对
    index_rel: str | None
    index_line: str | None       # 实际追加的那一行（供撤销精确移除）

def plan_note(
    vault_root: Path, *,
    rel_folder: str, filename: str,
    frontmatter: dict[str, Any],
    body_shape: str,                       # "variants" | "spec_table"
    variants: list[str] | None = None,     # body_shape=variants
    spec_rows: list[dict] | None = None,   # body_shape=spec_table，[{group,key,value}]
    today: str,                            # ISO 日期，由调用方传入（测试可定）
) -> NotePlan: ...
    # 纯计算不落盘：解析目标路径、探最近祖先索引、检测同名、渲染 body、拼规范双链尾、
    #   组出 full_text 与 index_line。conflict=True 时禁止 commit。

def commit_note(plan: NotePlan, vault_root: Path) -> WriteReceipt: ...
    # 落盘：rel_path 已存在 → raise FileExistsError（路由转 409）；写 full_text(utf-8)；
    #   若 index_rel：确保「## App 新增（待人工归入）」块存在，再幂等追加 index_line；返回 receipt。
    #   仅写入既有文件夹（不新建目录——文件夹来自 list_writable_folders）。

def undo_write(receipt: WriteReceipt, vault_root: Path) -> list[str]: ...
    # 尽力而为单级撤销，返回 warnings：
    #   created 文件存在且 sha==content_sha → 删；否则跳过 + 警告「文件已被改动，未删除」
    #   index_rel 在 → 移除等于 index_line 的那一行（若仍在）；否则跳过
```

**渲染细节**：
- frontmatter → 用 `python-frontmatter` dumps（`allow_unicode`，保序），列表值走 block 序列（`note_parser` 两种都能读回）。
- 变体 body：`① {v1}\n\n② {v2}\n\n③ {v3}…`（圈码 U+2460 起，与 `VARIANT_MARKERS` 一致）。
- 参数表 body：按 `group` 聚合 → `## {group}\n\n| 参数 | 数值 |\n|------|------|\n| {k} | {v} |…`；无 group 归入单一 `## 参数`。
- **规范双链尾**（最近祖先索引由扫描得出，对 §5.2 死表免疫，向上找最近 `*索引*.md` 到 vault_root 止）：
  ```
  \n\n---\n**返回上层**: [[{索引名}|{索引名}]] | **返回主页**: [[关联数据库]]\n
  ```
- **索引「App 新增」块**：
  ```
  ## App 新增（待人工归入）
  - [[{文件名去.md}]] · {素材类型} · {today}
  ```
  幂等（同链接不重复）、可被 undo 精确移除、绝不触碰块以上的人工内容。

---

## 5. API（同步——本地文件操作快，无需 SSE）

```
GET  /api/vault/writable-folders
       → 200 {folders: [FolderProfile…]}            素材库未配置 → 400
POST /api/vault/plan
       body {rel_folder, filename, frontmatter, body_shape, variants?, spec_rows?}
       → 200 NotePlan（含 full_text/index_line/conflict/warnings）  纯计算不落盘
POST /api/vault/commit
       body 同 plan
       → 200 WriteReceipt | 409 同名已存在 | 400 校验失败（路径逃逸/文件名非法/未配置）
POST /api/vault/undo
       body {receipt}
       → 200 {undone: bool, warnings: [...]}
```

`vault_writer_service.py`：解析 `cfg.vault_root`（None → 400「未配置素材库路径」）；`scan_vault` 取 index；盖 `today`；委托引擎。**校验**：`rel_folder` 必须是 vault_root 下既有目录、解析后仍在根内（防逃逸）；`filename` 非空、无空格、无路径分隔符（`/` 或 `\`）、以 `.md` 结尾。

---

## 6. 前端

### 6.1 `MaterialsView.vue`
假 tab 条 → 真 tab 状态：**品牌型号**（现有只读详情）| **录入**（`<IntakeForm/>`）；**浏览**仍「建设中」（延后）。

### 6.2 `components/materials/IntakeForm.vue`（四步）
1. **选目标位置**：文件夹选择器，源 `store.writableFolders`。每项显相对路径 · 邻居数 · body 徽标（`变体`/`参数表`）· 素材类型值。例：`科普模块/吸尘器/挑选攻略 · 10 篇 · 变体 · 科普选购`。
2. **表单自适应**（读选中 `FolderProfile`）：frontmatter 字段按 `frontmatter_keys` 渲染、`defaults` 预填（核心关键词=标签输入；命中 `人群分类`/`品牌`/`型号`/`适用型号` 才显）；文件名自动建议 `[产品]-[描述]-[核心词].md` 可改并校验；body 按 `body_shape` 渲染 ①②③ 行 或 分组/参数/数值 三列行（增删）。
3. **diff 预览**：防抖调 `plan` → 展示 `full_text` 全文 + 将追加索引行 + 同名冲突红字。
4. **确认入库 / 撤销**：`commit` 成功弹 toast + 露「撤销上次写入」（用最近 receipt）；冲突拦下要求改名。

### 6.3 `stores/materials.ts`
加 `writableFolders`/`loadFolders()`/`selectedFolder`/`plan`(防抖)/`commit()`/`undo()`/`lastReceipt`（单级、会话内）。沿用现有 sidecar client + useNotifications。

---

## 7. 安全 / 边界

- **不覆盖**：`plan` 标 `conflict` → UI 禁「确认」；`commit` 落盘前二次查（防 TOCTOU）→ 竞态出现 409。
- **撤销**：尽力而为单级——仅当 created 内容 sha 未变才删；索引行仅当仍在才移除；被人工改过则跳过 + 警告。
- **路径逃逸**：`rel_folder`/`filename` 解析须在 `vault_root` 内，否则 400。
- **无祖先索引文件夹**：仍写笔记 + 跳过登记 + warning（笔记照样 Dataview 可见）。
- **空文件夹**（邻居 0）：表单回退手填键 + 用户选 body 形状。
- **只写既有文件夹**：不新建目录（文件夹均来自 `list_writable_folders`）。

---

## 8. 测试（共享盘红线）

- **写/撤销测试一律用 pytest `tmp_path` 合成 vault，绝不碰 `D:\家电组共享\DATA`。**
- `tests/core/vault/test_folder_profile.py`：合成 vault（变体文件夹 / 参数表文件夹 / 混合 / 空），断言 `body_shape`/`frontmatter_keys`/`defaults`/`sample_count`。
- `tests/core/vault/test_writer.py`：
  - `plan`：full_text/规范双链尾/index_line/conflict/无索引 warning。
  - `commit`：写文件 + 建「App 新增」块 + 幂等追加（二次同链接不重复）；已存在 → FileExistsError。
  - `undo`：sha 匹配则删、被改动则跳过+警告、精确移除索引行。
- **真实库只读回归**（门禁同 brand_memory 真实库测试：vault_root 不存在则 skip）：`profile_folder` 跑已知文件夹断言 body_shape（挑选攻略→variants、产品参数→spec_table），**只读不 commit**。
- `sidecar/tests/test_vault_writer_routes.py`：cfg 覆盖到 tmp vault，plan/commit/undo/409/400/路径逃逸。
- 前端：`IntakeForm.spec.ts` + materials store intake spec（mock sidecar：选文件夹→自适应→plan 预览→commit/undo）。**推前先 `vue-tsc -b`**（vitest 不做类型检查）。

---

## 9. 留给计划阶段的开放点

1. frontmatter YAML 渲染是否需逐文件夹镜像邻居的列表风格（block vs inline `[…]`）——MVP 统一 block 序列，够用即可。
2. `body_shape="unknown"` 文件夹的手填回退 UX 细节（让用户显式选变体/参数表）。
3. 「App 新增」块的排序/去重粒度（按链接去重已定，是否按日期分组留待 plan）。
4. 撤销是否需跨会话持久化 receipt——MVP 仅会话内单级，足够。

---

## 10. 验收

- 选一个真实文件夹 → 表单正确镜像邻居（键 + body 形状）→ 填内容 → diff 显示规范 .md 全文 → 确认 → 文件按 `CLAUDE.md` 命名/frontmatter/双链落盘 + 「App 新增」块登记 + `MaterialsView`/Obsidian 可见。
- 同名笔记被拒（不覆盖）；撤销能删回刚写的文件 + 移除索引行；被人工改动后撤销安全跳过。
- 全程零写真实共享盘的自动化测试通过；真实库只读回归断言 body_shape 探测正确。
