"""Starter markdown body for new skills.

Matches the structure of the existing xiaohongshu-polish.md example so
users have a consistent four-section starting point (style / structure /
prohibitions / output). The { product } placeholder is prose only — no
templating substitution; users edit it in place."""

SKILL_SKELETON = """# 新 Skill

你是一位专注于 { product } 品类的内容编辑。收到毛坯文后，按下面的规则进行**润色改写**。

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
"""
