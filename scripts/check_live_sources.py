"""Daily low-volume checks of the real JavBus and JavDB HTML adapters.

No image downloads, library scanning, NFO writes, or media renames.
"""

import os
import re
import time
from pathlib import Path

from javlibrarian.fetcher import Fetcher
from javlibrarian.sources import _same_code, fetch_javbus, fetch_javdb


class ProbeFetcher(Fetcher):
    """Record response statuses, retrying only short-lived transport errors once."""

    TRANSIENT = {0, 408, 500, 502, 503, 504}

    def __init__(self):
        super().__init__(page_delay=5.0, image_delay=0.0, title_delay=0.0)
        self.history = []

    def get(self, url, referer=None, binary=False, max_retry=5):
        for attempt in range(2):
            status, body = super().get(
                url, referer=referer, binary=binary, max_retry=1
            )
            self.history.append(f"HTTP {status} {url}")
            if status not in self.TRANSIENT or attempt:
                return status, body
            time.sleep(3)


def validate(data, source, code):
    if not data:
        return ["no matching title parsed (network block, missing title, or changed HTML)"]
    problems = []
    if data.get("source") != source:
        problems.append("unexpected source")
    if not _same_code(data.get("dvdid"), code):
        problems.append("catalog number mismatch")
    title = (data.get("title") or "").strip()
    if not title or _same_code(title, code):
        problems.append("title missing or only the catalog number")
    if not re.search(r"\d{4}[-/]\d{2}[-/]\d{2}", data.get("release") or ""):
        problems.append("release date missing or malformed")
    if not (data.get("cover") or "").startswith(("http://", "https://")):
        problems.append("cover URL missing")
    return problems


def main():
    probes = (
        ("JavBus", "javbus", fetch_javbus, os.getenv("JAVBUS_SMOKE_CODE", "SONE-035")),
        ("JavDB", "javdb", fetch_javdb, os.getenv("JAVDB_SMOKE_CODE", "SONE-035")),
    )
    summary = [
        "## Live metadata source checks", "",
        "| Source | Code | Result |", "| --- | --- | --- |",
    ]
    failed = False
    for name, source, fetch, raw_code in probes:
        code = raw_code.strip()
        fetcher = ProbeFetcher()
        try:
            problems = validate(fetch(fetcher, code), source, code)
            if problems:
                raise ValueError("; ".join(problems))
            print(f"PASS {name} ({code}): valid ID, title, date and cover", flush=True)
            result = "PASS"
        except Exception as error:
            failed = True
            result = "FAIL"
            print(f"FAIL {name} ({code}): {error}", flush=True)
            print(f"::error title={name} live source failed::{error}", flush=True)
        print("  " + "; ".join(fetcher.history or ["no HTTP requests"]), flush=True)
        summary.append(f"| {name} | {code} | {result} |")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as file:
            file.write("\n".join(summary) + "\n")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
