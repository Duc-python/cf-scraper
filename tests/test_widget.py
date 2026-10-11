"""Widget tests against localhost - no third-party demo site needed.

Serves explicit Turnstile pages using Cloudflare's documented TEST sitekeys,
then runs the real min/max jobs through the API.

These sitekeys do not produce usable tokens: Cloudflare answers
`XXXX.DUMMY.TOKEN.XXXX`, 21 characters, every time - that is their documented
behaviour for `1x...` and `3x...`. So the expectation here is a 500 carrying
the explanation, not a 200. An earlier version of this file asserted the
opposite, which is how a placeholder token kept passing as a success.

Real-token behaviour is covered separately against a production-style sitekey
(see README, "Turnstile token capture").

Needs the engine and network access to challenges.cloudflare.com.
Run with:  CF_WIDGET=1 pytest tests/test_widget.py -v
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from cf_scraper.app import create_app

LIVE = os.getenv("CF_WIDGET") == "1"

pytestmark = pytest.mark.skipif(not LIVE, reason="needs CF_WIDGET=1 (engine + network)")

ALWAYS_PASS = "1x00000000000000000000AA"
FORCE_CHALLENGE = "3x00000000000000000000FF"

PAGE = """<!doctype html><html><body>
<div class="turnstile"></div>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js?onload=cb" defer></script>
<script>window.cb = function () {
  turnstile.render('.turnstile', { sitekey: '%s', callback: function (t) {
    var c = document.createElement('input'); c.type = 'hidden';
    c.name = 'cf-response'; c.value = t; document.body.appendChild(c); } });
};</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        key = FORCE_CHALLENGE if self.path.startswith("/challenge") else ALWAYS_PASS
        body = (PAGE % key).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def origin():
    server = HTTPServer(("127.0.0.1", 8901), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:8901"
    server.shutdown()


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(headless=True)) as client:
        yield client


def assert_placeholder_rejected(response):
    """The widget rendered and answered; the answer is a placeholder."""
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == 500
    assert "placeholder" in body["message"]
    assert "test keys" in body["message"]


def test_max_always_pass(client, origin):
    """Renders and answers; the answer is a placeholder and must be refused."""
    response = client.post(
        "/cf-clearance-scraper",
        json={"url": f"{origin}/pass", "mode": "turnstile-max"},
    )
    assert_placeholder_rejected(response)


def test_max_forced_challenge(client, origin):
    """Forced-challenge key: the click path runs, the answer is still a placeholder."""
    response = client.post(
        "/cf-clearance-scraper",
        json={"url": f"{origin}/challenge", "mode": "turnstile-max"},
    )
    assert_placeholder_rejected(response)


def test_min_fake_page(client, origin):
    response = client.post(
        "/cf-clearance-scraper",
        json={"url": f"{origin}/anything", "siteKey": ALWAYS_PASS, "mode": "turnstile-min"},
    )
    assert_placeholder_rejected(response)
