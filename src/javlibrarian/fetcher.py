"""Serial HTTP fetching with per-host throttling and retry backoff."""

import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit(
        "Missing requests. This project manages dependencies with uv. Run:  uv sync\n"
        "Then use uv run javlibrarian ... instead of invoking Python directly."
    )


DEFAULT_PAGE_DELAY = 5.0
DEFAULT_IMAGE_DELAY = 2.0
DEFAULT_TITLE_DELAY = 10.0

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class Fetcher:
    """Rate-limit requests by host and content type, with adaptive backoff."""

    BACKOFF_START = 10.0
    BACKOFF_CAP = 300.0
    SLOWDOWN = 1.5
    DELAY_CAP = 30.0
    RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}

    def __init__(
        self,
        page_delay=DEFAULT_PAGE_DELAY,
        image_delay=DEFAULT_IMAGE_DELAY,
        verbose=False,
        title_delay=DEFAULT_TITLE_DELAY,
    ):
        self.verbose = verbose
        self.s = requests.Session()
        self.s.headers.update(
            {
                "User-Agent": UA,
                "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
                "Accept": "text/html,application/xhtml+xml,image/webp,*/*;q=0.8",
            }
        )
        self.s.cookies.set("over18", "1", domain="javdb.com")
        self._base = {"page": page_delay, "img": image_delay}
        self._delay = {}
        self._last = {}
        self._blocked_until = {}
        self.throttled = 0
        self.title_delay = title_delay
        self._movie_ended_at = None
        self._movie_active = False

    @staticmethod
    def bucket_of(url, binary):
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url or "").lower() or "?"
        return f"{host}:{'img' if binary else 'page'}"

    def _delay_of(self, bucket):
        if bucket not in self._delay:
            kind = "img" if bucket.endswith(":img") else "page"
            self._delay[bucket] = self._base[kind]
        return self._delay[bucket]

    def _wait(self, bucket):
        delay = self._delay_of(bucket)
        now = time.monotonic()
        gap = now - self._last.get(bucket, now - delay)
        wait = max(delay - gap, self._blocked_until.get(bucket, 0) - now)
        if wait > 0:
            if self.verbose:
                print(f"      · request wait {wait:.1f}s for {bucket}", flush=True)
            time.sleep(wait)
        self._last[bucket] = time.monotonic()

    def _slow_down(self, bucket):
        old = self._delay_of(bucket)
        self._delay[bucket] = min(old * self.SLOWDOWN, self.DELAY_CAP)
        if self.verbose and self._delay[bucket] > old:
            print(
                f"      · {bucket} base interval {old:.1f}s → {self._delay[bucket]:.1f}s",
                flush=True,
            )

    def begin_movie(self):
        """Apply the inter-title delay immediately before network scraping."""
        if self._movie_ended_at is not None and self.title_delay > 0:
            elapsed = time.monotonic() - self._movie_ended_at
            wait = self.title_delay - elapsed
            if wait > 0:
                if self.verbose:
                    print(f"      · inter-title wait {wait:.1f}s", flush=True)
                time.sleep(wait)
        self._movie_active = True

    def finish_movie(self):
        """Record completion only for a title that entered network scraping."""
        if self._movie_active:
            self._movie_ended_at = time.monotonic()
            self._movie_active = False

    def get(self, url, referer=None, binary=False, max_retry=5):
        """Return ``(status_code, text_or_bytes)``; failed bodies are ``None``."""
        headers = {"Referer": referer} if referer else {}
        bucket = self.bucket_of(url, binary)
        backoff = self.BACKOFF_START
        for attempt in range(max_retry):
            self._wait(bucket)
            try:
                response = self.s.get(url, headers=headers, timeout=30)
            except requests.exceptions.RequestException as error:
                if attempt == max_retry - 1:
                    return 0, None
                if self.verbose:
                    print(
                        f"      · {type(error).__name__}; retrying in {backoff:.0f}s",
                        flush=True,
                    )
                time.sleep(backoff)
                backoff = min(backoff * 2, self.BACKOFF_CAP)
                continue

            if response.status_code == 429:
                self.throttled += 1
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if (retry_after and retry_after.isdigit()) else backoff
                self._slow_down(bucket)
                if attempt == max_retry - 1:
                    deadline = time.monotonic() + wait
                    self._blocked_until[bucket] = max(
                        self._blocked_until.get(bucket, 0), deadline
                    )
                    return 429, None
                if self.verbose:
                    print(f"      · 429 rate limit; retrying in {wait:.0f}s", flush=True)
                time.sleep(wait)
                backoff = min(backoff * 2, self.BACKOFF_CAP)
                continue

            if response.status_code == 200:
                return 200, response.content if binary else response.text

            if response.status_code not in self.RETRYABLE_STATUS:
                return response.status_code, None

            if response.status_code == 503:
                self._slow_down(bucket)
            if attempt == max_retry - 1:
                return response.status_code, None
            if self.verbose:
                print(
                    f"      · HTTP {response.status_code}; retrying in {backoff:.0f}s",
                    flush=True,
                )
            time.sleep(backoff)
            backoff = min(backoff * 2, self.BACKOFF_CAP)
        return 0, None
