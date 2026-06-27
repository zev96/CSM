"""禁区 lint 规则：默认词表/正则 + config 覆盖合并。"""
from __future__ import annotations
import re
from dataclasses import dataclass

from csm_core.config import LintConfig

DEFAULT_META = ["广告", "推广", "赞助", "软文"]

# 绝对化 = 广告法极限词 + 承诺词。curated 短语，默认不含裸「最」/温度词（最近/最后/
# 最终/最初）/测量歧义前缀（最大/最高/最小/最低）——嫌漏经 extra_absolute 加严。
DEFAULT_ABSOLUTE = [
    "最佳", "最好", "最强", "最优", "最先进", "最值得", "最顶级", "最专业",
    "第一", "首个", "首选", "唯一", "独家", "顶级", "极致", "国家级", "世界级",
    "百分百", "100%", "绝对", "永久", "永不", "万能", "根治", "彻底根除", "包治",
    "史上最", "全网最", "全国最", "零缺陷", "永不衰减", "100%安全",
]

DEFAULT_TRAFFIC = [
    "点击下方链接", "点击链接", "戳链接", "链接在评论", "关注账号", "关注我",
    "抽奖", "免费领", "免费送", "加微信", "加V", "扫码", "扫描二维码",
    "私信", "私我", "主页领", "简介领",
]

EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002B00-\U00002BFF\U00002300-\U000023FF\U0000FE00-\U0000FE0F"
    "\U0000200D\U000020E3]+"
)
DASH_PATTERN = re.compile(r"[—―]+")
QUOTE_CHARS = "“”\""   # " "（U+201C/201D）+ ASCII "；不含「」/单引号


@dataclass(frozen=True)
class Rules:
    meta: tuple[str, ...]
    absolute: tuple[str, ...]
    traffic: tuple[str, ...]
    check_emoji: bool
    check_dash: bool
    check_quote: bool


def _merge(default: list[str], extra: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for w in (*default, *extra):
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return tuple(out)


def build_rules(config: LintConfig | None) -> Rules:
    config = config or LintConfig()
    disabled = set(config.disabled_categories)
    return Rules(
        meta=() if "meta_speak" in disabled else _merge(DEFAULT_META, config.extra_meta),
        absolute=() if "absolute" in disabled else _merge(DEFAULT_ABSOLUTE, config.extra_absolute),
        traffic=() if "traffic" in disabled else _merge(DEFAULT_TRAFFIC, config.extra_traffic),
        check_emoji="emoji" not in disabled,
        check_dash="dash" not in disabled,
        check_quote="quote" not in disabled,
    )
