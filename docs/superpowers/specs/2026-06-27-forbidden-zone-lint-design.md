# 禁区 lint（确定性合规扫描）设计

> 创作台 ④「其他写作优化」里的独立块。成稿里 emoji / 破折号 / 双引号 / 绝对化用语 / 引流话术 / 元话术这类**确定性可机器判定**的违规，扫出 → 标红定位 → 机械类一键清 → 判断类人工放行 → 软拦导出。与已交付的「事实核对」(Plan 3) 互补：事实核对管「编造数字/认证/产品信息」，禁区 lint 管「违规措辞/标点」。

来源：真实 skill `examples/skills/家电科普博主.md` §写作禁区（行 459–469）+ 路线图 `specs/2026-06-23-creation-studio-upgrade-roadmap-design.md` §0.1 / Phase 0（禁区 lint = P0「确定性质量门禁，快赢」，落点 `csm_core/lint/`）。

---

## 0. 立场（lint 是薄的、隔离脆弱链）

1. **确定性优先**：纯词表/正则/unicode 区间判定，零 LLM。可机器判定的才进 lint；判不清的（点名攻击竞品）不进。
2. **隔离脆弱链**：lint 不碰 `finalize_draft` / `/api/generate/{id}/export` resume / factcheck 服务端门禁那条出过 SSE 时序 bug 的链（见 `specs/2026-06-25-interactive-finalize-design.md`）。引擎放 `csm_core/lint/`，经**无状态** `POST /api/lint` 暴露，软拦完全在前端编排。
3. **人工定夺**：lint 只标红 + 给建议 + 机械类一键清；绝不替用户改判断类措辞。软拦（可放行）而非硬拦。
4. **opt-out 而非 opt-in**：默认开（用户明确要「自动跑 + 软拦」）；`config.lint.enabled=false` 可整体关，退回今天行为。

---

## 1. 范围与边界

### 1.1 六类（确定性可扫）

| key | 类别 | 默认命中物（节选） | fixable（可一键清） |
|---|---|---|---|
| `meta_speak` | 元话术词 | 广告 / 推广 / 赞助 / 软文 | 否（需改写） |
| `absolute` | 绝对化用语 | 最佳 / 最强 / 第一 / 首选 / 唯一 / 顶级 / 极致 / 100% / 绝对 / 永不 / 根治 / 零缺陷 / 永不衰减 / 100%安全 | 否（需改写） |
| `traffic` | 引流话术 | 点击下方链接 / 关注账号 / 抽奖 / 免费领 / 加微信 / 扫码 / 私信 | 否（需改写） |
| `emoji` | emoji | 😀✨🔥（unicode emoji 区间） | 是（删） |
| `dash` | 破折号 | `——` / `—`（U+2014/2015） | 是（→`，`） |
| `quote` | 双引号 | `"` `"` `"`（U+201C/201D + ASCII） | 是（删，保留内文） |

机械三类（emoji/dash/quote）= 标点/符号层面，可安全批量清；判断三类（meta_speak/absolute/traffic）= 措辞层面，删词可能破句 → 只标红定位、人工改或放行。

### 1.2 不进 lint（边界）

- **事实类**：编造认证、添加毛坯没有的产品信息 → 已由 Plan 3 事实核对覆盖，不重复管。
- **点名攻击竞品**：本域天然要跟戴森/小米/追觅做对比（CEWEY/希喂自有品牌 vs 竞品），纯确定性分不清「对比」与「攻击」→ 不进 lint，留给人工 / skill prompt。
- **只扫成稿**（finalText），不扫初稿（draftText）/ 组装预览。

---

## 2. 复用面（不重造）

| 复用项 | 来源 | 用法 |
|---|---|---|
| 审查面板范式 | `components/article/FactCheckPanel.vue` | `LintPanel.vue` 镜像：Dialog + 逐项列违规 + 逐项放行勾选 + footer 操作 |
| 导出门禁入口 | `ArticleView.vue:574 onExportClick()` | 加 lint 软拦守卫（factcheck > lint > 导出 modal） |
| 违规模型形态 | `csm_core/factcheck/model.py Violation` | `LintHit` 同构（kind→category、value→text、加 start/end/fixable） |
| 成稿可编辑 | `ArticleView` 成稿 tab `TiptapEditor` | 一键清/手改写回 `article.finalText` |
| config 深合并 | `config_service._deep_merge` + `/api/config` PATCH | 新增 `LintConfig`，部分 patch 安全（无 UI，手改 settings.json） |
| 鉴权依赖 | `RequireToken`（既有路由模式） | `/api/lint` 加同款依赖 |
| 路由注册 | `main.py` include_router 模式 | 注册 `lint_routes.router` |

