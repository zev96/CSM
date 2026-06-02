"""每站 RPA 配置（URL + 选择器）—— 脆弱的逐站常量集中一处。

线上改版/选择器漂移 → 改这里 + 重抓 fixture/重新校准（不动 provider 逻辑）。
⚠ 区分两类选择器（见 _flow 顶注）：
- 纯函数用（bs4，必须合法 CSS）：answer_sel / citation_sel / logged_in_sel / logged_out_sel
- page 端用（可 Playwright 语法）：composer_sel / send_sel / web_toggle_sel / generating_sel

⚠ 下列选择器为初始最佳猜测，**必须用 Task 5/9/10 的人工 e2e 校准**（在原生
测试窗登录后 dump page.content() 比对真实 DOM）。校准前 CI 只跑 provider
错误路径（不依赖真选择器），真站抓取靠人工验收。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class SiteSpec:
    platform: str
    url: str
    composer_sel: str
    send_sel: str | None          # None → 按 Enter 提交
    web_toggle_sel: str | None    # None → 默认联网/无开关
    generating_sel: str | None    # 生成中在场的元素（如停止按钮）；None → 退化为 send 可点
    answer_sel: str               # 回答容器（抓正文，CSS）
    citation_sel: str             # 引用容器（抓来源链接，CSS；常与 answer_sel 同）
    logged_in_sel: str            # 登录态正向标志（CSS，如 composer 存在）
    logged_out_sel: str | None    # 未登录标志（CSS，如登录按钮稳定 class；命中=未登录）
    exclude_hosts: tuple[str, ...] = ()


SITES: dict[str, SiteSpec] = {
    "deepseek": SiteSpec(
        platform="deepseek",
        url="https://chat.deepseek.com/",
        composer_sel="textarea#chat-input, textarea",
        send_sel="div[role='button'][aria-label*='发送'], button[type='submit']",
        web_toggle_sel="div[role='button']:has-text('联网搜索')",  # page 端，允许 :has-text
        generating_sel="div[role='button'][aria-label*='停止']",    # page 端
        answer_sel="div.ds-markdown",                               # CSS，校准
        citation_sel="div.ds-markdown",                             # CSS，校准
        logged_in_sel="textarea",                                   # CSS
        logged_out_sel=None,                                        # 校准时填稳定登录按钮 class
        exclude_hosts=("deepseek.com",),
    ),
    # kimi（Task 9）/ yuanbao（Task 10）在各自 Task 加入此 dict。
}
