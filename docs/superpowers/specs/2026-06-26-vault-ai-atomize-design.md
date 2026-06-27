# Phase 3b：AI 拆条归类入库 设计稿

> **诉求①「素材自动归类入库」的自动化部分。** 3a（PR #146，已并入 main）交付了确定性「Vault 写入器 + 手动录入」地基；3b 在其上加一层 AI：粘贴一篇文章/资料 → LLM 拆成原子素材并归类 → 人工审阅修正 → **复用 3a 写入器**逐条落库到共享盘 Obsidian vault。

**日期**：2026-06-27
**分支**：`claude/ai-atomize`
**前置**：3a 已 merge（`writer.py` / `folder_profile.py` / `vault_writer_service` / `/api/vault/{writable-folders,plan,commit,undo}` / `IntakeForm.vue` / materials store intake 切片）

---

## 1. 设计立场：3b 在写入侧极薄

3a 的 `plan_note` / `commit_note` / `undo_write` 引擎 + `/api/vault/{plan,commit,undo}` 端点**原样复用**。3b 只新增 **1 个后端端点（atomize）+ 1 个前端 tab**。`writer.py` 的 docstring 本就是为此写的（"3b reuses the engine, so keep that contract"）。

```
粘贴文章 → POST /api/vault/atomize → N 条 AtomDraft（已归类 + 置信度）
        → N 张可编辑卡片（预填 3a 字段，低置信置顶高亮）
        → 逐条「确认入库 / 撤销」复用 POST /api/vault/{plan,commit,undo}
        →「全部入库」便捷键（循环逐条，默认只扫 high/med，逐条报成败）
```

## 2. 关键复用面（已核对源码）

| 复用项 | 出处 | 用法 |
|---|---|---|
| LLM 客户端 | `services/llm_factory.build_client()` → `LLMClient.complete(system=, user=, temperature=)` | atomize 服务调它；未配 provider → `LLMConfigError` |
| JSON 解析模式 | `services/xhs_ai_service`：`_strip_code_fence` + 正则抠 `{...}` + 逐字段兜底 | 改成抠 `[...]` 数组、逐条兜底 |
| 真实归类菜单 | `csm_core/vault/folder_profile.list_writable_folders(index)` → `FolderProfile{rel_folder, material_types, body_shape, defaults, frontmatter_keys}` | 喂给 LLM 做 grounding；**off-menu 进不了库** |
| 写入引擎 | `csm_core/vault/writer.plan_note/commit_note/undo_write` | 每条原子一次，零改动 |
| 写入端点 | `routes/vault_writer.py`：`/api/vault/{plan,commit,undo}` | 前端逐卡复用；`commit` 端点直接吃 payload、服务端重新 plan+写 |
| 校验 | `vault_writer_service._validate`（路径逃逸 + 文件名规则） | commit 时已兜底 |
| 测试 LLM mock | `tests/test_xhs_ai_service.py`：`_RecordingClient` + `monkeypatch.setattr(service.llm_factory, "build_client", ...)`；503 分支不打 patch | atomize 服务测试照搬 |

## 3. 决策（已与用户敲定）

- **D1 拆条粒度**：**忠实拆分 + 归类**。每条原子 = 一个要点，正文 = 原文措辞，写成**单变体 ①**。不让 AI 改写/扩写（避免事实污染永久库、不与已有「链式增强器」职责重叠）。变体 ②③ 留给链式增强器（用素材时）或人工后补。
- **D2 UI 位置**：MaterialsView 新增**第 3 个顶级 tab「AI 拆条」**（品牌型号 ｜ 录入 ｜ AI 拆条 ｜ 浏览）。手动录入与批量拆条是两种工作流，各自专注。
- **D3 提交粒度**：**逐条为主 +「全部入库」便捷键**。每卡独立 plan/commit/undo（复用 3a 单笔流程）；「全部入库」循环逐条提交、逐条报成功/失败，互不影响（对共享盘最安全、复用代码最多）。不想要的原子不提交即丢弃。
- **D4 归类约束**：**强引导 + 人工定夺**。Prompt 喂真实文件夹菜单让 AI 建议尽量落在菜单内并预填选择器；**最终归属永远是人从真实下拉里选**——off-menu 建议进不了库（选择器只列真实文件夹 + sidecar 校验兜底）。**v1 不自动建文件夹**（结构变更太重，该在 Obsidian 里手动做），无匹配的原子高亮提示，人工丢弃或改选现有文件夹。
- **D5 置信度**：**轻量 high/med/low**（只评归类判断，正文是忠实原文不评）。低置信卡片**置顶 + 高亮**；**「全部入库」默认只扫 high/med，low 必须人工逐条确认**——给批量键加一层对共享盘的保护。不做数值阈值门禁（v1 YAGNI）。

