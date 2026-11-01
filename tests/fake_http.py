"""Minimal stand-in for requests.Session that routes calls to handler functions."""

import json as _json


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None, content=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = content if content is not None else _json.dumps(body or {}).encode()
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        return self._body if self._body is not None else _json.loads(self.content)


class FakeSession:
    def __init__(self):
        self.routes = []
        self.calls = []

    def route(self, method, prefix, handler):
        self.routes.append((method, prefix, handler))

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for m, prefix, handler in self.routes:
            if m == method and url.startswith(prefix):
                return handler(url=url, **kw)
        raise AssertionError(f"unexpected {method} {url}")

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def put(self, url, **kw):
        return self.request("PUT", url, **kw)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)