---

## 3. 决策（已拍板）

- **D1 规则范围** = 六类全做（§1.1）；点名竞品不进 lint。
- **D2 行为门禁** = finalize 出成稿后**自动扫** + **软拦导出**（未处理命中需先放行或一键清才导）。
- **D3 一键清** = 只清机械三类（emoji/dash/quote）；判断三类只标红定位。
- **D4 规则存放** = 内置 `csm_core/lint/` + `settings.json` 可选覆盖（extend，不替换）；v1 无 UI 编辑器。
- **架构选型 = A（无状态端点 + 前端编排软拦）**，不选 B（折进 factcheck 服务端硬门禁）。理由：隔离脆弱链、确定性前端编排足够权威（本地单机 app）、引擎仍 testable 在 csm_core 且将来批量评分可复用。
- **D5 绝对化误报处理** = 用 curated 极限词/短语表，**不裸匹配「最」**（避开 最近/最后/最大吸力 等误报）；判断类只标红 + config 可调，容忍少量噪音（人工把关）。

---

## 4. 引擎 `csm_core/lint/`（纯函数，零 IO）

### 4.1 `model.py`

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field

Category = Literal["meta_speak", "absolute", "traffic", "emoji", "dash", "quote"]

class LintHit(BaseModel):
    category: Category
    text: str          # 命中的原文片段，如 "最佳" / "😀" / "——" / "加微信"
    start: int         # 字符偏移（高亮/排序/去重 key）
    end: int           # 含尾（start + len(text)）
    sentence: str      # 所在句子（面板定位用，截断 ≤80 字）
    fixable: bool      # True=机械三类，可一键清
    suggestion: str    # 处理建议（如 "删除 emoji" / "改为非绝对化表述，如「行业领先」"）

class LintReport(BaseModel):
    hits: list[LintHit] = Field(default_factory=list)
    fixed_text: str    # 机械三类全清后的文本（一键清用）；判断三类不动
```

### 4.2 `rules.py`

默认词表（const，可被 config extend）：

```python
DEFAULT_META = ["广告", "推广", "赞助", "软文"]

# 绝对化 = 广告法极限词 + 承诺词。curated 短语（不含裸「最」/温度词「最近/最后」），
# 也不默认含测量歧义前缀（最大/最高/最小/最低）——嫌漏可经 config.extra_absolute 加。
DEFAULT_ABSOLUTE = [
    "最佳", "最好", "最强", "最优", "最先进", "最值得", "最顶级", "最专业",
    "第一", "首个", "首选", "唯一", "独家", "顶级", "极致", "国家级", "世界级",
    "100%", "百分百", "绝对", "永久", "永不", "万能", "根治", "彻底根除", "包治",
    "史上最", "全网最", "全国最", "零缺陷", "永不衰减", "100%安全",
]

DEFAULT_TRAFFIC = [
    "点击下方链接", "点击链接", "戳链接", "链接在评论", "关注账号", "关注我",
    "抽奖", "免费领", "免费送", "加微信", "加V", "扫码", "扫描二维码",
    "私信", "私我", "主页领", "简介领",
]

# 机械类 —— 正则/区间
EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\U00002300-\U000023FF\U0000FE00-\U0000FE0F"
    "\U0000200D\U000020E3]+"            # emoji + 区域旗 + ZWJ/变体选择符/keycap，连续算一处
)
DASH_PATTERN = re.compile(r"[—―]+")   # —（U+2014）/ ―（U+2015），连续算一处
QUOTE_CHARS = "“”""              # “ ” + ASCII "；不含 「」/单引号
```

`Rules` = frozen dataclass，持各类有效词表 + 编译好的正则；`disabled_categories` 里的类不进扫描：

```python
@dataclass(frozen=True)
class Rules:
    meta: tuple[str, ...]
    absolute: tuple[str, ...]
    traffic: tuple[str, ...]
    check_emoji: bool
    check_dash: bool
    check_quote: bool

