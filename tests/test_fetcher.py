import io
from contextlib import redirect_stdout

import pytest
import requests

from javlibrarian.fetcher import Fetcher


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}
        self.text = "ok"
        self.content = b"ok"


def test_repeated_429_exhaustion_sets_cooldown(controlled_fetcher):
    fetcher, sleeps, _ = controlled_fetcher([FakeResponse(429)] * 5)

    assert fetcher.get("http://x.com/a") == (429, None)
    assert sleeps == [10.0, 20.0, 40.0, 80.0]
    assert fetcher.throttled == 5
    assert fetcher._delay_of("x.com:page") == 30.0
    assert fetcher.s.calls == 5

    before = list(sleeps)
    fetcher.get("http://y.com/a")
    assert sleeps == before
    fetcher.get("http://x.com/a")
    assert sleeps == before + [160.0]


def test_retry_after_precedes_exponential_backoff(controlled_fetcher):
    fetcher, sleeps, _ = controlled_fetcher(
        [FakeResponse(429, {"Retry-After": "8"}), FakeResponse(200)]
    )

    status, _ = fetcher.get("http://x.com/a")

    assert status == 200
    assert sleeps == [8.0]


def test_backoff_is_capped_and_skips_sleep_after_final_attempt(controlled_fetcher):
    fetcher, sleeps, _ = controlled_fetcher([FakeResponse(429)] * 10)

    fetcher.get("http://x.com/a", max_retry=10)

    assert sleeps == [10.0, 20.0, 40.0, 80.0, 160.0, 300.0, 300.0, 300.0, 300.0]


def test_503_retries_and_slows_down(controlled_fetcher):
    fetcher, _, _ = controlled_fetcher([FakeResponse(503), FakeResponse(200)])

    status, _ = fetcher.get("http://x.com/a")

    assert status == 200
    assert fetcher.throttled == 0
    assert fetcher._delay_of("x.com:page") == 7.5


@pytest.mark.parametrize("status", [400, 403, 404])
def test_permanent_client_errors_return_without_retry(controlled_fetcher, status):
    fetcher, sleeps, _ = controlled_fetcher(
        [FakeResponse(status), FakeResponse(200)]
    )

    assert fetcher.get("http://x.com/a") == (status, None)
    assert fetcher.s.calls == 1
    assert sleeps == []


def test_network_exceptions_back_off_without_adaptive_slowdown(controlled_fetcher):
    fetcher, sleeps, _ = controlled_fetcher(
        [
            requests.ConnectionError("boom"),
            requests.Timeout("slow"),
            FakeResponse(200),
        ]
    )

    status, _ = fetcher.get("http://x.com/a")

    assert status == 200
    assert sleeps == [10.0, 20.0]
    assert fetcher._delay_of("x.com:page") == 5.0


def test_programming_errors_are_not_retried(controlled_fetcher):
    fetcher, _, _ = controlled_fetcher([ValueError("programming error")])

    with pytest.raises(ValueError):
        fetcher.get("http://x.com/a")


def test_verbose_output_reports_wait_slowdown_and_retry(controlled_fetcher):
    fetcher, _, _ = controlled_fetcher(
        [FakeResponse(200), FakeResponse(200)], verbose=True
    )
    output = io.StringIO()
    with redirect_stdout(output):
        fetcher.get("http://x.com/first")
        fetcher.get("http://x.com/second")
    assert "request wait 5.0s for x.com:page" in output.getvalue()

    fetcher, _, _ = controlled_fetcher(
        [FakeResponse(503), FakeResponse(200)], verbose=True
    )
    output = io.StringIO()
    with redirect_stdout(output):
        fetcher.get("http://x.com/retry")
    assert "base interval 5.0s → 7.5s" in output.getvalue()
    assert "HTTP 503; retrying in 10s" in output.getvalue()


def test_image_and_page_buckets_are_independent(controlled_fetcher):
    fetcher, _, _ = controlled_fetcher([FakeResponse(429), FakeResponse(200)])

    fetcher.get("http://x.com/a", binary=True)

    assert fetcher._delay["x.com:img"] == 3.0
    assert fetcher._delay_of("x.com:page") == 5.0


def test_retryable_server_error_returns_actual_status(controlled_fetcher):
    fetcher, _, _ = controlled_fetcher([FakeResponse(500)] * 5)

    assert fetcher.get("http://x.com/a") == (500, None)
    assert fetcher._delay_of("x.com:page") == 5.0


def test_host_buckets_are_independent(controlled_fetcher):
    fetcher, _, _ = controlled_fetcher(
        [FakeResponse(429), FakeResponse(200), FakeResponse(200)]
    )

    fetcher.get("https://javdb.com/v/x")
    fetcher.get("https://www.javbus.com/CODE")

    assert fetcher._delay_of("javdb.com:page") == 7.5
    assert fetcher._delay_of("www.javbus.com:page") == 5.0
    assert (
        Fetcher.bucket_of("https://pics.dmm.co.jp/a/b.jpg", True)
        == "pics.dmm.co.jp:img"
    )


def test_inter_title_wait_ignores_local_skips(controlled_fetcher):
    fetcher, sleeps, clock = controlled_fetcher([])

    fetcher.begin_movie()
    assert sleeps == []
    fetcher.finish_movie()

    clock[0] += 4
    fetcher.begin_movie()
    assert sleeps == [6.0]
    fetcher.finish_movie()

    clock[0] += 3
    sleeps.clear()
    fetcher.finish_movie()
    clock[0] += 2
    fetcher.begin_movie()
    assert sleeps == [5.0]
