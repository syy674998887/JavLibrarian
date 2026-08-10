"""Shared deterministic test doubles."""

import pytest

from javlibrarian import fetcher as fetcher_module
from javlibrarian.fetcher import Fetcher


class FakeResponse:
    def __init__(self, status, headers=None, text="ok", content=b"ok"):
        self.status_code = status
        self.headers = headers or {}
        self.text = text
        self.content = content


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.headers = {}
        self.cookies = type(
            "Cookies", (), {"set": staticmethod(lambda *args, **kwargs: None)}
        )()

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else FakeResponse(200)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def controlled_fetcher(monkeypatch):
    """Build a Fetcher backed by scripted responses and a controlled clock."""

    def make(script, **kwargs):
        instance = Fetcher(**kwargs)
        instance.s = FakeSession(script)
        sleeps = []
        clock = [1000.0]

        monkeypatch.setattr(fetcher_module.time, "time", lambda: clock[0])
        monkeypatch.setattr(fetcher_module.time, "monotonic", lambda: clock[0])

        def fake_sleep(seconds):
            sleeps.append(round(seconds, 2))
            clock[0] += seconds

        monkeypatch.setattr(fetcher_module.time, "sleep", fake_sleep)
        return instance, sleeps, clock

    return make
