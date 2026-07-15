# 素材库产品线通用化设计(2026-07-14)

## 背景与问题

用户 vault(`D:\家电组共享\DATA`)已重组为多产品线布局:营销资料库每个模块下分
`吸尘器 / 空气净化器` 两条产品线子树,净化器已录入 29 篇产品参数笔记(DARZ/UORRIS/
亚都/树新风 等品牌,frontmatter 完整)。但素材库页面仍假设单一吸尘器产品线,暴露 5 个根因:

1. **净化器参数录了却显示 0/32** — `identity.BRAND_ALIASES` 是写死的吸尘器品牌表,
   同时充当"品牌白名单"。`build_brand_registry` 靠 frontmatter 兜底能列出型号,但
   `resolver.resolve_memory` 的产品参数匹配**只认文件名解析、不看 frontmatter**
   (`parse_brand_model(note.id) == (brand, model)`),未知品牌解析落空 → specs 恒空。
   米家/美的/海尔的净化器因品牌撞表反而能解析,行为不一致。
2. **前端参数分组写死吸尘器本体** — `modelSpecs.ts` 的 `PARAM_GROUPS`(6 组 32 字段)
   与摘要卡 `STATS`(吸力/真空度/噪音/重量)全是吸尘器字段。净化器字段只能挤「其他」
   兜底组,摘要卡恒「—」。而笔记本身自带干净 H2 分组(吸尘器 7 节、净化器 5 节),
   被 `parse_spec_table` 拍平丢弃。
3. **主推/竞品全局单值** — `own_brands=["CEWEY"]`,净化器线自有品牌 DARZ 被标「竞品」。
4. **型号列表无产品线维度** — 62 个型号两条线混排;`category` 恒为
   `cfg.user_product or "吸尘器"` 的全局假设。
5. **录入素材树两个坑** — `list_writable_folders` 只列"直接含 ≥1 已解析笔记的文件夹":
   (a) 中间层(吸尘器/空气净化器)不渲染 → 两个「产品参数」同名并排无法区分;
   (b) 空文件夹完全不出现 → 净化器空骨架(引言/总结/标题/用户人群等)无法录入
   第一篇笔记,鸡生蛋死锁。

## 用户拍板的决策(2026-07-14)

- 总方向:**产品线通用化**(非最小修补)。
- 参数分组:**全部按笔记真实 H2 小节**,吸尘器也放弃 2026-07 初拍板的设计稿 6 组
  映射(该决策就此作废),单一代码路径,vault 即真相源。
- DARZ **加入自有品牌**:`own_brands=["CEWEY","DARZ"]`,生成链对 DARZ 按自有品牌待遇。
- 空文件夹表单模板**借兄弟产品线**。

## 设计

### ① 品牌/型号识别通用化(csm_core/brand_memory + vault)

- 新增共享函数 `note_identity(note, aliases) → (canonical品牌, 型号全名) | None`,
  判定链与 registry 现行为完全一致:**frontmatter `品牌`/`型号` 优先 → 文件名
  `parse_brand_model` / `stem.split("-")[0]` 兜底**;两者都缺 → None(与 registry
  的 skip 行为一致)。
- `build_brand_registry` 与 `resolver.resolve_memory` 的产品参数匹配都改用它,
  两处永不再分歧。
- `BRAND_ALIASES` 回归纯别名折叠职责(米家→小米、希喂→CEWEY),不再是白名单;
  未知品牌(DARZ 等)靠 frontmatter 直接命中,无须扩表。
- **resolver 对外签名不变**(避免波及生成链 generate/fact/batch 调用点):内部
  spec 匹配同时接受两种型号形式 —— `note_identity` 的型号全名 == 传入 model,
  或剥掉品牌别名前缀后 == 传入 model(现调用方传剥品牌形式,如 DS18)。
- 竞品推荐内容 `_model_in_stem` 匹配行为不变:未知品牌回退全名匹配文件名,
  与今日行为等价、不劣化;别名表可随时间按需扩充改善此路径。

### ② 参数分组数据驱动(specs → API → 前端)

- `SpecValue`(pydantic)加 `section: str = ""` 字段;`parse_spec_table` 记录
  每字段所属 H2 小节名,不再丢弃。specs 仍是扁平有序 dict(插入序 = 笔记顺序,
  Python/JSON/JS 全链路保序),消费方(白名单/事实/注入)零影响。
- 前端 `buildSpecGroups` 重写:按 `section` 分组、保持笔记原始顺序;删除
  `PARAM_GROUPS` 硬编码与 normKey 标签映射(不再需要设计稿标签清洗)。分组
  chips、scroll-spy、进度条已是 groups 数据驱动,自动适配任意小节数。
- 进度语义:分母 = 该笔记全部真实字段数,分子 = 非占位字段数。
- 无参数笔记的型号:详情区显示「暂无产品参数笔记」空态(coverage.has_specs
  已有此信号),不再渲染误导性 0/32 骨架。
