# CSM · Content SEO Maker

本地 PyQt6 桌面应用：基于 Obsidian Vault 的 SEO 文章快速生成工具。

## 桌面行为

- 关闭按钮（×）默认最小化到 Windows 系统托盘，应用在后台保留运行；可在「设置 → 行为」改为直接退出。
- 托盘右键菜单提供「显示主界面 / 新建文章 / 新建模板 / 新建 Skill / 设置 / 退出 CSM」六项快捷操作。
- 单实例锁：再次双击桌面快捷方式不会启动新进程，而是把已最小化的主窗复原到前台，避免重复实例对 `settings.json` / `recent_docs.json` 的写入冲突。

## 内容查重（可选）

- 创作区右侧润色按钮下方会显示两个指标：
  - **历史重复率** — 当前文章与你指定的"历史文章库目录"的字面重叠
  - **素材引用率** — 润色后的成文与 Obsidian vault 素材的字面重叠（衡量 AI 润色是否消化了原文）
- 在「设置 → 历史查重」开启后启用，需要先点「重建索引」让应用扫描语料；
- 算法：13-字滑窗 shingling + MinHash/LSH 候选检索（Jaccard 阈值 0.3）+ 精算下钻段落定位；
- 索引懒加载：未启用查重时不消耗内存；启用后索引序列化到 `<config_dir>/dedup_index/`，重启后无需重建；
- 点击 ⓘ 详情可查看 top 3 相似来源 + 命中段落，双击列表项用系统默认应用打开来源文件。

See `docs/superpowers/specs/` for design and `docs/superpowers/plans/` for implementation plans.
