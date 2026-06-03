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
    new_chat_sel: str | None = None  # 「新建对话」图标（开干净会话，清旧上下文）；None→打开即新会话
    deep_think: bool = False          # 提交前开启「深度思考」开关（_flow.enable_toggle_by_text，文字定位）
    tool_web_search: tuple[str, str] | None = None  # (工具按钮sel, 菜单项文字)——元宝式联网搜索（菜单内开）
    source_text_sel: str | None = None  # 信源无<a>时抓纯文本条目作 name-only 信源（元宝 COT 搜到的资料，in-page）
    toolcall_sel: str | None = None   # Kimi「搜索网页」toolcall——点开露出信源<a>（内联<a>不稳，要点开）
    exclude_hosts: tuple[str, ...] = ()


SITES: dict[str, SiteSpec] = {
    # ✅ 真站校准过（_calib 探针实测：登录态 send 出 1587 字 + 7 来源）
    "deepseek": SiteSpec(
        platform="deepseek",
        url="https://chat.deepseek.com/",
        composer_sel="textarea",          # 纯 textarea，page.fill 可用
        send_sel=None,                    # textarea 走 Enter 提交（无发送按钮元素）
        web_toggle_sel=None,              # 「智能搜索」默认开（用户实测默认卡其=默认开启）→ 不动它
        generating_sel=None,              # 无停止键 aria → make_done_predicate 走内容增长兜底
        # ⚠ 深度思考(R1) 开启后推理会渲染进 div.ds-think-content>div.ds-markdown，
        # 与答案同 markdown 类 → 必须收窄到答案主容器，排除推理，否则抽取吃到推理文本。
        answer_sel="div.ds-markdown.ds-assistant-message-main-content",
        citation_sel="div.ds-markdown.ds-assistant-message-main-content",  # 答案内的 <a> 来源（非推理里的搜索结果）
        logged_in_sel="textarea",         # 探针 send 无 login wall = 真登录
        logged_out_sel=None,
        deep_think=True,                  # 用户要求：DeepSeek 开深度思考（智能搜索默认已开）
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
        citation_sel="div.markdown",         # 内联 <a>（不稳，常为空）→ kimi.py 改「点开 toolcall + 全页抓」
        logged_in_sel="div[contenteditable='true']",
        logged_out_sel="span.user-name:-soup-contains('登录')",  # 真站校准：账号区显示「登录」=未登录
        # 真站校准：Kimi 信源不在内联 <a>（时有时无），点开「搜索网页」toolcall 才露出
        # 搜到的网页链接（49 条含 bing 跳转壳 + 直链）→ 点开后全页抓 <a> 再过滤。
        toolcall_sel="[class*='toolcall']",
        # bing.com=搜索跳转壳（非真信源），moonshot/kimi/mokahr=自家页脚链接，全过滤。
        exclude_hosts=("kimi.com", "moonshot.cn", "moonshot.ai", "kimi.ai",
                       "mokahr.com", "bing.com"),
    ),
    "yuanbao": SiteSpec(
        platform="yuanbao",
        url="https://yuanbao.tencent.com/",
        composer_sel="div.ql-editor",   # Quill 富文本编辑器，keyboard.type 输入
        send_sel=None,                   # 真站校准：enterkeyhint=send → Enter 提交（无发送按钮元素）
        web_toggle_sel=None,             # 默认联网（探针实测答案带搜索结果）
        generating_sel=None,             # 无停止键 aria → 内容增长兜底
        # ⚠ 深度思考开启后，推理(COT)也渲染成 hyc-common-markdown，但带 -cot 后缀
        # （hyc-common-markdown-style-cot，在 hyc-component-deepsearch-cot 里）；最终
        # 答案是 hyc-common-markdown-style（无 -cot）。必须排除 -cot，否则抓到推理文本。
        answer_sel="div[class*='hyc-common-markdown']:not([class*='-cot'])",
        citation_sel="div[class*='hyc-common-markdown']:not([class*='-cot'])",  # 元宝信源走 source_panel，此项未用
        logged_in_sel="div[contenteditable='true']",
        logged_out_sel="[data-placeholder*='请登录']",  # 真站校准：composer 占位「请登录后输入内容」=未登录
        # 真站校准：元宝打开即恢复上次会话 → 必须先点「新建对话」开干净会话，
        # 否则 done 判定/抓取都会读到上一轮答案。父按钮 JS 点（见 _flow.start_new_chat）。
        new_chat_sel="span.icon-yb-ic_newchat_20",
        # 用户实测：元宝须手动开 深度思考 + 联网搜索（在「工具」菜单里）才出参考资料。
        deep_think=True,
        tool_web_search=("button.ybc-atomSelect-tools", "联网搜索"),
        # 元宝信源无 URL（DOM 全程无真实来源链接）。深度思考 COT 的「搜到 N 篇资料」是
        # in-page 的（无需点击/hover，比 hover-gated 的「源」抽屉稳）→ 抓 doc-container 文本
        # 作 name-only 信源（媒体名+标题，domain="" 不进域名榜，但用户能看到元宝引了谁）。
        source_text_sel="div[class*='__item__doc-container']",
        exclude_hosts=("yuanbao.tencent.com", "tencent.com"),
    ),
}
