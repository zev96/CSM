"""TikHub API 适配器注册表构造。

分派层(monitor_lifecycle)用当前 config + keyring 造好注册表注入 MonitorLoop。
client_factory 惰性读 config(base_url + key),每次 fetch 现取,配置改了下轮生效。
id_extractor 复用本地 _extract_video_id(短链解析用 curl_cffi 会话,和本地同法)。
"""
from __future__ import annotations

from .client import TikHubClient
from .zhihu_adapter import ZhihuQuestionApiAdapter
from .comment_adapter import (
    CommentApiAdapter, DOUYIN_SPEC, BILIBILI_SPEC, KUAISHOU_SPEC,
)
from csm_core.monitor.platforms.douyin_comment import DouyinCommentAdapter
from csm_core.monitor.platforms.kuaishou_comment import KuaishouCommentAdapter
from csm_core.monitor.platforms.bilibili_comment import BilibiliCommentAdapter


def _cffi_session():
    """给 _extract_video_id 用的 follow-redirect 会话(短链展开;curl_cffi 躲指纹拦截)。"""
    from curl_cffi import requests
    return requests.Session(impersonate="chrome120")


def build_api_adapters(get_config, key_reader):
    """构造 {task_type: api_adapter}。
    get_config() -> AppConfig(取 tikhub_base_url);key_reader("tikhub", cfg) -> str(keyring key)。
    """
    def client_factory():
        cfg = get_config()
        return TikHubClient(base_url=cfg.monitor.tikhub_base_url,
                            api_key=key_reader("tikhub", cfg))

    def _dy(url):
        return DouyinCommentAdapter._extract_video_id(_cffi_session(), url)

    def _ks(url):
        return KuaishouCommentAdapter._extract_video_id(_cffi_session(), url)

    def _bl(url):
        res = BilibiliCommentAdapter._extract_video_id(url)   # 纯正则,返回 (vid,id_type)|None
        return res if res else (None, "")

    return {
        "zhihu_question": ZhihuQuestionApiAdapter(client_factory),
        "douyin_comment": CommentApiAdapter(DOUYIN_SPEC, client_factory, _dy),
        "bilibili_comment": CommentApiAdapter(BILIBILI_SPEC, client_factory, _bl),
        "kuaishou_comment": CommentApiAdapter(KUAISHOU_SPEC, client_factory, _ks),
    }
