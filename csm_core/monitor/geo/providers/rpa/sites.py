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
    # ✅ 真站校准过（_calib 探针实测：登录态 send 出 1587 字 + 7 来源）
    "deepseek": SiteSpec(
        platform="deepseek",
        url="https://chat.deepseek.com/",
        composer_sel="textarea",          # 纯 textarea，page.fill 可用
        send_sel=None,                    # textarea 走 Enter 提交（无发送按钮元素）
        web_toggle_sel=None,              # 「智能搜索」状态随 profile 持久；探针默认即带来源
        generating_sel=None,              # 无停止键 aria → make_done_predicate 走内容增长兜底
        answer_sel="div.ds-markdown",     # 探针抓到 1587 字
        citation_sel="div.ds-markdown",   # 探针抓到 7 个真实来源
        logged_in_sel="textarea",         # 探针 send 无 login wall = 真登录
        logged_out_sel=None,
        exclude_hosts=("deepseek.com",),
    ),
    "kimi": SiteSpec(
        platform="kimi",
        url="https://kimi.com/",
        composer_sel="div[contenteditable='true']",  # Lexical 富文本编辑器，keyboard.type 输入
        send_sel=".send-button-container",   # 真站校准：图标 div 发送键（打字后点它，非 Enter）
        web_toggle_sel=None,                 # 默认联网（探针带「搜索网页…50 个结果」+ 来源）
        generating_sel=None,                 # 无停止键 aria → 内容增长兜底
        answer_sel="div.markdown",           # 真站校准：抓到回答 prose
        citation_sel="div.markdown",         # Kimi 仅 markdown 内 <a> 来源（搜索结果非 <a>，暂取此）
        logged_in_sel="div[contenteditable='true']",
        logged_out_sel="span.user-name:-soup-contains('登录')",  # 真站校准：账号区显示「登录」=未登录
        exclude_hosts=("kimi.com", "moonshot.cn"),
    ),
    "yuanbao": SiteSpec(
        platform="yuanbao",
        url="https://yuanbao.tencent.com/",
        composer_sel="div.ql-editor",   # Quill 富文本编辑器，keyboard.type 输入
        send_sel=None,                   # 真站校准：enterkeyhint=send → Enter 提交（无发送按钮元素）
        web_toggle_sel=None,             # 默认联网（探针实测答案带搜索结果）
        generating_sel=None,             # 无停止键 aria → 内容增长兜底
        answer_sel="div[class*='markdown']",   # 真站校准：抓到 973 字回答
        citation_sel="div[class*='markdown']", # 元宝来源非 <a>（探针 0 链接），暂取此，后续再挖
        logged_in_sel="div[contenteditable='true']",
        logged_out_sel="[data-placeholder*='请登录']",  # 真站校准：composer 占位「请登录后输入内容」=未登录
        exclude_hosts=("yuanbao.tencent.com", "tencent.com"),
    ),
}
