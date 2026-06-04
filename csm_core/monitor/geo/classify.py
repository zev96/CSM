# csm_core/monitor/geo/classify.py
"""信源域名规整 + source_type 分类。

domain：取「注册域名」（去子域）。优先用 tldextract（声明依赖，随 bundle
打包，离线配置），否则用一个覆盖中国常见多段后缀（.com.cn/.gov.cn/.edu.cn…）
的轻量回退（_MULTI_SUFFIX）。

source_type：规则表优先（精确域名 → 类别）。规则未命中返回「其他」；
LLM 兜底归类在抽取层（Task 8）按需调用，这里只做确定性规则。

# 注：「官网」由抽取层/品牌官网域名判定，规则表不输出（品牌官网是 per-task 配置，
#      不是全局固定域名）。
"""
from __future__ import annotations
import logging
from urllib.parse import urlparse

from .models import Citation, ClassifiedCitation

logger = logging.getLogger(__name__)

# ── tldextract：模块级实例，离线配置（不联网、不写缓存）──────────────────────
# suffix_list_urls=() 强制使用 tldextract 自带的 bundled snapshot，
# cache_dir=None 禁止写文件系统缓存（PyInstaller bundle 里 tmp 路径不可预期）。
try:
    import tldextract  # type: ignore
    _EXTRACT: tldextract.TLDExtract | None = tldextract.TLDExtract(
        suffix_list_urls=(), cache_dir=None
    )
except ImportError:
    _EXTRACT = None
    logger.warning(
        "tldextract 未安装，csm_core.monitor.geo.classify 使用限量 _MULTI_SUFFIX 回退；"
        "release bundle 应包含 tldextract（见 pyproject.toml + spec hiddenimports）。"
    )

# 多段后缀：识别 a.b.com.cn 这种注册域名 = b.com.cn
_MULTI_SUFFIX = (
    ".com.cn", ".net.cn", ".org.cn", ".gov.cn", ".edu.cn", ".ac.cn",
    ".com.hk", ".com.tw",
)

# 精确注册域名 → 类别
# 注：「官网」由抽取层/品牌官网域名判定，规则表不输出（品牌官网是 per-task 配置，
#      不是全局固定域名）。
_RULES: dict[str, str] = {
    "zhihu.com": "知乎",
    "xiaohongshu.com": "小红书",
    "xhslink.com": "小红书",
    # 权威媒体（央媒/门户/政务）
    "people.com.cn": "权威媒体", "xinhuanet.com": "权威媒体", "gov.cn": "权威媒体",
    "cctv.com": "权威媒体", "thepaper.cn": "权威媒体", "caixin.com": "权威媒体",
    "36kr.com": "权威媒体", "ifeng.com": "权威媒体", "sina.com.cn": "权威媒体",
    # 电商
    "jd.com": "电商", "taobao.com": "电商", "tmall.com": "电商",
    "pinduoduo.com": "电商", "suning.com": "电商",
}


# host 级拆分：一个主域名下的多个独立内容平台，注册域名会合并掉它们，
# 所以在「完整 host」层识别后拆开（百度系/微信）。⚠️ 写入时生效：
# geo_citations 存的是这里产出的 domain，老数据是合并态，需重跑才体现。
_CANONICAL_HOST: dict[str, tuple[str, str]] = {
    "baijiahao.baidu.com": ("baijiahao.baidu.com", "百家号"),
    "baike.baidu.com": ("baike.baidu.com", "百度百科"),
    "zhidao.baidu.com": ("zhidao.baidu.com", "百度知道"),
    "tieba.baidu.com": ("tieba.baidu.com", "贴吧"),
    "mp.weixin.qq.com": ("mp.weixin.qq.com", "微信公众号"),
}

# source_type → 权威度基数（高权重信源排序用）。未知类型回退「其他」。
_AUTHORITY: dict[str, float] = {
    "权威媒体": 1.0, "百度百科": 0.9, "知乎": 0.8,
    "百家号": 0.6, "微信公众号": 0.6, "小红书": 0.6,
    "百度知道": 0.5, "电商": 0.4, "贴吧": 0.3, "其他": 0.2,
}


def authority(source_type: str) -> float:
    return _AUTHORITY.get(source_type, _AUTHORITY["其他"])


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return ""


def canonical_source(url: str) -> tuple[str, str]:
    """(canonical domain, source_type)。先查 host 级拆分表（百度系/微信），
    否则注册域名 + 规则分类（*.zhihu.com 在 registered_domain 合并）。"""
    host = _host(url)
    if host in _CANONICAL_HOST:
        return _CANONICAL_HOST[host]
    dom = registered_domain(url)
    return dom, classify_source(dom)


def registered_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        host = ""
    if not host or "." not in host:
        return ""
    if _EXTRACT is not None:
        ext = _EXTRACT(url)
        if ext.domain and ext.suffix:
            return f"{ext.domain}.{ext.suffix}"
        return ""
    # 回退：处理多段后缀
    for suf in _MULTI_SUFFIX:
        if host.endswith(suf):
            head = host[: -len(suf)].split(".")[-1]
            return f"{head}{suf}" if head else host
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_source(domain: str) -> str:
    d = (domain or "").lower()
    if d in _RULES:
        return _RULES[d]
    # 政务/教育兜底：任何 .gov.cn / .edu.cn 注册域归权威媒体
    if d.endswith(".gov.cn") or d.endswith(".edu.cn"):
        return "权威媒体"
    return "其他"


def classify_citations(cits: list[Citation]) -> list[ClassifiedCitation]:
    out: list[ClassifiedCitation] = []
    for c in cits:
        dom, st = canonical_source(c.url)
        out.append(ClassifiedCitation(url=c.url, title=c.title, domain=dom, source_type=st))
    return out
