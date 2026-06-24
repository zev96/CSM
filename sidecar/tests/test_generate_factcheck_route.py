from pathlib import Path

from fastapi.testclient import TestClient

from csm_core.assembler.plan import AssemblyPlan
from csm_sidecar.services import factcheck_service


def test_export_route_404_when_no_pending(client: TestClient):
    factcheck_service.reset_for_test()
    r = client.post("/api/generate/ghost/export",
                    json={"final_text": "x", "released_numbers": [], "released_certs": []})
    assert r.status_code == 404


def test_export_route_exports_when_clean(client: TestClient, tmp_path: Path):
    factcheck_service.reset_for_test()
    factcheck_service.cache_pending(
        "jr", plan=AssemblyPlan(keyword="kw", template_id="t", seed=0),
        out_dir=tmp_path, keyword="kw", fmt="markdown",
        allowed_numbers={220.0}, allowed_certs=set())
    r = client.post("/api/generate/jr/export",
                    json={"final_text": "吸力220AW。", "released_numbers": [],
                          "released_certs": []})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and Path(body["document"]).exists()


def test_export_route_returns_remaining_violations(client: TestClient, tmp_path: Path):
    factcheck_service.reset_for_test()
    factcheck_service.cache_pending(
        "jv", plan=AssemblyPlan(keyword="kw", template_id="t", seed=0),
        out_dir=tmp_path, keyword="kw", fmt="markdown",
        allowed_numbers={220.0}, allowed_certs=set())
    r = client.post("/api/generate/jv/export",
                    json={"final_text": "吸力300AW。", "released_numbers": [],
                          "released_certs": []})
    assert r.status_code == 200
    assert r.json()["ok"] is False
