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


def test_surface_window_moves_onscreen():
    cdp = _FakeCDP(); page = _FakePage(cdp)
    window_util.surface_window(page)
    methods = [m for m, _ in cdp.sent]
    assert "Browser.getWindowForTarget" in methods
    setb = next(p for m, p in cdp.sent if m == "Browser.setWindowBounds")
    assert setb["windowId"] == 7
    assert setb["bounds"]["left"] >= 0 and setb["bounds"]["top"] >= 0
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
