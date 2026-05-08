# Skills 管理页 + 模板基础设置精简 设计文档

**日期**：2026-04-23
**范围**：把模板基础设置里的 LLM 相关字段（系统提示词 / SEO 默认参数 / 版本）全部清除，相关内容迁移到 Skill (.md) 文件里；在导航栏新增 Skills 管理页，支持列表 / 新建 / 编辑 / 删除 / 重命名。同时修复新建模板弹窗遮挡问题，并把模板 ID 改为自动生成。

---

## 目标

1. **Skill 成为 LLM 约束的唯一载体**：一个 .md 文件完整描述 system prompt（风格、结构、SEO、字数、语气、关键词）。模板不再携带 system prompt 和 SEO 默认参数。
2. **模板职责收窄**：模板只管"结构"（模块 / 段落 / 采样规则），不管"风格"。
3. **Skill 成为一等公民**：有专属管理页，用户可直接在 GUI 里编辑，不用下 shell 改文件。
4. **新建模板流畅化**：弹窗不遮挡内容；ID 自动生成，用户只填名称和产品类别。

## 非目标

- 不做 Skill 的版本控制 / 历史 / diff。
- 不做 Skill 的 markdown 渲染预览（纯文本编辑器足够）。
- 不重新设计 Skill 的格式（仍是自由 markdown，不加前言元数据）。
- 不做 Skill 分类 / 标签 / 搜索（列表 < 50 个时没必要）。

---

## 架构

### 字段迁移表

| 模板字段 | 现状 | 迁移后 |
|---|---|---|
| `version` (版本) | 无人读 | **删除** |
| `system_prompt_default` | `pipeline.py:73` → LLM system prompt | **删除**。其内容在一次性迁移中拼入 Skill `.md` |
| `seo_defaults.target_word_count` | `_format_seo_block()` → system prompt | **删除**。迁移时写入 Skill 正文 |
| `seo_defaults.keyword_density` | 同上 | 同上 |
| `seo_defaults.tone` | 同上 | 同上 |
| `seo_defaults.force_h2` | 同上 | 同上 |
| `seo_defaults.long_tail_keywords` | 同上 | 同上（迁移时写成逗号分隔字符串） |

### 迁移逻辑（一次性脚本）

扫描 `templates/*.json`。对每个模板：

1. 渲染出当前的 system-prompt-等价文本：
   ```
   {system_prompt_default}

   ## SEO 约束
   - 目标字数：1500-2000
   - 关键词密度：5%-8%
   - 语气风格：小红书笔记体
   - 强制 H2：是
   - 长尾关键词：家用吸尘器推荐, 宠物吸尘器对比
   ```
2. 把这段文本作为新 Skill `{template-id}-migrated.md` 写入 `skill_dir`。
3. 从模板 JSON 里删掉 `version` / `system_prompt_default` / `seo_defaults` 字段。
4. 打 log：`migrated template {id} -> skill {path}`。

迁移脚本位置：`scripts/migrate_template_to_skill.py`。幂等（如果目标 skill 已存在就 skip）。用户运行一次即可。

### pipeline 变更

`csm_core/llm/prompts.py:build_prompt()` 签名：
- **删除**：`template_system_prompt: str` 参数
- **删除**：`seo: SEODefaults` 参数 和 `_format_seo_block()` 函数
- **保留**：`user_skill_prompt: str`（这就是全部的 system prompt 了）

`csm_core/pipeline.py:73-75` 和 `csm_core/batch/runner.py:74-76` 相应简化。

### Schema 变更

`csm_core/template/schema.py`：
- 删除 `SEODefaults` 模型
- 删除 `Template.version / system_prompt_default / seo_defaults` 字段
- 保留：`id / name / product / blocks`

加载旧模板时，Pydantic 默认会对未知字段报错。解决：在 `Template` 上加 `model_config = ConfigDict(extra="ignore")`，让旧 JSON 里残留的三字段被静默忽略（前向兼容未迁移的模板）。迁移脚本跑完后，新保存的模板自然不再写这些字段。

---

## 新建模板弹窗修复

**问题**：当前 `_NewTemplateDialog(self)` 的 parent 是左侧 `TemplateListPanel`，qfluentwidgets 的 `MessageBoxBase` 以 parent 为基准居中，所以弹窗落在左侧面板中央、遮挡右侧编辑器。

**修复**：parent 改成主窗口 (`self.window()`)，弹窗居中在整个应用。

**字段简化**：
- **删除**：模板 ID 输入框（自动生成）
- **保留**：模板名称、产品类别

**ID 自动生成**：`template-{int(time.time())}`（选项 A，纯时间戳）。文件名 `template-1732880000.json`。冲突概率 ≈ 0（同一秒内双击），万一冲突仍走现有的 `-2/-3` 后缀逻辑。

---

## Skills 管理页设计

### 导航入口
`main_window.py` 里 `addSubInterface(self.skills_page, FluentIcon.DICTIONARY, "Skills")`。图标用 `DICTIONARY` 或 `EDIT`（待定，取 qfluentwidgets 里语义最贴的）。

### 页面布局
左右两栏（沿用模板页的布局语言）：

```
┌─────────────────┬────────────────────────────────┐
│ Skills 目录       │ 编辑区                            │
│ {skill_dir}      │ 名称: [xiaohongshu-polish     ]  │
│ [浏览]           │                                │
│                 │ ┌──────────────────────────┐ │
│ ─── 列表 ───      │ │ # 小红书风格润色 Skill     │ │
│ • xiaohongshu-... │ │                        │ │
│ • tech-review     │ │ 你是一位专注于...          │ │
│ • (selected)      │ │ (纯文本 markdown 编辑)     │ │
│                  │ │                        │ │
│ [+ 新建]          │ └──────────────────────────┘ │
│ [删除]            │                                │
│                 │                      [保存]     │
└─────────────────┴────────────────────────────────┘
```