## 4. 后端核心

### 4.1 Unit A —— `csm_core/vault/atomizer.py`（纯函数，无 LLM，高可测）

```python
@dataclass(frozen=True)
class AtomDraft:
    text: str                       # 正文（单变体①，忠实原文）
    rel_folder: str | None          # 已对 allowlist 校验；off-menu → None
    material_type: str              # 素材类型
    product: str                    # 产品：希喂/戴森/小米/追觅/通用
    keyword: str                    # 核心关键词
    filename: str                   # 已 sanitize，.md 结尾
    confidence: str                 # high|med|low（非法 → low）
    warnings: list[str]             # 如「建议文件夹不在库中，请人工选择」

def build_menu(folders: list[FolderProfile]) -> str
    # 只取 body_shape != "spec_table" 的文件夹（产品参数表归 3a 手动录入），
    # 拼成喂 LLM 的菜单：每行「rel_folder ｜ 素材类型: a/b/c」。

def _safe_filename(raw: str, fallback: str) -> str
    # strip；去空格与路径分隔符（/ \）；保证 .md 结尾；空 → fallback（取 keyword）；
    # 中文允许（库里就是中文笔记名）。

def parse_atoms(raw_llm_text: str, folders: list[FolderProfile]) -> list[AtomDraft]
    # ① _strip_code_fence（复用 xhs 同款逻辑）；② json.loads，失败再正则抠第一个 [...]；
    # ③ 逐条：text 必填（空则跳过该条）；建议文件夹 ∈ {f.rel_folder} 才保留、否则 None+warning；
    #    confidence 不在 {high,med,low} → low；filename = _safe_filename(建议文件名 或 keyword)；
    #    缺字段 → 空串。返回 list[AtomDraft]。整体非数组 → 返回 []。
```

`_strip_code_fence`（去 ` ```json ` 围栏）在本单元**就近放 `atomizer.py` 内部私有函数**（v1 自带一份即可，逻辑 ~6 行）；xhs 那份不动（不跨层改既有码，跨模块 DRY 留后续）。`_MAX_INPUT` 取 8000 字（约一篇长文，超长截断 + warning）。

### 4.2 Unit B —— `services/atomize_service.py` + `routes/vault_atomize.py`

```python
# atomize_service.py（镜像 xhs_ai_service 结构）
ATOMIZE_SYSTEM = (...)   # 见 §5；强调忠实拆分、从菜单选、输出 JSON 数组、置信度

def atomize(text: str) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) > _MAX_INPUT:          # v1 不分块，超长截断 + 该条 warning
        text = text[:_MAX_INPUT]
    root = vault_writer_service._root()           # 复用：未配/不存在 → ValueError
    index = vault_service.scan(root)              # 复用 3a 同一 scan
    folders = list_writable_folders(index)
    menu = build_menu(folders)
    client = llm_factory.build_client()           # 未配 provider → LLMConfigError
    raw = client.complete(system=ATOMIZE_SYSTEM,
                          user=f"【可选归类菜单】\n{menu}\n\n【待拆分原文】\n{text}",
                          temperature=0.2)         # 低方差，归类更稳
    return [asdict(a) for a in parse_atoms(raw, folders)]
