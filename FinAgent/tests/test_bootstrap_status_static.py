from pathlib import Path


SERVER_PY = Path(__file__).resolve().parents[1] / "finagent" / "web" / "server.py"


def test_bootstrap_final_status_requires_all_codes_completed():
    source = SERVER_PY.read_text(encoding="utf-8")
    assert 'final_status = "completed" if ok_count == len(codes)' in source
    assert '"status": final_status' in source
    assert '"ok": ok_count == len(codes)' in source