- 摘要卡 5 项:已知产品线用精选表 —— 吸尘器沿用现有 5 项(价格/吸力/真空度/
  最低噪音/整机重量);空气净化器 = 价格/颗粒物CADR/甲醛CADR/最低档噪音/适用面积。
  未知产品线兜底"价格 + 前 4 个短数值字段"(raw ≤ 12 字符、numbers 非空、
  排除字段名含「链接」)。取值显示优先 raw 原文(避免 CCM「P4」被抽成「4」、
  区间值被截断)。这是唯一保留的每线小配置,仅影响摘要卡观感,可缺省降级。

### ③ 型号列表产品线维度(registry → service → 前端)

- registry 构建时从笔记路径提取产品线:`产品参数` 目录的上一段
  (`产品模块/<产品线>/产品参数`);若上一段就是 `产品模块`(旧扁平布局)或
  路径不含该结构,兜底 frontmatter `产品` 字段,再兜底 `"未分类"`。
  `BrandRegistry` 记录 `line_of(model)`。
- `list_models` 每行加 `product_line`;`get_model_detail` 的 `category` 改用
  真实产品线(替掉 `cfg.user_product or "吸尘器"`)。category 在 memory 中仅为
  展示元数据(fact_service 已注明不参与 specs 解析),生成链传 template.product
  的路径不动。
- 品牌型号页左栏顶部加产品线下拉(全部/各产品线,含计数;复用 Select 组件并传
  minWidth 防窄栏撑爆——见既有坑记录),筛选联动列表分组与顶栏
  「共 N 个型号 · 主推 X · 竞品 Y」计数。

### ④ DARZ 加入自有品牌(配置)

- 用户 `%LOCALAPPDATA%\CSM-Data\settings.json` 的 `brand_memory.own_brands`
  改为 `["CEWEY", "DARZ"]`(代码默认值不动)。
- CEWEY 只有吸尘器型号、DARZ 只有净化器型号 → 各线主推自然正确;「全部」视图
  主推 2。生成链、事实白名单对 DARZ 文章按自有品牌待遇(用户已确认语义:公司
  吸尘器卖 CEWEY、净化器卖 DARZ)。

### ⑤ 录入素材树重做(folder_profile + IntakeForm)

- 后端改为**走文件系统枚举 vault 根下全部非隐藏目录**(排除任意层级点开头目录:
  .obsidian/.smart-env/.claude 等),每个目录一行:
  - 有直接笔记 → 照旧 profile(字段/默认值/形态/计数);
  - 空目录 → **借兄弟模板**:候选 = "同叶名、同深度、路径恰差一段"的已 profile
    目录,取样本数最多者;借来 frontmatter_keys / body_shape / defaults,其中
    `产品` 默认值替换为所差的那段(即产品线名)。找不到兄弟 → 通用空白模板
    (产品/素材类型/核心关键词 三件套 + variants 正文)。
  - `FolderProfile` 加 `template_from: str | None`,借用时 UI 提示
    「模板借自 <目录>」;空目录 `sample_count=0`。
- 前端树:中间层与空目录正常渲染(深度缩进已有),两个「产品参数」从此有
  产品线父级可辨;空目录计数显示 0 而非隐藏。
- 提交链路不动:`_validate` 已要求目标目录真实存在,空目录天然满足。
- AI 拆条 AtomCard 的目标文件夹选择器共用 `writableFolders`,自动受益,零改动。

## 不动的部分

生成链注入格式(render_brand_facts)、事实白名单逻辑、使用反馈 tab、浏览 tab、
resolve_memory 对外签名、代码内 own_brands 默认值。

## 测试与回归防线

- mini_vault 夹具加一条空气净化器产品线:未知品牌 + 完整 frontmatter 的产品参数
  笔记、DARZ推荐内容 子树、空骨架目录(覆盖①③⑤)。
- 单测:note_identity 判定链(frontmatter 优先/文件名兜底/双缺 None)、resolver
  未知品牌命中 + 两种型号形式、specs section 保留与顺序、产品线提取(新层级/
  旧扁平兜底)、空目录借模板(命中/无兄弟兜底/产品默认值替换)、隐藏目录排除。
- 前端:modelSpecs.spec.ts 按 section 分组重写;摘要卡精选/兜底两路;树渲染含
  空目录;既有 resolver/inject/whitelist/generate 测试全量跑,保证生成链零回归。
- sidecar 路由测试更新(注意:sidecar/tests 不在默认 pytest 收集里,需显式跑)。

## 验收

1. 品牌型号页:DARZ·D9 参数按笔记 5 节正确显示且非空;DARZ 显示主推;左栏可按
   产品线筛选;吸尘器型号按 7 节真实小节显示。
2. 录入页:树含 吸尘器/空气净化器 中间层;净化器空骨架可选中并借到模板;录入
   一篇后计数 +1。
3. 全量测试绿(tests/ + sidecar/tests/ + 前端 vitest)。