def build_rules(config: LintConfig | None) -> Rules:
    """默认词表 + config.extra_* 扩展（去重保序）；disabled_categories 关掉对应类。"""
```

### 4.3 `scanner.py`

```python
def scan(text: str, rules: Rules) -> list[LintHit]:
    """逐类扫描 → 收集 LintHit。
    - 词表类（meta/absolute/traffic）：找出每个词的所有出现位置（非重叠、最长优先）。
    - emoji/dash：正则 finditer，连续算一处。
    - quote：逐字符命中 QUOTE_CHARS。
    去重：同 (start, text) 只留一条；同位置多类命中按 meta>absolute>traffic>其余 取一。
    句子定位：在 [。！？!?\n] 边界间取包含 start 的子串，截断 ≤80。
    返回按 start 升序。"""

def autofix(text: str, rules: Rules) -> str:
    """只清机械三类（按 rules 开关）：
    - emoji → 删（替空串）
    - dash  → 替「，」，随后合并「，，」→「，」、「。，」→「。」
    - quote → 删（保留内文）
    判断三类不动。幂等：autofix(autofix(t)) == autofix(t)。
    从尾向头按区间替换，保证偏移不串位。"""

def build_report(text: str, rules: Rules) -> LintReport:
    """scan + autofix 组装成 LintReport（service 调它）。"""
```

误报控制（D5）落在 `DEFAULT_ABSOLUTE`：用 curated 短语，默认不含裸「最」、不含温度词（最近/最后/最终/最初/最多/最少）、不含测量歧义前缀（最大/最高/最小/最低）。这些可由用户经 `config.extra_absolute` 自行加严。

---

## 5. 后端（sidecar）

### 5.1 `services/lint_service.py`

```python
def scan_text(text: str) -> dict:
    """读 config.lint → 关则直接空报告；否则 build_rules → build_report → model_dump。
    返回 {"hits": [...], "fixed_text": "..."}。纯计算、不写盘、不碰 vault。"""
    cfg = config_service.load()             # 既有读取入口（返回 AppConfig）
    lint_cfg = cfg.lint
    if not lint_cfg.enabled:
        return {"hits": [], "fixed_text": text}
    rules = build_rules(lint_cfg)
    report = build_report(text or "", rules)
    return report.model_dump()
```

### 5.2 `routes/lint.py`

```python
router = APIRouter(tags=["lint"], dependencies=[RequireToken])

class LintBody(BaseModel):
    text: str        # 缺→422；空串→service 返回空报告

@router.post("/api/lint")
def lint(body: LintBody) -> dict[str, Any]:
    return lint_service.scan_text(body.text)
```

无 LLM、无 IO → 无 503/LLMConfigError 分支；唯一异常面是编程错（500）。main.py：`from .routes import lint as lint_routes` + `app.include_router(lint_routes.router)`。

### 5.3 `config` 新增 `LintConfig`（在 `csm_core/config.py`）

`LintConfig` 与 `AppConfig`/`BrandMemoryConfig`/pricing 配置同处 `csm_core/config.py`（引擎 `csm_core/lint/rules.py` 从此 import，依赖方向与 brand_memory 一致）：

```python
class LintConfig(BaseModel):
    enabled: bool = True
    extra_meta: list[str] = Field(default_factory=list)
    extra_absolute: list[str] = Field(default_factory=list)
    extra_traffic: list[str] = Field(default_factory=list)
    disabled_categories: list[str] = Field(default_factory=list)  # 如 ["quote"] 关双引号检查
```

挂进 `AppConfig.lint: LintConfig = LintConfig()`。`/api/config` GET 已返回全量、PATCH 深合并（`config_service._deep_merge`）→ 手改 settings.json 的 `lint` 子键安全；旧 settings.json 无该键时 `model_validate` 补默认（默认全开、零额外词 = 纯内置行为）。无 UI 卡。

---

## 6. 数据流（软拦）

```
finalize done（final_text 非空）
  → article.runLint(finalText)            自动扫（POST /api/lint）
  → lintBlocking 变 true
  → ArticleView watch → 自动弹 LintPanel
       ├─「一键清机械类」→ finalText = fixed_text → 重扫（机械项消失）
       ├─ 判断项逐条「本次放行」 或 回成稿 tab 手改 → 重扫
       └─ 全部清/放行 → lintBlocking=false →「确认并导出」→ 开导出 modal
