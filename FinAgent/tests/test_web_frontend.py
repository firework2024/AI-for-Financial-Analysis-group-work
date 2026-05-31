from pathlib import Path

from fastapi.testclient import TestClient

from finagent.web.server import create_app


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "finagent" / "web" / "static"


def test_index_loads_marked_before_app_js():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    marked_pos = html.find("marked.min.js")
    app_pos = html.find("/assets/app.js")
    assert marked_pos != -1 and app_pos != -1
    assert marked_pos < app_pos, "marked 须在 app.js 之前加载，否则 bootstrap 不会执行"


def test_app_js_bootstraps_and_wires_report_navigation():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "bootstrap();" in js
    assert "welcomeReportsBtn" in js
    assert 'data-sidebar === "reports"' not in js or "state.view === \"chat\") return" not in js
    assert "navigate(state.activeReportId ? \"report\" : \"report-empty\")" in js


def test_index_served_with_required_assets():
    client = TestClient(create_app())
    index = client.get("/")
    assert index.status_code == 200
    body = index.text
    assert "welcomeReportsBtn" in body
    assert "data-sidebar=\"reports\"" in body

    for asset in ("app.js", "chat.js", "auth.js", "app.css"):
        response = client.get(f"/assets/{asset}")
        assert response.status_code == 200, asset
