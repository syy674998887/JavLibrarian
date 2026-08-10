"""Metadata inspection and scraping workflows."""

import shutil
import tempfile
import time
from pathlib import Path

from .artwork import (
    SAMPLES_DIR,
    download_with_alt,
    is_vr,
    make_poster,
    pick_sample_poster,
    ps_reference_url,
)
from .catalog import VIDEO_EXT, normalize
from .filesystem import atomic_write_bytes
from .nfo import build_nfo
from .sources import fetch_javbus, fetch_javdb, merge_sources


def do_inspect(folders):
    """Print parsed catalog numbers and tags without network or filesystem writes."""
    print(f"\n{'Original folder':<44} {'Query ID':<16} Tags")
    print("─" * 92)
    recognized = unrecognized = 0
    for folder in folders:
        code, tags = normalize(folder.name)
        if code:
            recognized += 1
        else:
            unrecognized += 1
        mark = "✅" if code else "❌"
        print(
            f"{folder.name[:43]:<44} {str(code):<16} "
            f"{'/'.join(tags) or '—'}  {mark}"
        )
    print("─" * 92)
    print(
        f"Recognized {recognized} / Unrecognized {unrecognized} / Total {len(folders)}"
    )
    print("\n[inspect] No network requests or file writes were performed.")


def scrape_one(folder, fetcher, args):
    """Scrape and atomically commit metadata for one title folder."""
    code, tags = normalize(folder.name)
    if not code:
        return "SKIP", "Catalog number not recognized"

    nfo_path = folder / "movie.nfo"
    if nfo_path.exists() and not args.force:
        return "SKIP", "movie.nfo exists; skipped (--force to override)"

    fetcher.begin_movie()

    videos = sorted(
        [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_EXT
        ],
        key=lambda path: path.name,
    )

    bus = fetch_javbus(fetcher, code)
    db = fetch_javdb(fetcher, code)
    data = merge_sources(bus, db)

    if not data:
        return "MISS", f"{code} was not found in either metadata source"

    source_tag = "+".join(
        source for source, found in (("javbus", bus), ("javdb", db)) if found
    )
    data["source"] = source_tag
    payload = build_nfo(data, tags, folder.name)

    images = []
    samples = data.get("samples", [])
    alternate_samples = data.get("samples_alt", [])
    fanart = folder / "fanart.jpg"
    poster = folder / "poster.jpg"

    has_fanart = download_with_alt(
        fetcher, data.get("cover"), data.get("cover_alt"), fanart
    )
    if has_fanart:
        images.append("fanart")

    if is_vr(data, code):
        temporary = Path(tempfile.mkdtemp(prefix="jav_"))
        try:
            downloaded = []
            for index, sample in enumerate(samples, 1):
                path = temporary / f"s{index:02d}.jpg"
                alternate = (
                    alternate_samples[index - 1]
                    if index <= len(alternate_samples)
                    else None
                )
                if download_with_alt(fetcher, sample, alternate, path):
                    downloaded.append(path)

            selected, note = pick_sample_poster(
                fetcher,
                downloaded,
                ps_reference_url(samples, code=code),
                temporary,
            )
            if selected:
                atomic_write_bytes(poster, selected.read_bytes())
                downloaded.remove(selected)
                images.append(f"poster(sample: {note})")
            elif has_fanart and make_poster(fanart, poster):
                images.append(f"poster(crop: {note})")

            if downloaded:
                sample_directory = folder / SAMPLES_DIR
                sample_directory.mkdir(exist_ok=True)
                for index, path in enumerate(downloaded, 1):
                    atomic_write_bytes(
                        sample_directory / f"sample{index}.jpg", path.read_bytes()
                    )
                images.append(f"samples×{len(downloaded)}")
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    else:
        if has_fanart and make_poster(fanart, poster):
            images.append("poster(crop)")
        if samples:
            sample_directory = folder / SAMPLES_DIR
            sample_directory.mkdir(exist_ok=True)
            downloaded_count = 0
            for index, sample in enumerate(samples, 1):
                alternate = (
                    alternate_samples[index - 1]
                    if index <= len(alternate_samples)
                    else None
                )
                if download_with_alt(
                    fetcher,
                    sample,
                    alternate,
                    sample_directory / f"sample{index}.jpg",
                ):
                    downloaded_count += 1
            if downloaded_count:
                images.append(f"samples×{downloaded_count}")

    nfo_count = 1
    for video in videos:
        sidecar = video.with_suffix(".nfo")
        if sidecar == nfo_path:
            continue
        if sidecar.exists() and not args.force:
            continue
        atomic_write_bytes(sidecar, payload)
        nfo_count += 1
    atomic_write_bytes(nfo_path, payload)

    detail = f"{code} [{source_tag}] nfo×{nfo_count}"
    if tags:
        detail += f" tags:{'/'.join(tags)}"
    if images:
        detail += f" images:{','.join(images)}"
    return "OK", detail


def do_scrape(folders, fetcher, args):
    """Run serial scraping and print an aggregate result summary."""
    print(
        f"Intervals: pages {args.page_delay}s / images {args.image_delay}s / "
        f"titles {args.delay}s   Force: {'yes' if args.force else 'no'}"
    )
    print("─" * 92)

    stats = {"OK": 0, "SKIP": 0, "MISS": 0}
    misses = []
    started_at = time.time()

    for index, folder in enumerate(folders, 1):
        try:
            status, message = scrape_one(folder, fetcher, args)
        except KeyboardInterrupt:
            print(
                "\nInterrupted. A rerun will skip completed titles that already have movie.nfo."
            )
            break
        except Exception as error:
            status, message = "MISS", f"Error {type(error).__name__}: {error}"
        finally:
            fetcher.finish_movie()
        stats[status] = stats.get(status, 0) + 1
        if status == "MISS":
            misses.append((folder.name, message))
        icon = {"OK": "✅", "SKIP": "⏭ ", "MISS": "❌"}[status]
        print(
            f"[{index:3}/{len(folders)}] {icon} {folder.name[:40]:<42} {message}",
            flush=True,
        )

    elapsed = time.time() - started_at
    print("─" * 92)
    print(
        f"Complete: succeeded {stats['OK']}  skipped {stats['SKIP']}  "
        f"failed {stats['MISS']}   elapsed {elapsed / 60:.1f} min"
    )
    if fetcher.throttled:
        slowed = {
            bucket: delay
            for bucket, delay in fetcher._delay.items()
            if delay
            > fetcher._base["img" if bucket.endswith(":img") else "page"]
        }
        print(
            f"Rate limiting: HTTP 429 occurred {fetcher.throttled} time(s)"
            + (
                "; slowed "
                + ", ".join(
                    f"{bucket} → {delay:.1f}s" for bucket, delay in slowed.items()
                )
                if slowed
                else ""
            )
        )
    if misses:
        print("\nUnmatched titles (manual review may be needed):")
        for name, message in misses:
            print(f"  · {name:<44} {message}")
