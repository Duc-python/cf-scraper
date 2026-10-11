# CF Clearance Scraper (Python)

Python port of [ZFC-Digital/cf-clearance-scraper](https://github.com/ZFC-Digital/cf-clearance-scraper)
(v2.1.3) — same HTTP API, same four modes, same env vars. The browser layer is
replaced: `puppeteer-real-browser` (Chromium) becomes
[invisible_playwright](https://github.com/feder-cr/invisible_playwright), an
anti-detect headless Firefox with a seeded fingerprint. Everything else —
route, request/response shapes, status codes, limits — is identical.

Created for testing and training purposes: retrieve the page source of
websites, create Cloudflare Turnstile tokens and create Cloudflare WAF sessions.

Cloudflare protection not only checks cookies in the request. It also checks
variables in the header. For this reason, it is recommended to use it with the
sample code below.

Cookies with cf in the name belong to Cloudflare. You can find out what these
cookies do and how long they are valid by
**[Clicking Here](https://developers.cloudflare.com/fundamentals/reference/policies-compliances/cloudflare-cookies/)**.

## Installation

Requires **Python 3.11+**.

```powershell
git clone https://github.com/Duc-python/cf-scraper.git
cd cf-scraper
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m invisible_playwright fetch   # one-time engine download
```

```bash
# linux / mac
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m invisible_playwright fetch
```

Run:

```bash
python -m cf_scraper            # PORT=3000 by default
```

## Create Cloudflare WAF Session

By creating a session as in the example, you can send multiple requests to the
same site without being blocked. Since sites may have TLS protection, it is
recommended to send requests with a TLS-fingerprinting client, reusing the
returned headers and cookies.

```python
import httpx

session = httpx.post("http://localhost:3000/cf-clearance-scraper", json={
    "url": "https://nopecha.com/demo/cloudflare",
    "mode": "waf-session",
    # "proxy": {"host": "127.0.0.1", "port": 3000,
    #           "username": "username", "password": "password"},
}).json()

assert session["code"] == 200
cookies = "; ".join(f"{c['name']}={c['value']}" for c in session["cookies"])
headers = {**session["headers"], "cookie": cookies}
print(headers["user-agent"])
```

## Create Turnstile Token with Little Resource Consumption

This endpoint serves a minimal Turnstile render page instead of the full site,
so no extra css/js is loaded. The `siteKey` must be sent along with the site.
If this does not work, use `turnstile-max` (full page load) below.

```python
import httpx

token = httpx.post("http://localhost:3000/cf-clearance-scraper", json={
    "url": "https://turnstile.zeroclover.io/",
    "siteKey": "0x4AAAAAAAEwzhD6pyKkgXC0",
    "mode": "turnstile-min",
}).json()

print(token)  # {"token": "...", "code": 200}
```

## Creating Turnstile Token with Full Page Load

This request goes to the page at the given url address with a real browser,
resolves the Turnstile and returns the token.

```python
import httpx

token = httpx.post("http://localhost:3000/cf-clearance-scraper", json={
    "url": "https://turnstile.zeroclover.io/",
    "mode": "turnstile-max",
}).json()

print(token)  # {"token": "...", "code": 200}
```

## Getting Page Source from a Site Protected with Cloudflare WAF

```python
import httpx

page = httpx.post("http://localhost:3000/cf-clearance-scraper", json={
    "url": "https://nopecha.com/demo/cloudflare",
    "mode": "source",
}).json()

print(page["source"][:200])
```

## Configuration

| Variable      | Default | Meaning                                                     |
|---------------|---------|-------------------------------------------------------------|
| `PORT`        | `3000`  | HTTP port                                                   |
| `browserLimit`| `20`    | max concurrent browser contexts (else HTTP 429)             |
| `timeOut`     | `60000` | per-request timeout in ms (else "Timeout Error")            |
| `authToken`   | —       | when set, requests need a matching `authToken` (else 401)   |
| `headless`    | `true`  | hidden virtual display, headed rendering pipeline          |
| `SEED`        | —       | fixed fingerprint seed (reproducible runs)                  |
| `QUIET_CANVAS`| `true`  | disable canvas pixel substitution (matches real Firefox)    |
| `SKIP_LAUNCH` | `false` | `true` = serve the API without launching the browser        |

## API

`POST /cf-clearance-scraper` with JSON body:

```jsonc
{
  "mode": "source | turnstile-min | turnstile-max | waf-session",
  "url": "https://...",
  "proxy": {"host": "...", "port": 8080, "username": "...", "password": "..."},
  "siteKey": "0x4AAAA...",
  "authToken": "..."
}
```

Responses mirror the original: `{source, code: 200}`, `{token, code: 200}`,
`{cookies, headers, code: 200}`, errors as `{code, message}` with HTTP
400 / 401 / 404 / 429 / 500.

## Tests

```bash
pytest tests/test_api.py -v        # no browser needed
CF_LIVE=1 pytest tests/test_live.py -v   # launches the engine, uses network
CF_WIDGET=1 pytest tests/test_widget.py -v  # localhost Turnstile pages, no third party
```

Verified end to end against real server processes:

- concurrency (`browserLimit=1`, 3 parallel): exactly `1x200 + 2x429`
- plain pages: no solve delay (race between the 200/302 gate and the solver)
- `timeOut` overflow: `500 "Timeout Error"`
- dead proxy: fast `500 "Navigation failed: Problem loading page"`, server stays up
- proxy chain: local CONNECT proxy logs the browser's `CONNECT`, job returns 200
- `source` + `waf-session` live vs `nopecha.com/demo/cloudflare`, real `cf_clearance`
- turnstile min/max vs localhost with Cloudflare test sitekeys (always-pass and
  forced-challenge, the latter proving the checkbox click path)

`test_live.py` mirrors the original repo's tests byte-for-byte (same demo
URLs). Note: `turnstile.zeroclover.io` returned Cloudflare 502 Host Error
when this port was verified (origin server dead, not a bot block) — the
min/max flows were instead verified locally against `127.0.0.1` pages using
Cloudflare's documented test sitekeys (`1x00000000000000000000AA`
always-pass, `3x00000000000000000000FF` force-challenge, the latter proving
the checkbox click path end to end). `source` and `waf-session` pass live
against `nopecha.com/demo/cloudflare`, including a real `cf_clearance`
cookie.

## Quick Questions and Answers

### Does It Open A New Browser On Every Request?

No, a new context is started with each request and closed when the job is
finished. Jobs run in isolated contexts through a single browser — same as
the original.

### How Do I Limit the Browser Context to Open?

Set the `browserLimit` variable. The default is 20.

### How Do I Add Authentication to Api?

Set the `authToken` variable. Requests whose body `authToken` does not match
get HTTP 401.

### How Do I Set The Timeout Time?

Set the `timeOut` variable in milliseconds. The default is 60000.

## What changed vs the Node original

- Browser: `puppeteer-real-browser` → `invisible_playwright` (async API),
  one shared Firefox engine, one context per request.
- Proxy: same `{host, port, username, password}` shape, mapped to the
  engine's proxy config.
- Canvas: pixel substitution is off by default (`QUIET_CANVAS=true`) so
  readback matches a real Firefox; set `QUIET_CANVAS=false` for stock
  behaviour.
- `src/data/fakePage.html` is reused byte-for-byte for `turnstile-min`.

## Disclaimer of Liability

This repository was created purely for testing and training purposes. The user
is responsible for any prohibited liability that may arise from its use. The
library is not intended to harm any site or company. The user is responsible
for any damage that may arise. Users of this repository are deemed to have
accepted this disclaimer. Only use it on sites you own or are permitted to
test.