左栏：
- `skill_dir` 路径（带"浏览"按钮改目录，同模板页的目录选择器）
- Skill 文件列表（按 stem 显示，`.md` 后缀隐藏）
- `+ 新建` 按钮 → 弹窗问 Skill 名称 → 用骨架创建新文件
- `删除` 按钮 → 二次确认 → 删文件（走 `send2trash` 到回收站，不是硬删）

右栏：
- 名称输入框（改名 = 重命名文件）
- `QPlainTextEdit`（纯文本，无 markdown 渲染，宽字体 / monospace 可读）
- `保存` 按钮（未保存时高亮 / 文件头显示 `*`）

### 新建 Skill 骨架
```markdown
# 新 Skill

你是一位专注于 xxx 品类的内容编辑。收到毛坯文后，按下面的规则进行**润色改写**。

## 风格约束

- 开头钩子：
- 段落密度：
- 口语化：
- 数字保留：必须逐字保留所有参数、价格、型号。
- 品牌/型号：必须原样保留。

## 结构约束

- 保留毛坯文的所有 H2 段落及其顺序。
- 不得新增虚构内容。

## 禁止项

- 禁止引流话术（"点击关注"、"免费领"等）。
- 禁止绝对化承诺词（"最"、"第一"、"100%"、"根治"）。

## 输出

直接输出润色后的完整正文 Markdown，不要加任何前言或代码块包裹。
```

### 文件 I/O 策略
- 列表 = `Path(skill_dir).glob("*.md")`，名称排序
- 编辑器里改名 = `os.rename`（冲突时在对话框里报错，不覆盖）
- 未保存 dirty 态：切换到另一 skill 前弹确认（丢弃 / 保存 / 取消）
- 保存走原子写（tmp + replace），和 config / template 保存一致
- 删除用 `send2trash`（已经是依赖了就用，没有就 `os.remove`，先查 requirements）

### 失败模式
- `skill_dir` 不存在：页面显示"请先在设置里选择 Skill 目录"空态
- 目录为空：显示"点击左下方 + 新建 Skill"空态
- 文件读取失败（权限 / 编码）：Toast 提示，不崩

---

## 测试

### 单元测试
- `tests/gui/test_skills_page.py`：pytest-qt 驱动，覆盖：
  - 列表加载
  - 新建 skill 生成骨架
  - 保存写回磁盘
  - 删除走二次确认 + 回收站
  - 改名 = rename
- `tests/core/template/test_schema.py`：验证 `extra="ignore"` 吞掉老字段
- `tests/scripts/test_migrate.py`：给一个含 system_prompt + seo 的模板 JSON，跑迁移脚本，断言输出 skill 内容 + 模板字段清除 + 幂等

### 回归测试
- `tests/core/test_pipeline.py`：确认 `build_prompt()` 不再接收 `template_system_prompt / seo`
- `tests/gui/test_template_editor.py`：断言编辑器不再显示"版本 / 系统提示词 / SEO 默认参数"三个 group
- `tests/gui/test_template_list_panel.py`：新建弹窗只有 2 个输入框，ID 自动生成不冲突

### 手工验证清单（给用户）
1. 运行迁移脚本，检查 `skill_dir` 多了 `.migrated.md` 文件
2. 打开模板编辑器 → 基础设置只剩"名称 / 产品" 2 个字段
3. 导航栏点 "Skills" → 看到列表 → 新建一个 → 填内容 → 保存 → 重启 app 还能看到
4. 新建模板弹窗 → 只有名称 + 产品，弹窗居中在整个应用而不是左侧
5. 跑一次完整生成（草稿 + 润色）：输出应与迁移前一致（因为 skill 内容 = 旧 system_prompt + 旧 SEO）

---

## 风险 & 回滚

**风险 1**：迁移后 skill 目录未配置，用户生成时没 skill 可选 → LLM 没有 system prompt → 输出质量下降。

缓解：迁移脚本跑完后在 log 里打印一条"请在设置里确认 skill_dir 并选默认 skill"。文档里说明。

**风险 2**：`extra="ignore"` 静默吞字段，用户改错 schema 时不会报错。

缓解：接受此风险。前向兼容的价值（旧 JSON 仍能加载）> 严格校验。

**风险 3**：Skills 页面的 dirty 态管理有 bug → 用户丢失编辑。

缓解：切换 / 关闭前强制弹确认。保存走原子写。

**回滚**：git revert 本次 PR。迁移脚本创建的 .md 文件保留（用户可继续用），老模板 JSON 里的字段保留（因为迁移脚本删了 —— 这是单向的，回滚前需要手工从 .md 拷回 JSON）。**迁移脚本必须先备份原 JSON**（写 `.bak`）。

---

## 开放问题

### 模板记住默认 Skill（已确认 b）

模板 schema 新增 `default_skill_id: str | None = None`。迁移脚本把它设成新建的 `{template-id}-migrated`（skill 的 stem，不带 .md）。

草稿页 skill 下拉框在切换模板时读取这个字段并预填；用户仍可手动换选。

模板编辑器的"基础设置"tab 新增一行"默认 Skill" 下拉（从 `skill_dir` 扫，加空选项）。

设计决策已由用户确认：
- 方案 B（先迁移再删）
- ID 方案 A（时间戳）
- Skill 编辑用纯文本编辑器 + 骨架 + 删除二次确认
