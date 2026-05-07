# CSM · Content SEO Maker

本地 PyQt6 桌面应用：基于 Obsidian Vault 的 SEO 文章快速生成工具。

## 桌面行为

- 关闭按钮（×）默认最小化到 Windows 系统托盘，应用在后台保留运行；可在「设置 → 行为」改为直接退出。
- 托盘右键菜单提供「显示主界面 / 新建文章 / 新建模板 / 新建 Skill / 设置 / 退出 CSM」六项快捷操作。
- 单实例锁：再次双击桌面快捷方式不会启动新进程，而是把已最小化的主窗复原到前台，避免重复实例对 `settings.json` / `recent_docs.json` 的写入冲突。

See `docs/superpowers/specs/` for design and `docs/superpowers/plans/` for implementation plans.
