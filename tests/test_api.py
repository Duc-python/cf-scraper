"""API-level tests - port of tests/validate.test.js.

No browser is launched here, mirroring SKIP_LAUNCH=true in the original.
"""
from fastapi.testclient import TestClient

from cf_scraper.app import NOT_READY, create_app

BASE = {"url": "https://nopecha.com/demo/cloudflare", "mode": "source"}


def _client(**kwargs):
    kwargs.setdefault("launch_browser", False)
    return TestClient(create_app(**kwargs))


def test_authorisation():
    with _client(auth_token="123456") as client:
        response = client.post("/cf-clearance-scraper", json=BASE)
    assert response.status_code == 401
    assert response.json() == {"code": 401, "message": "Unauthorized"}


def test_context_limit():
    with _client(limit=-1, auth_token="123456") as client:
        response = client.post(
            "/cf-clearance-scraper", json={**BASE, "authToken": "123456"}
        )
    assert response.status_code == 429
    assert response.json() == {"code": 429, "message": "Too Many Requests"}


def test_bad_request():
    with _client() as client:
        response = client.post(
            "/cf-clearance-scraper", json={"url": BASE["url"], "mode": "nope"}
        )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == 400
    assert body["message"] == "Bad Request"
    assert body["schema"]


def test_not_ready_without_browser():
    with _client() as client:
        response = client.post("/cf-clearance-scraper", json=BASE)
    assert response.status_code == 500
    assert response.json() == {"code": 500, "message": NOT_READY}


def test_not_found():
    with _client() as client:
        response = client.get("/nope")
    assert response.status_code == 404
    assert response.json() == {"code": 404, "message": "Not Found"}


def test_bad_url():
    with _client() as client:
        response = client.post(
            "/cf-clearance-scraper", json={"url": "not-a-url", "mode": "source"}
        )
    assert response.status_code == 400
    assert response.json()["code"] == 400


def test_missing_mode():
    with _client() as client:
        response = client.post(
            "/cf-clearance-scraper", json={"url": "https://example.com/"}
        )
    assert response.status_code == 400
    assert response.json()["code"] == 400


def test_extra_field_rejected():
    with _client() as client:
        response = client.post(
            "/cf-clearance-scraper",
            json={**BASE, "hacker": True},
        )
    assert response.status_code == 400
    assert response.json()["code"] == 400


def test_proxy_port_must_be_integer():
    with _client() as client:
        response = client.post(
            "/cf-clearance-scraper",
            json={**BASE, "proxy": {"host": "127.0.0.1", "port": "8080"}},
        )
    assert response.status_code == 400
    assert response.json()["code"] == 400


def test_proxy_missing_port():
    with _client() as client:
        response = client.post(
            "/cf-clearance-scraper",
            json={**BASE, "proxy": {"host": "127.0.0.1"}},
        )
    assert response.status_code == 400


def test_non_object_body():
    with _client() as client:
        response = client.post("/cf-clearance-scraper", json=["source"])
    assert response.status_code == 400
    assert response.json()["code"] == 400


def test_wrong_auth_token():
    with _client(auth_token="secret") as client:
        response = client.post(
            "/cf-clearance-scraper", json={**BASE, "authToken": "wrong"}
        )
    assert response.status_code == 401
    assert response.json() == {"code": 401, "message": "Unauthorized"}
