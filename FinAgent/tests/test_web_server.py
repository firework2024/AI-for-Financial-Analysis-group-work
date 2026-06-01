from pathlib import Path

from finagent.web.server import _find_output_file, _normalize_output_relative_path


def test_normalize_output_relative_path_strips_prefix():
    assert _normalize_output_relative_path("outputs/charts/foo/bar.png") == "charts/foo/bar.png"
    assert _normalize_output_relative_path("FinAgent/outputs/charts/foo/bar.png") == "charts/foo/bar.png"


def test_find_output_file_supports_nested_chart_paths():
    root = Path(__file__).resolve().parents[1]
    outputs = root / "outputs"
    chart_dir = outputs / "charts" / "_test_nested"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_file = chart_dir / "sample.png"
    chart_file.write_bytes(b"png")
    try:
        found = _find_output_file("charts/_test_nested/sample.png")
        assert found is not None
        assert found.name == "sample.png"
        fallback = _find_output_file("sample.png")
        assert fallback is not None
        assert fallback.name == "sample.png"
    finally:
        chart_file.unlink(missing_ok=True)
        chart_dir.rmdir()
        nested = outputs / "charts" / "_test_nested"
        if nested.exists() and not any(nested.iterdir()):
            nested.rmdir()


def test_chart_alias_route():
    from fastapi.testclient import TestClient

    from finagent.web.server import create_app

    root = Path(__file__).resolve().parents[1]
    outputs = root / "outputs"
    chart_dir = outputs / "charts" / "_test_alias"
    chart_dir.mkdir(parents=True, exist_ok=True)
    chart_file = chart_dir / "alias.png"
    chart_file.write_bytes(b"png")
    try:
        client = TestClient(create_app())
        auth = client.post("/api/auth/register", json={"username": "chart_user", "password": "secret12"})
        if auth.status_code != 200:
            auth = client.post("/api/auth/login", json={"username": "chart_user", "password": "secret12"})
        assert auth.status_code == 200, auth.text
        token = auth.json()["token"]
        response = client.get(
            "/charts/_test_alias/alias.png",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.content == b"png"
    finally:
        chart_file.unlink(missing_ok=True)
        chart_dir.rmdir()
