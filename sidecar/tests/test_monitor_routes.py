"""Tests for /api/monitor/*.

These exercise the route + service layer against a per-test sqlite DB.
The MonitorLoop itself is NOT started here (the run-now route returns 503
when the loop is absent, and we test that path explicitly). The full
loop integration is covered by sidecar/tests/test_monitor_loop.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from csm_core.monitor import storage
from csm_core.monitor.base import MonitorResult


def _seed_task(client: TestClient, **overrides) -> int:
    body = {
        "type": "zhihu_question",
        "name": "测试任务",
        "target_url": "https://www.zhihu.com/question/12345",
        "config": {"target_brand": "x", "top_n": 5},
        "schedule_cron": "manual",
        "enabled": True,
    }
    body.update(overrides)
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── Storage gate ───────────────────────────────────────────────────────────
def test_routes_503_when_storage_uninitialized(settings_path, vault_cache_reset):
    """Accessing any monitor route without monitor_db fixture → 503."""
    from csm_sidecar import auth
    from csm_sidecar.main import app
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {auth.get_token()}"
        resp = c.get("/api/monitor/tasks")
    assert resp.status_code == 503
    assert "not initialised" in resp.json()["detail"]


# ── Task CRUD ──────────────────────────────────────────────────────────────
def test_create_list_get_update_delete(client: TestClient, monitor_db: Path):
    list_resp = client.get("/api/monitor/tasks")
    assert list_resp.status_code == 200
    assert list_resp.json() == {"count": 0, "tasks": []}

    tid = _seed_task(client, name="task1")
    assert tid > 0

    list2 = client.get("/api/monitor/tasks").json()
    assert list2["count"] == 1
    assert list2["tasks"][0]["name"] == "task1"

    get1 = client.get(f"/api/monitor/tasks/{tid}").json()
    assert get1["id"] == tid

    upd = client.patch(f"/api/monitor/tasks/{tid}", json={
        "type": "zhihu_question",
        "name": "renamed",
        "target_url": "https://www.zhihu.com/question/12345",
        "config": {"target_brand": "x", "top_n": 7},
        "schedule_cron": "08:00",
        "enabled": False,
    })
    assert upd.status_code == 200
    assert upd.json()["name"] == "renamed"
    assert upd.json()["enabled"] is False

    del_resp = client.delete(f"/api/monitor/tasks/{tid}")
    assert del_resp.status_code == 204
    assert client.get(f"/api/monitor/tasks/{tid}").status_code == 404


def test_create_invalid_type_422(client: TestClient, monitor_db: Path):
    resp = client.post("/api/monitor/tasks", json={
        "type": "not_a_type",
        "name": "x",
        "target_url": "x",
    })
    assert resp.status_code == 422


def test_get_unknown_task_404(client: TestClient, monitor_db: Path):
    assert client.get("/api/monitor/tasks/9999").status_code == 404


def test_list_filtered_by_type_and_enabled(client: TestClient, monitor_db: Path):
    _seed_task(client, name="zhi", type="zhihu_question")
    _seed_task(client, name="bili", type="bilibili_comment",
               target_url="https://www.bilibili.com/video/AV1")
    _seed_task(client, name="off", type="bilibili_comment",
               target_url="https://www.bilibili.com/video/AV2", enabled=False)

    bili = client.get("/api/monitor/tasks", params={"type": "bilibili_comment"}).json()
    assert bili["count"] == 2

    bili_on = client.get("/api/monitor/tasks", params={
        "type": "bilibili_comment", "enabled_only": True,
    }).json()
    assert bili_on["count"] == 1
    assert bili_on["tasks"][0]["name"] == "bili"


# ── Run-now ────────────────────────────────────────────────────────────────
def test_run_now_when_loop_not_started_returns_503(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    resp = client.post(f"/api/monitor/tasks/{tid}/run-now")
    assert resp.status_code == 503


def test_run_now_unknown_task_404(client: TestClient, monitor_db: Path, monkeypatch):
    """When the loop IS running, an unknown task_id is a 404."""
    from csm_sidecar.services import monitor_lifecycle
    from csm_sidecar.services.monitor_loop import MonitorLoop
    fake_loop = MonitorLoop(event_sink=lambda _e: None, adapters={})
    fake_loop.start()
    monkeypatch.setattr(monitor_lifecycle, "_loop", fake_loop)
    try:
        resp = client.post("/api/monitor/tasks/9999/run-now")
        assert resp.status_code == 404
    finally:
        fake_loop.stop()


# ── Results ────────────────────────────────────────────────────────────────
def test_list_results_empty(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    resp = client.get("/api/monitor/results", params={"task_id": tid})
    assert resp.status_code == 200
    assert resp.json() == {"task_id": tid, "count": 0, "results": []}


def test_list_results_returns_recent_first(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    # Seed 3 results directly via storage; route should return them ordered
    # newest first.
    for i in range(3):
        storage.save_result(MonitorResult(
            task_id=tid,
            checked_at=datetime.now() - timedelta(minutes=10 - i),
            status="ok",
            rank=i + 1,
            metric={"i": i},
        ))
    resp = client.get("/api/monitor/results", params={"task_id": tid, "limit": 5})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 3
    # Most recent first: rank=3 (i=2) should be first.
    assert data["results"][0]["rank"] == 3


def test_list_results_limit_capped(client: TestClient, monitor_db: Path):
    tid = _seed_task(client)
    resp = client.get("/api/monitor/results", params={"task_id": tid, "limit": 9999})
    # Pydantic Field(le=500) → 422 on out-of-range query.
    assert resp.status_code == 422


# ── Cookies ────────────────────────────────────────────────────────────────
def test_cookie_lifecycle(client: TestClient, monitor_db: Path):
    list_empty = client.get("/api/monitor/cookies", params={"platform": "zhihu_question"})
    assert list_empty.json()["count"] == 0

    add = client.post("/api/monitor/cookies/zhihu_question", json={
        "cookies_text": "z=1; auth=xxx",
        "label": "main account",
    })
    assert add.status_code == 201
    cred_id = add.json()["id"]

    listed = client.get("/api/monitor/cookies", params={"platform": "zhihu_question"})
    assert listed.json()["count"] == 1
    cookie = listed.json()["cookies"][0]
    assert cookie["label"] == "main account"
    # Sensitive fields stripped.
    assert "cookies_text" not in cookie
    assert "user_agent" not in cookie

    client.delete(f"/api/monitor/cookies/{cred_id}")
    assert client.get("/api/monitor/cookies", params={"platform": "zhihu_question"}).json()["count"] == 0


def test_cookie_add_empty_text_422(client: TestClient, monitor_db: Path):
    resp = client.post("/api/monitor/cookies/zhihu_question", json={
        "cookies_text": "",
        "label": "x",
    })
    assert resp.status_code == 422


# ── Summary ────────────────────────────────────────────────────────────────
def test_summary_empty(client: TestClient, monitor_db: Path):
    from csm_sidecar.services.monitor_service import PLATFORM_TYPES

    resp = client.get("/api/monitor/summary")
    assert resp.status_code == 200
    data = resp.json()
    # summary 必须为每个已注册平台类型各出一个 key(空库时 count=0)。从 PLATFORM_TYPES
    # 派生而非硬编码 —— 新增平台类型(如后来加的 zhihu_search)时不再悄悄 stale。
    assert set(data["platforms"].keys()) == set(PLATFORM_TYPES)
    for p in data["platforms"].values():
        assert p["task_count"] == 0


def test_summary_includes_latest_result(client: TestClient, monitor_db: Path):
    tid = _seed_task(client, type="bilibili_comment",
                     target_url="https://www.bilibili.com/video/X")
    storage.save_result(MonitorResult(
        task_id=tid,
        checked_at=datetime.now(),
        status="ok",
        rank=2,
        metric={"retained": 8, "total": 10},
    ))
    summary = client.get("/api/monitor/summary").json()
    bili = summary["platforms"]["bilibili_comment"]
    assert bili["task_count"] == 1
    assert bili["tasks"][0]["latest"]["metric"]["retained"] == 8


# ── Auth ────────────────────────────────────────────────────────────────────
def test_monitor_routes_require_auth(monitor_db: Path):
    from csm_sidecar.main import app
    with TestClient(app) as c:
        # No Authorization header.
        resp = c.get("/api/monitor/tasks")
    assert resp.status_code == 401


# ── Baidu Keyword Monitor ──────────────────────────────────────────────────────
def test_create_baidu_keyword_task(client: TestClient, monitor_db: Path):
    body = {
        "type": "baidu_keyword",
        "name": "百度-Claude教程",
        "target_url": "search:Claude Code 教程",
        "config": {
            "search_keyword": "Claude Code 教程",
            "target_brands": ["Claude", "Anthropic"],
            "headless": True,
        },
        "schedule_cron": "manual",
        "enabled": True,
    }
    resp = client.post("/api/monitor/tasks", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["type"] == "baidu_keyword"
    assert resp.json()["config"]["target_brands"] == ["Claude", "Anthropic"]


class TestBaiduNativeModeRoutes:
    def test_detect_chrome_returns_paths_when_present(self, client, monkeypatch):
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda user_data_dir=None: "C:/Chrome/chrome.exe",
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_user_data_dir",
            lambda: "C:/User Data",
        )
        resp = client.post("/api/monitor/baidu/detect-chrome")
        assert resp.status_code == 200
        data = resp.json()
        assert data["executable_path"] == "C:/Chrome/chrome.exe"
        assert data["user_data_dir"] == "C:/User Data"

    def test_detect_chrome_returns_none_when_missing(self, client, monkeypatch):
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda user_data_dir=None: None,
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_user_data_dir",
            lambda: None,
        )
        resp = client.post("/api/monitor/baidu/detect-chrome")
        assert resp.status_code == 200
        data = resp.json()
        assert data["executable_path"] is None
        assert data["user_data_dir"] is None

    def test_list_profiles_returns_array(self, client, monkeypatch):
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.list_profiles",
            lambda path: [
                {"name": "Default", "account_email": "a@gmail.com"},
                {"name": "Profile 1", "account_email": None},
            ],
        )
        resp = client.post(
            "/api/monitor/baidu/list-profiles",
            json={"user_data_dir": "C:/User Data"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["profiles"][0]["name"] == "Default"
        assert data["profiles"][0]["account_email"] == "a@gmail.com"
        assert len(data["profiles"]) == 2

    def test_list_profiles_400_on_empty_path(self, client):
        resp = client.post("/api/monitor/baidu/list-profiles", json={"user_data_dir": ""})
        # Pydantic Field(min_length=1) → FastAPI 422 (Unprocessable Entity)
        assert resp.status_code in (400, 422)

    def test_test_native_success(self, client, monkeypatch):
        """mock baidu_browser_session 不抛 → 返回 {"ok": True}。
        B' pivot: 用 chrome_profile_copy_path 而不是 chrome_user_data_dir。
        """
        from contextlib import contextmanager
        @contextmanager
        def fake_session(**kw):
            assert kw["use_native_chrome"] is True
            assert kw["chrome_profile_name"] == "Default"  # 副本内固定 Default
            yield MagicMock()
        monkeypatch.setattr(
            "csm_sidecar.routes.monitor.baidu_browser_session", fake_session,
        )
        resp = client.post(
            "/api/monitor/baidu/test-native",
            json={
                "chrome_executable_path": "C:/Chrome/chrome.exe",
                "chrome_profile_copy_path": "C:/CSM-Data/baidu_chrome_profile_copy",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_test_native_failure_returns_error_details(self, client, monkeypatch):
        from contextlib import contextmanager
        @contextmanager
        def fake_session(**kw):
            raise RuntimeError("chrome.exe not found")
            yield  # pragma: no cover
        monkeypatch.setattr(
            "csm_sidecar.routes.monitor.baidu_browser_session", fake_session,
        )
        resp = client.post(
            "/api/monitor/baidu/test-native",
            json={
                "chrome_executable_path": "C:/bad/chrome.exe",
                "chrome_profile_copy_path": "C:/CSM-Data/baidu_chrome_profile_copy",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "chrome.exe not found" in body["error"]

    def test_copy_profile_success(self, client, monkeypatch):
        """copy_profile_to 成功 → 返回 ok=True + copy_path + metadata，config 更新。"""
        fake_meta = {
            "imported_at": "2026-05-25T10:00:00",
            "size_mb": 180.5,
            "elapsed_s": 12.3,
        }
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.copy_profile_to",
            lambda **kw: fake_meta,
        )
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={
                "source_user_data_dir": "C:/User Data",
                "source_profile_name": "Default",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "copy_path" in data
        assert data["imported_at"] == "2026-05-25T10:00:00"
        assert data["size_mb"] == 180.5
        assert data["elapsed_s"] == 12.3

    def test_copy_profile_failure_source_not_found(self, client, monkeypatch):
        """source profile 不存在 → 返回 ok=False + error 原样透传，不抛 500。"""
        def _raise(**kw):
            raise FileNotFoundError("Chrome 数据目录不存在：C:/User Data")
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.copy_profile_to",
            _raise,
        )
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={
                "source_user_data_dir": "C:/User Data",
                "source_profile_name": "Default",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "Chrome 数据目录不存在" in data["error"]

    def test_copy_profile_uses_explicit_profile_verbatim(self, client, monkeypatch, tmp_path):
        """用户在下拉里明确选了某个 profile → 原样用它，不被兜底逻辑换掉。

        向后兼容不变量：老配置 / 老前端显式传 "Default" 且它存在时，复制的
        必须还是 Default。
        """
        seen: dict = {}
        def _fake(**kw):
            seen.update(kw)
            return {"imported_at": "t", "size_mb": 1.0, "elapsed_s": 1.0}
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.copy_profile_to", _fake
        )
        user_data = tmp_path / "User Data"
        for n in ("Default", "Profile 1"):
            (user_data / n).mkdir(parents=True)
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={
                "source_user_data_dir": str(user_data),
                "source_profile_name": "Profile 1",
            },
        )
        assert resp.json()["profile_name"] == "Profile 1"
        assert seen["source_profile_name"] == "Profile 1"

    def test_copy_profile_explicit_missing_profile_errors_instead_of_swapping(
        self, client, monkeypatch, tmp_path
    ):
        """显式选的 profile 不存在 → 报「可用的有哪些」，而不是闷声换一个复制。"""
        monkeypatch.setattr(
            "csm_core.config.default_config_dir", lambda: tmp_path / "cfgdir"
        )
        user_data = tmp_path / "User Data"
        (user_data / "Default").mkdir(parents=True)
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={
                "source_user_data_dir": str(user_data),
                "source_profile_name": "Profile 9",
            },
        )
        data = resp.json()
        assert data["ok"] is False
        assert "Profile 9" in data["error"] and "Default" in data["error"]

    def test_copy_profile_normalizes_quoted_path(self, client, monkeypatch, tmp_path):
        """资源管理器「复制文件地址」带引号 —— 不规整就误报「目录不存在」。"""
        monkeypatch.setattr(
            "csm_core.config.default_config_dir", lambda: tmp_path / "cfgdir"
        )
        user_data = tmp_path / "User Data"
        (user_data / "Default").mkdir(parents=True)
        (user_data / "Default" / "Cookies").write_bytes(b"c")
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": f'"{user_data}"'},
        )
        data = resp.json()
        assert data["ok"] is True, data
        cfg = client.get("/api/monitor/baidu/native-config").json()
        assert cfg["chrome_user_data_dir"] == str(user_data)  # 存的是规整后的

    def test_list_profiles_normalizes_quoted_path(self, client, tmp_path):
        user_data = tmp_path / "User Data"
        (user_data / "Default").mkdir(parents=True)
        resp = client.post(
            "/api/monitor/baidu/list-profiles",
            json={"user_data_dir": f'  "{user_data}"  '},
        )
        assert [p["name"] for p in resp.json()["profiles"]] == ["Default"]

    def test_copy_profile_unreadable_dir_returns_error_not_500(
        self, client, monkeypatch, tmp_path
    ):
        """目录能 stat 但列不动（公司机 ACL）→ ok=False，不是 500。"""
        monkeypatch.setattr(
            "csm_core.config.default_config_dir", lambda: tmp_path / "cfgdir"
        )
        user_data = tmp_path / "User Data"
        user_data.mkdir()

        from pathlib import Path as _P
        def boom(self):
            raise PermissionError(13, "Access is denied")
        monkeypatch.setattr(_P, "iterdir", boom)
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": str(user_data)},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False

    def test_copy_profile_refuses_when_source_is_the_copy_dir(
        self, client, monkeypatch, tmp_path
    ):
        """把 CSM 副本目录填成「Chrome 数据目录」→ ok=False，副本原封不动
        （copy_profile_to 会先 rmtree 目标，不拦就是把副本和登录态删光）。"""
        cfg_dir = tmp_path / "cfgdir"
        copy_dir = cfg_dir / "baidu_chrome_profile_copy"
        (copy_dir / "Default").mkdir(parents=True)
        (copy_dir / "Default" / "Cookies").write_bytes(b"login")
        monkeypatch.setattr("csm_core.config.default_config_dir", lambda: cfg_dir)
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": str(copy_dir)},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert (copy_dir / "Default" / "Cookies").is_file()

    def test_list_profiles_flags_unreadable_dir(self, client, monkeypatch, tmp_path):
        """「读不动」要和「空目录」区分开，否则前端会把它当失效路径悄悄改用别的目录。"""
        user_data = tmp_path / "User Data"
        user_data.mkdir()
        from pathlib import Path as _P
        def boom(self):
            raise PermissionError(13, "Access is denied")
        monkeypatch.setattr(_P, "iterdir", boom)
        data = client.post(
            "/api/monitor/baidu/list-profiles",
            json={"user_data_dir": str(user_data)},
        ).json()
        assert data["profiles"] == []
        assert data["unreadable"] is True

    def test_list_profiles_empty_dir_is_not_unreadable(self, client, tmp_path):
        user_data = tmp_path / "User Data"
        user_data.mkdir()
        data = client.post(
            "/api/monitor/baidu/list-profiles",
            json={"user_data_dir": str(user_data)},
        ).json()
        assert data["profiles"] == [] and data["unreadable"] is False

    def test_copy_profile_repairs_executable_on_channel_switch(
        self, client, monkeypatch, tmp_path
    ):
        """已存的 exe 跟本次数据目录不同渠道 → 换成配套的那个。

        只在"exe 为空"时探测的话，老用户（早就存了稳定版 exe）改用 Beta 数据
        目录后会拿稳定版 Chrome 去开 Beta 的 profile，被「配置文件来自更新版本」
        拒绝，而且要到「测试启动」才暴露。
        """
        client.post(
            "/api/monitor/baidu/native-config",
            json={
                "use_native_chrome": True,
                "chrome_executable_path": "C:/PF/Google/Chrome/Application/chrome.exe",
                "chrome_user_data_dir": None,
                "chrome_profile_name": "Default",
            },
        )
        monkeypatch.setattr(
            "csm_core.config.default_config_dir", lambda: tmp_path / "cfgdir"
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda user_data_dir=None: "C:/PF/Google/Chrome Beta/Application/chrome.exe",
        )
        beta = tmp_path / "Google" / "Chrome Beta" / "User Data"
        (beta / "Default").mkdir(parents=True)
        (beta / "Default" / "Cookies").write_bytes(b"c")
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": str(beta)},
        )
        assert resp.json()["ok"] is True
        cfg = client.get("/api/monitor/baidu/native-config").json()
        assert cfg["chrome_executable_path"] == "C:/PF/Google/Chrome Beta/Application/chrome.exe"

    def test_copy_profile_keeps_matching_executable(self, client, monkeypatch, tmp_path):
        """渠道配套时不动用户已设的 exe。"""
        client.post(
            "/api/monitor/baidu/native-config",
            json={
                "use_native_chrome": True,
                "chrome_executable_path": "D:/MyChrome/chrome.exe",
                "chrome_user_data_dir": None,
                "chrome_profile_name": "Default",
            },
        )
        monkeypatch.setattr(
            "csm_core.config.default_config_dir", lambda: tmp_path / "cfgdir"
        )
        stable = tmp_path / "Google" / "Chrome" / "User Data"
        (stable / "Default").mkdir(parents=True)
        (stable / "Default" / "Cookies").write_bytes(b"c")
        client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": str(stable)},
        )
        cfg = client.get("/api/monitor/baidu/native-config").json()
        assert cfg["chrome_executable_path"] == "D:/MyChrome/chrome.exe"

    def test_native_config_normalizes_user_data_dir(self, client):
        resp = client.post(
            "/api/monitor/baidu/native-config",
            json={
                "use_native_chrome": True,
                "chrome_executable_path": None,
                "chrome_user_data_dir": '  "D:\\Chrome\\User Data"  ',
                "chrome_profile_name": "Default",
            },
        )
        assert resp.status_code == 200
        cfg = client.get("/api/monitor/baidu/native-config").json()
        assert cfg["chrome_user_data_dir"] == "D:\\Chrome\\User Data"

    def test_detect_chrome_pairs_executable_with_channel(
        self, client, monkeypatch, tmp_path
    ):
        """探测到的数据目录是哪个渠道，chrome.exe 就该配哪个渠道。"""
        seen: dict = {}
        def _fake_exe(user_data_dir=None):
            seen["user_data_dir"] = user_data_dir
            return "C:/Chrome Beta/chrome.exe"
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable", _fake_exe
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_user_data_dir",
            lambda: str(tmp_path / "Chrome Beta" / "User Data"),
        )
        data = client.post("/api/monitor/baidu/detect-chrome").json()
        assert seen["user_data_dir"] == str(tmp_path / "Chrome Beta" / "User Data")
        assert data["executable_path"] == "C:/Chrome Beta/chrome.exe"

    def test_detect_chrome_includes_profiles_and_resolved_name(
        self, client, monkeypatch, tmp_path
    ):
        """detect-chrome 要一并回 profile 列表 + 推荐项 —— 前端才画得出选择器。

        回归 bug：前端写死复制 "Default"，用户机器上没有 Default 时整条导入
        路径死掉，且 UI 里没有任何地方能改选。
        """
        user_data = tmp_path / "User Data"
        (user_data / "Profile 1").mkdir(parents=True)
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda user_data_dir=None: "C:/Chrome/chrome.exe",
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_user_data_dir",
            lambda: str(user_data),
        )
        data = client.post("/api/monitor/baidu/detect-chrome").json()
        assert [p["name"] for p in data["profiles"]] == ["Profile 1"]
        assert data["resolved_profile_name"] == "Profile 1"

    def test_list_profiles_includes_resolved_name(self, client, tmp_path):
        user_data = tmp_path / "User Data"
        (user_data / "Profile 2").mkdir(parents=True)
        resp = client.post(
            "/api/monitor/baidu/list-profiles",
            json={"user_data_dir": str(user_data)},
        )
        assert resp.json()["resolved_profile_name"] == "Profile 2"

    def test_copy_profile_auto_resolves_when_default_missing(
        self, client, monkeypatch, tmp_path
    ):
        """不传 source_profile_name（或传的那个不存在）→ 后端挑真实存在的 profile。"""
        user_data = tmp_path / "User Data"
        (user_data / "Profile 1").mkdir(parents=True)
        (user_data / "Profile 1" / "Cookies").write_bytes(b"c")
        monkeypatch.setattr(
            "csm_core.config.default_config_dir", lambda: tmp_path / "cfgdir"
        )
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": str(user_data)},
        )
        data = resp.json()
        assert data["ok"] is True, data
        assert data["profile_name"] == "Profile 1"
        # 选中的 profile 持久化，重新导入时复用
        cfg = client.get("/api/monitor/baidu/native-config").json()
        assert cfg["chrome_profile_name"] == "Profile 1"
        assert (tmp_path / "cfgdir" / "baidu_chrome_profile_copy" / "Default").is_dir()

    def test_copy_profile_error_is_actionable_when_no_profiles(
        self, client, monkeypatch, tmp_path
    ):
        """目录里一个 profile 都没有 → ok=False + 说得清下一步的中文提示。"""
        user_data = tmp_path / "User Data"
        user_data.mkdir()
        monkeypatch.setattr(
            "csm_core.config.default_config_dir", lambda: tmp_path / "cfgdir"
        )
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": str(user_data)},
        )
        data = resp.json()
        assert data["ok"] is False
        assert "启动" in data["error"]

    def test_copy_profile_empty_source_422(self, client):
        """source_user_data_dir 为空 → Pydantic 验证失败 422。"""
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": ""},
        )
        assert resp.status_code == 422

    def test_copy_profile_persists_detected_executable(self, client, monkeypatch):
        """copy-profile 成功后顺手探测并存 chrome.exe 路径，省得用户单独点'自动探测'
        （否则 chrome_executable_path 一直为空 → 后续'登录副本'/跑监控会失败）。"""
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.copy_profile_to",
            lambda **kw: {"imported_at": "2026-05-25T10:00:00", "size_mb": 1.0, "elapsed_s": 1.0},
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda user_data_dir=None: "C:/Detected/chrome.exe",
        )
        resp = client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": "C:/User Data", "source_profile_name": "Default"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        cfg = client.get("/api/monitor/baidu/native-config").json()
        assert cfg["chrome_executable_path"] == "C:/Detected/chrome.exe"

    def test_copy_profile_keeps_manually_set_executable(self, client, monkeypatch):
        """用户已手填 chrome.exe 路径时，copy-profile 不覆盖它。"""
        client.post(
            "/api/monitor/baidu/native-config",
            json={
                "use_native_chrome": True,
                "chrome_executable_path": "C:/Manual/chrome.exe",
                "chrome_user_data_dir": None,
                "chrome_profile_name": "Default",
            },
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.copy_profile_to",
            lambda **kw: {"imported_at": "2026-05-25T10:00:00", "size_mb": 1.0, "elapsed_s": 1.0},
        )
        monkeypatch.setattr(
            "csm_core.monitor.drivers.chrome_detect.find_chrome_executable",
            lambda: "C:/Detected/chrome.exe",  # 不应被采用
        )
        client.post(
            "/api/monitor/baidu/copy-profile",
            json={"source_user_data_dir": "C:/User Data", "source_profile_name": "Default"},
        )
        cfg = client.get("/api/monitor/baidu/native-config").json()
        assert cfg["chrome_executable_path"] == "C:/Manual/chrome.exe"

    def test_native_config_get_returns_current_settings(self, client):
        resp = client.get("/api/monitor/baidu/native-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "use_native_chrome" in data
        assert "chrome_executable_path" in data
        assert "chrome_user_data_dir" in data
        assert "chrome_profile_name" in data
        # B' new fields
        assert "chrome_profile_copy_path" in data
        assert "chrome_profile_copy_imported_at" in data

    def test_native_config_post_persists(self, client):
        resp = client.post(
            "/api/monitor/baidu/native-config",
            json={
                "use_native_chrome": True,
                "chrome_executable_path": "C:/x/chrome.exe",
                "chrome_user_data_dir": "C:/x/User Data",
                "chrome_profile_name": "Profile 1",
            },
        )
        assert resp.status_code == 200
        # round-trip
        resp2 = client.get("/api/monitor/baidu/native-config")
        data = resp2.json()
        assert data["use_native_chrome"] is True
        assert data["chrome_executable_path"] == "C:/x/chrome.exe"
        assert data["chrome_profile_name"] == "Profile 1"

    def test_launch_login_window_returns_error_when_copy_not_imported(self, client, monkeypatch):
        # 让 config 返回 copy_path=None
        fake_cfg = MagicMock()
        fake_cfg.monitor.baidu_keyword.chrome_profile_copy_path = None
        fake_cfg.monitor.baidu_keyword.chrome_executable_path = "C:/x/chrome.exe"
        monkeypatch.setattr(
            "csm_sidecar.routes.monitor._cfg_svc.load", lambda: fake_cfg,
        )
        resp = client.post("/api/monitor/baidu/launch-login-window")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False
        assert "导入" in data["error"]

    def test_launch_login_window_returns_error_when_no_executable(self, client, monkeypatch):
        fake_cfg = MagicMock()
        fake_cfg.monitor.baidu_keyword.chrome_profile_copy_path = "C:/x/copy"
        fake_cfg.monitor.baidu_keyword.chrome_executable_path = None
        monkeypatch.setattr(
            "csm_sidecar.routes.monitor._cfg_svc.load", lambda: fake_cfg,
        )
        resp = client.post("/api/monitor/baidu/launch-login-window")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is False

    def test_launch_login_window_spawns_subprocess(self, client, monkeypatch):
        fake_cfg = MagicMock()
        fake_cfg.monitor.baidu_keyword.chrome_profile_copy_path = "C:/x/copy"
        fake_cfg.monitor.baidu_keyword.chrome_executable_path = "C:/Chrome/chrome.exe"
        monkeypatch.setattr(
            "csm_sidecar.routes.monitor._cfg_svc.load", lambda: fake_cfg,
        )
        fake_proc = MagicMock()
        fake_proc.pid = 12345
        fake_proc.wait.return_value = 0
        captured: dict = {}
        def fake_popen(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return fake_proc
        monkeypatch.setattr("subprocess.Popen", fake_popen)
        resp = client.post("/api/monitor/baidu/launch-login-window")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["pid"] == 12345
        # 断言启动命令包含正确的 user-data-dir + URL
        args = captured["args"]
        assert args[0] == "C:/Chrome/chrome.exe"
        assert "--user-data-dir=C:/x/copy" in args
        assert "--profile-directory=Default" in args
        assert "https://www.baidu.com" in args


def test_geo_rpa_login_status_ok(client: TestClient, monkeypatch):
    import csm_core.monitor.geo.providers.rpa._session as sess
    monkeypatch.setattr(sess, "login_status", lambda p: {"logged_in": True})
    r = client.get("/api/monitor/geo/rpa/deepseek/login-status")
    assert r.status_code == 200
    assert r.json()["logged_in"] is True


def test_geo_rpa_login_status_unknown_platform_404(client: TestClient):
    r = client.get("/api/monitor/geo/rpa/nope/login-status")
    assert r.status_code == 404


def test_geo_rpa_login_status_soft_fallback(client: TestClient, monkeypatch):
    import csm_core.monitor.geo.providers.rpa._session as sess
    def _boom(p):
        raise RuntimeError("profile corrupt")
    monkeypatch.setattr(sess, "login_status", _boom)
    r = client.get("/api/monitor/geo/rpa/deepseek/login-status")
    assert r.status_code == 200 and r.json()["logged_in"] is False


def test_geo_rpa_login_open(client: TestClient, monkeypatch):
    import csm_core.monitor.geo.providers.rpa._session as sess
    monkeypatch.setattr(sess, "open_login", lambda p, **k: {"status": "success"})
    r = client.post("/api/monitor/geo/rpa/deepseek/login")
    assert r.status_code == 200 and r.json()["status"] == "success"


def test_geo_rpa_login_open_unknown_platform_404(client: TestClient):
    r = client.post("/api/monitor/geo/rpa/nope/login")
    assert r.status_code == 404
