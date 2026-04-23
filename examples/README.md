# CSM 示例资源

这里给你一套可以直接在 GUI 里跑通的示例。**不要在 GUI 里指向 `tests/fixtures/` 下的 vault**，那个是测试用的，改坏了测试会挂。用本目录的 vault。

## 目录说明

```
examples/
├── vault/营销资料库/          # 示例资料库（vault_root 指向这里）
│   ├── 引言模块/吸尘器/痛点共鸣/   (2 条)
│   ├── 科普模块/吸尘器/挑选攻略/   (2 条)
│   └── 产品模块/吸尘器/            (3 条：自有品牌 CEWEY + 竞品戴森/小米)
└── skills/
    └── xiaohongshu-polish.md      # 示例 skill（润色阶段注入的用户风格指令）
```

模板沿用仓库根目录的 `templates/daogou-changjing-renqun.json`（导购文-场景人群型·吸尘器），无需新建。

## GUI 里怎么填

打开 **设置页**，填三项：

| 字段 | 填什么 |
|------|--------|
| `vault_root` | `D:\CSM\examples\vault\营销资料库` |
| `default_template` | `D:\CSM\templates\daogou-changjing-renqun.json` |
| `out_dir` | 任意空目录，例如 `D:\CSM\output` |
| `skill_dir`（可选） | `D:\CSM\examples\skills` |

保存后回**首页**：

- **单篇**：关键词填"吸尘器"（或"宠物家庭吸尘器"等），点生成 → 跳文章页 → 选 `xiaohongshu-polish.md` → 润色 → 导出。
- **批量**：关键词框贴 2-3 个，点开始，看批量结果页的进度/成功/失败列表。

## 扩展：加自己的素材

按相同结构往 vault 里塞 md 文件即可（front-matter 字段参考现有文件）。核心结构：

```
vault_root/模块名/产品名/组件类型/*.md
```

front-matter 必备字段：`产品`、`素材类型`、`组件类型`（模板 slot 的 `filter` 会按 `组件类型` 匹配）；品牌素材需要 `品牌` 和 `型号`。
