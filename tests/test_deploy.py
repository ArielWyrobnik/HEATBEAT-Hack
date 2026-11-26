"""Hosted app: /api/config and the built frontend served by FastAPI (Dockerfile, render.yaml)."""
import importlib

from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path, feedback=None):
    (tmp_path / "index.html").write_text("<html>heatbeat</html>")
    (tmp_path / "app.js").write_text("console.log(1)")
    monkeypatch.setenv("HEATBEAT_STATIC", str(tmp_path))
    if feedback:
        monkeypatch.setenv("FEEDBACK_URL", feedback)
    else:
        monkeypatch.delenv("FEEDBACK_URL", raising=False)
    import heatbeat_api.app as m
    return TestClient(importlib.reload(m).app)


def test_config_feedback_url(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path, feedback="https://example.com/form")
    assert c.get("/api/config").json() == {"feedback_url": "https://example.com/form"}
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/config").json() == {"feedback_url": None}


def test_static_frontend_and_spa_fallback(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert "heatbeat" in c.get("/").text
    assert c.get("/app.js").text == "console.log(1)"
    assert "heatbeat" in c.get("/any/route").text          # SPA fallback
    assert c.get("/api/health").json()["status"] == "ok"    # API wins over the catch-all
    assert c.get("/api/does-not-exist").status_code == 404
    assert "HEATBEAT" not in c.get("/..%2fCLAUDE.md").text  # no path traversal
