from fastapi.testclient import TestClient

from lazarus import api

client = TestClient(api.app)


def test_homepage_is_lazarus_site():
    r = client.get("/")
    assert r.status_code == 200
    assert "Lazarus" in r.text
    assert "bundled codec" not in r.text.lower()
    assert client.get("/scrolly.js").status_code == 200


def test_workspace_served_under_app():
    if not api.WEB_DIST.exists():
        return
    r = client.get("/app/")
    assert r.status_code == 200
    assert '<div id="root">' in r.text
    assert r.headers.get("cache-control") == "no-cache"
    assert client.get("/app/job/xyz").status_code == 200


def test_api_untouched():
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/nope").status_code == 404
