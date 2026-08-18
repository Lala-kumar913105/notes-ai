"""Functional tests for /fetch-article-text (run from the project root)."""
import os
import sys
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

PROJECT = "/home/freefireloverfreefirelover513/master ai/leo-assistant"
os.chdir(PROJECT)
sys.path.insert(0, PROJECT)

import app as appmod  # noqa: E402

appmod.app.config["TESTING"] = True
client = appmod.app.test_client()

results = []


def check(name, ok, extra=""):
    results.append(ok)
    print(("PASS" if ok else "FAIL"), "-", name, extra)


class ArticlePage(BaseHTTPRequestHandler):
    def do_GET(self):
        body = (
            b"<!doctype html><html><head><title>t Article &amp; Co</title>"
            b"<script>window.x=1;</script><nav>NAV LINKS</nav></head>"
            b"<body><header>HDR BANNER</header><footer>FOOTER</footer>"
            b"<article><h1>Hello World</h1><p>First para with <b>bold</b>.</p>"
            b"<p>Second paragraph here.</p></article>"
            b"<script>more()</script></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class EmptyPage(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><head><title>x</title></head>"
            b"<body><script>diggity()</script><nav>hi</nav></body></html>"
        )

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), ArticlePage)
port = server.server_address[1]
threading.Thread(target=server.serve_forever, daemon=True).start()
server2 = HTTPServer(("127.0.0.1", 0), EmptyPage)
port2 = server2.server_address[1]
threading.Thread(target=server2.serve_forever, daemon=True).start()
local_url = "http://127.0.0.1:%d/" % port
empty_url = "http://127.0.0.1:%d/" % port2

print("== bs4 available:", appmod.BeautifulSoup is not None, "==")

# 1) Real public article (Wikipedia)
r = client.post("/fetch-article-text", json={"url": "https://en.wikipedia.org/wiki/Photosynthesis"})
data = r.get_json()
check("real article -> 200", r.status_code == 200, "status=%s" % r.status_code)
check("shape type=text", data and data.get("type") == "text", str(data)[:80])
check("shape source=article", data and data.get("source") == "article")
check("filename present (title)", data and bool(data.get("filename")))
content = data["content"] if data else ""
check("content usable (>500 chars)", len(content) > 500, "chars=%d" % len(content))
check("content truncated to MAX_EXTRACTED_CHARS", len(content) <= appmod.MAX_EXTRACTED_CHARS)

# 2. Local page: boilerplate stripped + title used as filename
r = client.post("/fetch-article-text", json={"url": local_url})
data = r.get_json()
labels = str(data)[:160]
check("local page -> 200", r.status_code == 200, labels)
c = data["content"] if data else ""
check("filename = <title>", data and "t Article" in data.get("filename", ""),
      "filename=%r" % (data.get("filename") if data else None))
check("no NAV/FOOTER/HEADER text leaked",
      "NAV LINKS" not in c and "FOOTER" not in c and "HDR BANNER" not in c)
check("article text kept", "Hello World" in c and "Second paragraph" in c)

# 3) Invalid URL
r = client.post("/fetch-article-text", json={"url": "not a url 123"})
check("invalid URL -> 400", r.status_code == 400, str(r.get_json())[:100])

# 4) Non-http scheme rejected
r = client.post("/fetch-article-text", json={"url": "javascript:alert(1)"})
check("bad scheme -> 400", r.status_code == 400, str(r.get_json())[:80])

# 5) Missing URL
r = client.post("/fetch-article-text", json={})
check("empty body -> 400", r.status_code == 400, str(r.get_json())[:80])

# 6) Unreachable host (DNS failure)
r = client.post("/fetch-article-text",
                json={"url": "https://this-domain-does-not-exist-abc123456.invalid/"})
check("unreachable host -> 400", r.status_code == 400, str(r.get_json())[:120])

# 7) Non-200 status
r = client.post("/fetch-article-text", json={"url": "https://httpbin.org/status/404"})
check("404 -> 400 with clear msg", r.status_code == 400 and "404" in r.get_json().get("error", ""),
      str(r.get_json())[:120])
# 8) Timeout path (monkeypatch requests.get to raise Timeout)
orig_get = appmod.requests.get
appmod.requests.get = lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.Timeout("t"))
try:
    r = client.post("/fetch-article-text", json={"url": local_url})
    check("timeout -> 400 friendly",
          r.status_code == 400 and "timeout" in r.get_json().get("error", "").lower(),
          str(r.get_json())[:120])
finally:
    appmod.requests.get = orig_get

# 9) Connection error path
appmod.requests.get = lambda *a, **k: (_ for _ in ()).throw(requests.exceptions.ConnectionError("c"))
try:
    r = client.post("/fetch-article-text", json={"url": local_url})
    check("connection error -> 400", r.status_code == 400, str(r.get_json())[:100])
finally:
    appmod.requests.get = orig_get

# 10) Empty extracted text (script-only page -> no readable content)
r = client.post("/fetch-article-text", json={"url": empty_url})
check("empty extraction -> friendly 400",
      r.status_code == 400 and "nahi mila" in r.get_json().get("error", ""),
      str(r.get_json())[:120])

# 11) robots.txt disallow present
r = client.get("/robots.txt")
check("robots.txt lists /fetch-article-text",
      "Disallow: /fetch-article-text" in r.get_data(as_text=True))

# 12) Regex fallback path works when bs4 import fails
if appmod.BeautifulSoup is not None:
    saved = appmod.BeautifulSoup
    appmod.BeautifulSoup = None
    try:
        text, title = appmod._extract_article_content(
            "<html><title>T &amp; Co</title><nav>NAV</nav><p>Hey</p><script>x()</script></html>")
        check("regex fallback strips boilerplate", "NAV" not in text and "Hey" in text, text[:40])
        check("regex fallback title unescaped", title == "T & Co", repr(title))
    finally:
        appmod.BeautifulSoup = saved
else:
    print("bs4 not installed - regex path is the active extraction path")

server.shutdown()
server2.shutdown()

passed = sum(1 for ok in results if ok)
print("\nSUMMARY: %d/%d passed" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)