```

```python
# routes/vault_atomize.py（新 router，main.py 注册）—— 与确定性 vault_writer 分文件，单一职责
class AtomizeBody(BaseModel):
    text: str

@router.post("/api/vault/atomize")
def atomize(body: AtomizeBody) -> dict:
    try:
        return {"atoms": atomize_service.atomize(body.text)}
    except LLMConfigError as e:        # 未配 provider/key
        raise HTTPException(503, str(e))
    except ValueError as e:            # vault_root 未配/不存在
        raise HTTPException(400, str(e))
    except OSError:                    # 共享盘断开/占用（scan 阶段）
        raise HTTPException(503, "拆条失败：素材库不可读（共享盘断开或文件被占用）")
```

## 5. ATOMIZE_SYSTEM prompt 要点

- 角色：把家电营销资料**忠实拆分**成可复用的原子素材，**不改写、不扩写、不编造**。
- 每条原子 = 一个独立要点；正文尽量保留原文措辞。
- 从【归类菜单】里选**建议文件夹**与**素材类型**；菜单里没有合适的就留空（让人工定）。
- 产品从 {希喂, 戴森, 小米, 追觅, 通用} 选（希喂=自家品牌）。
- 每条给 `置信度` high/med/low（评归类把握，不评正文）。
- **只返回一个 JSON 数组**，每个元素 `{正文, 建议文件夹, 素材类型, 产品, 核心关键词, 建议文件名, 置信度}`，不要数组以外任何文字/解释/markdown 围栏。

## 6. 前端（Unit C）

- **MaterialsView**：`tab` 类型加 `"atomize"`，新增 tab 按钮 + `<AtomizePanel v-else-if="tab==='atomize'">`；「浏览（建设中）」原样保留。
- **`components/materials/AtomizePanel.vue`**：粘贴 `<textarea>` →「拆条」按钮（loading）→ `m.atomizeText(text)` → 渲染 `AtomCard` 列表（按置信度排序：low 置顶 + 高亮边框）+ 顶部「全部入库（high/med）」便捷键 + 整体错误条。空/未配 provider（503）→ 友好提示。
- **`components/materials/AtomCard.vue`**：一张卡 = 一条原子的可编辑表单（折叠/展开），字段同 3a：文件夹下拉（预填 `rel_folder`，off-menu 显示「请选择」+ warning）、素材类型、产品、核心关键词、文件名、正文。各卡独立「确认入库 / 撤销」+ plan 预览（轻量 diff 或全文）。已入库显示绿勾 + 撤销。
- **DRY**：把 3a `IntakeForm` 的「folder profile → frontmatter 组装 + 构造 `NotePayload`」抽成共享 helper（`composables/useVaultPayload.ts` 或 `materials/payload.ts`），`IntakeForm` 与 `AtomCard` 共用；**不整组件复用 IntakeForm**（它是单文件夹自带 loader，不适合列表内 N 份）。
- **store（materials.ts）**：加**返回值型**动作，不碰 3a 单槽位 state（N 卡各自持有 plan/receipt）：
  ```ts
  interface AtomDraft { text; rel_folder: string|null; material_type; product; keyword; filename; confidence: "high"|"med"|"low"; warnings: string[] }
  async function atomizeText(text): Promise<AtomDraft[]>          // POST /api/vault/atomize
  async function planAtom(payload: NotePayload): Promise<NotePlan|null>   // POST /api/vault/plan，返回
  async function commitAtom(payload: NotePayload): Promise<WriteReceipt|null> // POST /api/vault/commit，返回
  async function undoAtom(receipt: WriteReceipt): Promise<void>  // POST /api/vault/undo
  ```
  3a 的 `planNote/commitNote/undoLast`（单槽位）留给手动表单不动。`commitAtom`/`commitNote` 内部可共用一个私有 POST helper（DRY）。
- **通知**：复用 `useNotifications().push(title, { tone })`，tone ∈ success/info/warn/error（**不是** `{kind,text}`）。

## 7. 安全红线（共享团队盘 `D:\家电组共享\DATA`）

- **测试绝不碰真实库**：LLM 走 mock（`_RecordingClient` + monkeypatch `build_client`，canned JSON）；vault 走 `tmp_path`。`parse_atoms`/`build_menu`/`_safe_filename` 是纯函数，喂假 JSON / 假 FolderProfile 单测。真实库测试（若有）只读 + `skipif` 门控。
- off-menu 建议**写不进库**（选择器只列真实文件夹 + `_validate` 兜底路径逃逸）。
- **v1 不自动建文件夹**。
- commit 复用 3a：不覆盖（`FileExistsError`→409）、逐条 sha 守卫撤销、索引只进「## App 新增」块不碰人工表格。
- 「全部入库」默认跳过 low。
- 首次真机使用是**真写共享盘**——先拿无关紧要素材试水，核对落盘 + App 新增块 + 撤销可用。

## 8. 测试清单

**后端**（PowerShell 双 PYTHONPATH `<worktree>;<worktree>\sidecar`，`& "D:\CSM\.venv\Scripts\python.exe" -X utf8 -m pytest`）：
- `tests/core/vault/test_atomizer.py`：`parse_atoms` 正常数组 / 围栏 / 前言抠数组 / 整体非数组→[] / off-menu→None+warning / 缺字段→空 / 置信度非法→low / text 空跳过；`build_menu` 过滤 spec_table；`_safe_filename` 空格分隔符中文。
- `sidecar/tests/test_atomize_service.py`：mock client 返回 canned JSON → 断言 atoms（含 grounding）；菜单注入 user；temperature=0.2；未配 provider → `LLMConfigError`；空输入 → `[]` 不打 LLM；`tmp_path` vault。
- `sidecar/tests/test_vault_atomize_routes.py`：200 正常；503（LLMConfigError）；400（vault_root 未配）；422（body 缺 text）。

**前端**（vitest + `npx vue-tsc -b` 强制过）：
- `materials.atomize.spec.ts`：`atomizeText`/`planAtom`/`commitAtom`/`undoAtom` 打对端点、返回值正确、错误进 `intakeError`。
- `AtomCard.spec.ts`：预填、off-menu 显 warning、确认入库走 commitAtom、撤销走 undoAtom。
- `AtomizePanel.spec.ts`：拆条渲染 N 卡、low 置顶、「全部入库」只扫 high/med。

## 9. Units 划分 & 交付

| Unit | 范围 | 文件 |
|---|---|---|
| **A** 后端核心 | atomizer 纯函数 | `csm_core/vault/atomizer.py` + `tests/core/vault/test_atomizer.py` |
| **B** sidecar | service + route + 注册 | `services/atomize_service.py`、`routes/vault_atomize.py`、`main.py`、2 个测试 |
| **C** 前端 | tab + 面板 + 卡 + store + helper | `MaterialsView.vue`、`AtomizePanel.vue`、`AtomCard.vue`、`materials.ts`、payload helper、3 个测试 |

subagent-driven：每 Unit implementer → spec 合规审 → 代码质量审 → 修；最后整体审 → **一个 PR**，期间用户审 merge。

## 10. 非目标（v1 明确不做）

- 不改写/扩写正文（变体 ②③ 归链式增强器/人工）。
- 不自动建文件夹。
- 不分块（超长截断 + warning；长文分块留后续）。
- 不拆产品参数表（spec_table 折叠出菜单，产品参数走 3a 手动）。
- 不做置信度数值阈值门禁。
- 不持久化拆条会话（无服务端 state，前端持有）。

## 11. 验收

1. 后端 / 前端全绿 + `vue-tsc` 0 + 零回归（3a 测试不破）。
2. 三轮审查（每 Unit spec+质量）+ 最终综合审查 SHIP。
3. CI 绿（预防 #144 vue-tsc-class 类失败）。
4. 真机：粘一段含 3-5 个要点的家电资料 → 拆条出卡 → 改一两条归类 → 逐条入库 + 一次「全部入库」+ 一次撤销，去 Obsidian 核对落盘/索引/可撤销。
