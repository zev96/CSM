"""WBI signing for the Bilibili web API.

Vendored from MediaCrawler:
  https://github.com/NanmiCoder/MediaCrawler/blob/main/media_platform/bilibili/help.py
  commit f328ee35b55e25e8aaeb9c847fe8b622e3f3447f

Original license: NON-COMMERCIAL LEARNING LICENSE 1.1 (see
``csm_core/mining/platforms/_vendor/README.md`` for full attribution and
``reference/MediaCrawler/LICENSE`` after cloning the upstream repo).

WBI algorithm independent reference:
  https://socialsisteryi.github.io/bilibili-API-collect/docs/misc/sign/wbi.html
"""
from __future__ import annotations

import time
import urllib.parse
from hashlib import md5
from typing import Dict


class BilibiliSign:
    """w_rid / wts signer for Bilibili's WBI API endpoints.

    Initialize with ``img_key`` and ``sub_key``, extracted from the basename
    (without extension) of ``wbi_img.img_url`` and ``wbi_img.sub_url`` in
    the ``/x/web-interface/nav`` response. Keys rotate roughly every 24h —
    caller is expected to refresh on signing failures.
    """

    # Magic permutation table — same in all public reverse-engineering refs.
    # 64 indices, each addressing one byte of (img_key + sub_key).
    MAP_TABLE: tuple[int, ...] = (
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52,
    )

    def __init__(self, img_key: str, sub_key: str) -> None:
        self.img_key = img_key
        self.sub_key = sub_key

    def get_salt(self) -> str:
        """Mix ``img_key + sub_key`` through ``MAP_TABLE``, take first 32 chars."""
        mixin = self.img_key + self.sub_key
        return "".join(mixin[i] for i in self.MAP_TABLE)[:32]

    def sign(self, req_data: Dict) -> Dict:
        """Add ``wts`` and ``w_rid`` to the request parameters in-place + return.

        Sorting + URL-encoding follows the spec: keys sorted lexically,
        values stripped of ``!'()*`` before encoding (Bilibili's signer
        ignores those characters, so we must too).
        """
        req_data["wts"] = int(time.time())
        req_data = dict(sorted(req_data.items()))
        req_data = {
            k: "".join(c for c in str(v) if c not in "!'()*")
            for k, v in req_data.items()
        }
        query = urllib.parse.urlencode(req_data)
        salt = self.get_salt()
        req_data["w_rid"] = md5((query + salt).encode()).hexdigest()
        return req_data
