"""End-to-end tests - port of tests/endpoints.test.js.

Hits the same public demo pages as the original. Needs network and the
anti-detect engine. Run with:  CF_LIVE=1 pytest tests/test_live.py -v
"""
import os

import pytest
from fastapi.testclient import TestClient

from cf_scraper.app import create_app

LIVE = os.getenv("CF_LIVE") == "1"

pytestmark = pytest.mark.skipif(not LIVE, reason="needs CF_LIVE=1 (network + engine)")


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(headless=True)) as client:
        yield client


def test_source(client):
    response = client.post(
        "/cf-clearance-scraper",
        json={"url": "https://nopecha.com/demo/cloudflare", "mode": "source"},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200
    assert "<html" in response.json()["source"].lower()


def test_turnstile_min(client):
    response = client.post(
        "/cf-clearance-scraper",
        json={
            "url": "https://turnstile.zeroclover.io/",
            "siteKey": "0x4AAAAAAAEwzhD6pyKkgXC0",
            "mode": "turnstile-min",
        },
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200
    assert len(response.json()["token"]) >= 10


def test_turnstile_max(client):
    response = client.post(
        "/cf-clearance-scraper",
        json={"url": "https://turnstile.zeroclover.io/", "mode": "turnstile-max"},
    )
    assert response.status_code == 200
    assert response.json()["code"] == 200
    assert len(response.json()["token"]) >= 10


def test_waf_session(client):
    response = client.post(
        "/cf-clearance-scraper",
        json={"url": "https://nopecha.com/demo/cloudflare", "mode": "waf-session"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 200
    assert isinstance(body["cookies"], list)
    assert isinstance(body["headers"], dict)
    assert any(cookie["name"] == "cf_clearance" for cookie in body["cookies"])
