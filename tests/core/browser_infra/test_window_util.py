from csm_core.browser_infra import window_util


def test_offscreen_args_when_hidden():
    args = window_util.offscreen_args(True)
    assert "--window-position=-32000,-32000" in args
    assert "--disable-features=CalculateNativeWinOcclusion" in args
    assert "--disable-backgrounding-occluded-windows" in args
    assert "--disable-renderer-backgrounding" in args


def test_offscreen_args_empty_when_not_hidden():
    assert window_util.offscreen_args(False) == []


class _FakeCDP:
    def __init__(self): self.sent = []
    def send(self, method, params=None):
        self.sent.append((method, params or {}))
        if method == "Browser.getWindowForTarget":
            return {"windowId": 7}
        return {}


class _FakeCtx:
    def __init__(self, cdp): self._cdp = cdp
    def new_cdp_session(self, page): return self._cdp


class _FakePage:
    def __init__(self, cdp): self.context = _FakeCtx(cdp); self._front = 0
    def bring_to_front(self): self._front += 1
    def evaluate(self, script): return {"w": 1920, "h": 1080}


def test_surface_window_moves_onscreen():
    cdp = _FakeCDP(); page = _FakePage(cdp)
    window_util.surface_window(page)
    methods = [m for m, _ in cdp.sent]
    assert "Browser.getWindowForTarget" in methods
    setb = next(p for m, p in cdp.sent if m == "Browser.setWindowBounds")
    assert setb["windowId"] == 7
    # _FakePage 报 1920×1080；1100×800 窗 → 居中 (410, 140)
    assert setb["bounds"]["left"] == (1920 - 1100) // 2
    assert setb["bounds"]["top"] == (1080 - 800) // 2
    assert page._front == 1


def test_hide_window_moves_offscreen():
    cdp = _FakeCDP(); page = _FakePage(cdp)
    window_util.hide_window(page)
    setb = next(p for m, p in cdp.sent if m == "Browser.setWindowBounds")
    assert setb["bounds"]["left"] < -1000 and setb["bounds"]["top"] < -1000


def test_surface_window_swallows_cdp_error():
    class Boom:
        context = type("C", (), {"new_cdp_session": lambda self, p: (_ for _ in ()).throw(RuntimeError("no cdp"))})()
    window_util.surface_window(Boom())  # must not raise


def test_center_bounds_centers_window():
    left, top = window_util._center_bounds(1920, 1080, 1100, 800)
    assert left == (1920 - 1100) // 2  # 410
    assert top == (1080 - 800) // 2    # 140


def test_center_bounds_clamps_when_window_larger_than_screen():
    # 窗口比屏幕大 → 不出现负坐标
    left, top = window_util._center_bounds(800, 600, 1100, 800)
    assert left == 0
    assert top == 0
