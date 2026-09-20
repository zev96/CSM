# CSM 示例资源

这里放随安装包一起打进去的只读示例资源（`sidecar/csm-sidecar.spec` 把整个 `examples/` 打进 exe）。**不要在 GUI 里指向 `tests/fixtures/` 下的 vault**，那个是测试用的，改坏了测试会挂。

## 目录说明

```
examples/
├── vault/营销资料库/          # 示例 Obsidian Vault（可把 vault_root 指到这里试用模板库编辑器）
│   ├── 引言模块/吸尘器/痛点共鸣/   (2 条)
│   ├── 科普模块/吸尘器/挑选攻略/   (2 条)
│   └── 产品模块/吸尘器/            (3 条：自有品牌 CEWEY + 竞品戴森/小米，带 品牌/型号 frontmatter)
└── skills/
    └── xiaohongshu-polish.md      # 示例风格 Skill（首次启动时种子到用户 Skills 目录）
```

## 各自的用途

- **`skills/`**：sidecar 首次启动建 `Skills\` 目录时，把这里的 `.md` 拷过去作为种子（`services/startup_dirs.py`）。用户之后在「模板库 → 风格 Skill」里查看 / 编辑。
- **`vault/营销资料库/`**：一个结构完整的小 Vault，用来演示「模板库」编辑器里依赖 Vault 的两类功能：
  - **属性筛选**：模板段落可按笔记 frontmatter 属性多选过滤（sidecar 启动时扫描 `vault_root` 建索引，接口 `/api/vault/dirs`、`/api/vault/attributes`）。
  - **竞品卡覆盖度 / 小节识别**：`产品模块/` 下的笔记带 `品牌` / `型号` frontmatter，可用来试 `card_coverage` / `card_sections`。

## GUI 里怎么填

打开 **设置 → 存储路径**：

| 字段 | 填什么 |
|------|--------|
| `Obsidian Vault` | `<仓库路径>\examples\vault\营销资料库` |
| `默认模板目录` | 首次启动自动建好的 `Templates\` 目录（也可指到仓库根 `templates/`） |
| `Skills 目录` | 首次启动自动建好的 `Skills\` 目录（已种子 `examples/skills`） |

然后进 **模板库** 打开任意模板，在段落编辑器里试「属性筛选」。

## 扩展：加自己的素材

按相同结构往 vault 里塞 md 文件即可（frontmatter 字段参考现有文件）。核心结构：

```
vault_root/模块名/产品名/组件类型/*.md
```

frontmatter 常用字段：`产品`、`素材类型`、`组件类型`；竞品卡需要 `品牌` 和 `型号`。