onExportClick 守卫顺序：
  if factcheck.blocked → 事实核对面板; return
  if lintBlocking      → 弹 LintPanel;   return
  else                 → 开导出 modal
```

- factcheck（服务端硬门禁）与 lint（前端软拦）是**两道独立门**，在导出口汇合。常见路径（inject 开、事实接地 → factcheck 不拦）只过 lint 一道。
- **双失败漏洞封堵**：factcheck 被拦时走 `FactCheckPanel` 自己的导出口（`/api/generate/{id}/export`），绕过 `onExportClick` → 故 `FactCheckPanel.recheckExport()` 在调 `resolveFactcheck` **之前**也加一句 `if (article.lintBlocking) { emit('lint'); return; }`，由 ArticleView 转弹 LintPanel。两口都守 → 任何脏文本都过不去。
- **失败开放**：`/api/lint` 网络/500 失败 → `runLint` catch → `lint=null`（lintBlocking=false）→ 不阻塞导出（lint 基建故障不该卡用户）。

---

## 7. 前端

### 7.1 `stores/article.ts`

```ts
export type LintCategory = "meta_speak"|"absolute"|"traffic"|"emoji"|"dash"|"quote";
export interface LintHit {
  category: LintCategory; text: string; start: number; end: number;
  sentence: string; fixable: boolean; suggestion: string;
}
// state（直接存 API 响应，snake_case 零映射，沿用 3b AtomDraft 同形约定）
lint: { hits: LintHit[]; fixed_text: string } | null;  // null = 未扫/失败
lintReleased: string[];                                 // 已放行 hit 的 key
// key
const lintKey = (h: LintHit) => `${h.category}:${h.start}:${h.text}`;
// getter
lintBlocking: (s) => !!s.lint && s.lint.hits.some(h => !s.lintReleased.includes(lintKey(h)));
lintUnresolved: (s) => s.lint ? s.lint.hits.filter(h => !s.lintReleased.includes(lintKey(h))).length : 0;
// actions
async runLint(text): POST /api/lint {text} → set lint, lintReleased=[]; catch → lint=null
autofixLint(): if lint → finalText=lint.fixed_text; await runLint(finalText)
toggleLintRelease(h): add/remove lintKey(h) in lintReleased
```

自动 runLint 的注入点（finalText 由完成的 LLM pass 赋值处）：`_subscribe.done`（finalize 出 final_text 时）、`rerunPass.done`（重跑改 final_text 时）。`submit`（draft_only，final_text 空）不触发。`submit`/`finalize` 的 reset 块清 `lint=null, lintReleased=[]`。

### 7.2 `components/article/LintPanel.vue`

镜像 FactCheckPanel：`Dialog`（v-model:open），按 category 分组列 hits（类中文 pill + 命中片段高亮 + 所在句 + 建议）；判断类每条带「本次放行」勾选；机械类不必逐条勾，靠顶部「一键清机械类」批量（清完即消失）。footer：`一键清机械类` / `重新检查`（runLint(finalText)）/ `确认并导出`（`!lintBlocking` 才 enabled，点击 `emit('proceed')` + 关面板）。data-lint-* 测试钩子。

### 7.3 `views/ArticleView.vue`

```ts
const showLint = ref(false);
watch(() => article.lintBlocking, (b, prev) => { if (b && !prev) showLint = true; });
function onExportClick() {
  if (article.factcheck?.blocked) { showFactcheck.value = true; return; }
  if (article.lintBlocking)       { showLint.value = true; return; }
  showExportModal.value = true;
}
// <LintPanel v-model:open="showLint" @proceed="showExportModal = true" />
```

质检卡（`checkItems`）加第 7 项「禁区」：value=`lintUnresolved 处` 或「无」，pass=`!lintBlocking`，tone=pass?ok:warn → 常驻状态，关了面板也能看见。

---

## 8. 安全红线

- lint 端点**无状态、不写盘、不碰 vault**；与共享团队盘 `D:\家电组共享\DATA` 零交集。
- 引擎纯函数，测试不依赖磁盘/网络/LLM。
- 一键清是 best-effort（——→，可能偶有不顺）→ 面板重扫给用户复检，用户最终在成稿 tab 定稿。
- 默认开但可 `config.lint.enabled=false` 整体关，退回今天导出行为（零回归逃生口）。

---

## 9. 测试

**A 引擎（`tests/core/lint/`）**
- 六类各：命中（含位置/句子定位正确）、不命中（干净文本 0 hit）。
- 绝对化不误报：「最近更新」「最后一步」「最初设计」→ 0 hit；「最佳选择」「业内第一」→ 命中。
- autofix：emoji 删净 / `——`→`，` / 双引号删保留内文；幂等（二次 autofix 不变）；判断类不被 autofix 动。
- 偏移正确：多处命中后 start/end 对得上原文切片。
- config：`extra_absolute` 加词生效；`disabled_categories=["quote"]` 后双引号 0 hit；`enabled=False`（service 层测）空报告。
- 空文本 / 纯标点 → 空报告。

**B 端点（`tests/sidecar/`）**
- `POST /api/lint` 200，形状 `{hits, fixed_text}`；命中文本 hits 非空。
- 缺 `text` → 422；空 `text` → 200 空报告。
- config 覆盖经端点生效（patch lint.extra_traffic 后命中新词）。
- 鉴权：无 token → 401/403（RequireToken）。

**C 前端（`frontend`）**
- `runLint` set lint + 清 released；`autofixLint` 置 finalText=fixedText 并重扫；`lintBlocking`/`lintUnresolved` 逻辑（放行后递减、全放行→false）。
- `toggleLintRelease` 增删 key。
- `onExportClick` 守卫顺序：factcheck.blocked 优先 > lintBlocking > 导出 modal（三态各一断言）。
- LintPanel：渲染 hits、一键清调 autofixLint、确认并导出在 `!lintBlocking` 时才可点并 emit proceed。
- **`vue-tsc -b` 必过**：LintHit fixture 的 `category` 字面量须满足 union（沿用 CSM#144 教训，fixture 数组显式标 `LintHit[]`）。

**真实库无关预存失败**：`tests/core`+`tests/scripts` 5 个预存失败（见 [[project_csm_creation_studio_upgrade]]）与本工作无关，别排查。

---

## 10. Units 拆分

- **Unit A** = `csm_core/lint/`（model + rules + scanner，含 build_rules/scan/autofix/build_report）。纯函数 TDD。
- **Unit B** = sidecar `services/lint_service.py` + `routes/lint.py` + `config.LintConfig` + main.py 注册。
- **Unit C** = 前端 `article.ts`（LintHit/state/getter/actions）+ `LintPanel.vue` + `ArticleView.vue` 接线（onExportClick 守卫 + watch 自动弹 + 质检卡第 7 项）+ `FactCheckPanel.vue` 加 lint 守卫一句。

子代理驱动，逐 Unit 两段审查（spec 合规 + 代码质量）+ 最终整体审查，沿用历轮节奏。

---

## 11. 非目标（v1）

- 不判「点名攻击竞品」（确定性分不清对比 vs 攻击）。
- 不做 UI 词表编辑器（只 config 手改）。
- 不拦初稿/组装预览（只成稿）。
- 不折进 factcheck 服务端门禁（A 方案，隔离脆弱链）。
- 判断三类不自动改写（只标红 + 建议 + 放行）。
- 不做服务端权威硬拦（前端软拦足够，本地单机）。
- emoji 不区分「装饰 emoji」与「合理符号」——一律命中、一律可一键清（用户放行个别可手改）。

---

## 12. 验收

1. 成稿含 emoji/——/双引号 → 自动弹面板 →「一键清机械类」后三类清零、成稿可读。
2. 成稿含「最佳」「加微信」「软文」→ 判断类标红 + 建议；逐条放行或手改后可导出。
3. 「最近」「最后一步」→ 不误报。
4. 未处理命中时点导出 → 被软拦弹面板；清/放行后才进导出 modal。
5. factcheck + lint 双命中 → 两道门都要过（事实核对面板导出口也被 lint 守住）。
6. `config.lint.enabled=false` → 不扫不拦，退回今天行为。

相关：[[project_csm_creation_studio_upgrade]]、[[feedback_csm_color_token_sweep_full_scan]]（颜色 token 那条不相关，仅提醒前端暗色可读）。
