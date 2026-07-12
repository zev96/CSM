"""失败原因分类(纯函数)—— 把 provider 的 error 文本 + status 归一到有限枚举,
供前端映射成人话(替掉写死的「够不到平台」)。

只吃字符串(error = 落库的 repr(e) / blocked 文案)+ status,不吃异常对象:
error cell 存库存的是 repr,下钻/前端拿到的也是字符串,单一真相源。

优先级(从最具体到最泛,首个命中即返回)—— 顺序是正确性的一部分:
  中断 > 未登录 > 限流 > 配额 > 风控 > 流超时 > 选择器 > 网络 > 兜底。
「流超时」(wait_stream_done 专属标记)必须早于泛化的 "timeout",因为
Playwright 的选择器/点击超时消息也含 "timeout",否则会把流超时误判成选择器漂移。
"""
from __future__ import annotations
from typing import Literal

FailReason = Literal[
    "not_logged_in", "timeout", "selector_drift", "rate_limited",
    "quota_exhausted", "content_blocked", "network", "interrupted", "unknown",
]


def classify_fail_reason(*, status: str, error: str) -> str:
    """把 (status, error 文本) 归类成 FailReason 之一。纯函数,无 I/O。"""
    e = error or ""
    t = e.lower()
    # 1) 中断(睡眠唤醒 / wall-clock 跳变)—— Phase 3b 会在 error 里打这些标记;
    #    3a 先把映射备好,3b 接上检测即生效。
    if "interrupted" in t or "时钟跳变" in e or "睡眠唤醒" in e:
        return "interrupted"
    # 2) 未登录 —— RPA blocked 的 login_blocked_msg 含「未登录」;API 侧 401/未授权。
    if ("未登录" in e or "请登录" in e or "登录已过期" in e
            or "not logged" in t or "unauthorized" in t or "401" in t):
        return "not_logged_in"
    # 3) 限流。
    if ("429" in t or "rate limit" in t or "too many requests" in t
            or "限流" in e or "频繁" in e):
        return "rate_limited"
    # 4) 配额 / 欠费。
    if ("quota" in t or "insufficient" in t or "balance" in t or "arrears" in t
            or "欠费" in e or "余额" in e or "配额" in e):
        return "quota_exhausted"
    # 5) 内容风控。「安全过滤」是三家 API provider(通义/豆包/Kimi)content_filter/
    #    sensitive 时实际写的文案(如「内容被通义安全过滤」),必须命中,否则会落到下面
    #    blocked→not_logged_in 兜底,把内容拦截误报成「未登录」(误导用户去查登录)。
    if ("风控" in e or "敏感" in e or "违规" in e or "安全过滤" in e
            or "content_filter" in t or ("content" in t and "block" in t)):
        return "content_blocked"
    # 6) 流式超时(答案没在期限内收敛)—— 必须早于泛 timeout(见模块头注)。
    if "wait_stream_done" in t or ("stream" in t and "timeout" in t):
        return "timeout"
    # 7) 选择器漂移(Playwright 点击 / 等待元素超时、找不到元素)。
    if ("timeout" in t or "waiting for" in t or "selector" in t or "locator" in t
            or "找不到" in e or "no element" in t or "not found" in t):
        return "selector_drift"
    # 8) 网络 / 浏览器传输异常(连接、页面被关)。
    if (("target" in t and "closed" in t) or "connect" in t or "connection" in t
            or "network" in t or "ssl" in t or "econn" in t):
        return "network"
    # 9) 兜底:blocked 未命中上面任一 → 多半仍是登录/风控,给 not_logged_in
    #    (用户第一反应去登录,比 unknown 更可行动);error → unknown。
    if status == "blocked":
        return "not_logged_in"
    return "unknown"
