# JavLibrarian

A lightweight, safety-first NAS media library builder for organizing JAV collections and generating local metadata and artwork.

**English** · [简体中文](README.zh-CN.md)

JavLibrarian scans a one-title-per-folder library, normalizes catalog numbers in memory, combines metadata from JavBus and JavDB, and writes media-server-friendly NFO and artwork files. Its primary target is the UGREEN UGOS media center, with folder-level compatibility for Emby, Jellyfin, and Kodi.

The project deliberately favors predictable behavior over throughput: scraping is serial, request pacing is conservative, completed folders are skipped, and destructive file operations are never part of the scraping path.

## Highlights

- Queries JavBus and JavDB for every title and merges their complementary metadata.
- Generates both `movie.nfo` and one same-name NFO for each recognized video file.
- Downloads `fanart.jpg`, builds `poster.jpg`, and stores sample images under `Samples/`.
- Preserves semantic filename suffixes such as `-C`, `-U`, and `-UC` as NFO tags.
- Validates page-reported catalog numbers before accepting metadata.
- Provides separate, preview-first workflows for folder and video renaming.
- Records every applied rename immediately in a root-bound rollback journal.
- Uses per-host, per-request-type throttling with bounded retry and backoff.
- Writes `movie.nfo` last and atomically, making it a reliable completion marker.

## Safety model

| Operation | Default behavior |
| --- | --- |
| Scraping | Adds or replaces metadata and artwork; never deletes or modifies video bytes |
| Existing `movie.nfo` | Skips the entire folder before network, image-tool, or movie-delay work |
| Forced refresh | Requires the explicit `--force` option |
| Folder renaming | Preview only unless `--apply` is also supplied |
| Video renaming | Preview only; duplicate sources and unrelated files are reported, not modified |
| Rollback | Validates that the journal belongs to the selected media root |
| Interrupted image/NFO work | Does not commit `movie.nfo`; the next run can retry |
| Rename journal writes | Persisted atomically after every successful rename |

Always review a dry run and rename preview before operating on an important library. A filesystem or NAS snapshot remains the best protection against hardware failure and mistakes outside this tool.

## Requirements

| Requirement | Details |
| --- | --- |
| Python | 3.9 or newer |
| Project runner | `uv` |
| Direct Python dependency | `requests>=2.32.5`, installed from `pyproject.toml` and `uv.lock` |
| Image processing | macOS `sips`; use `--no-images` when it is unavailable |
| Network access | JavBus, JavDB, and their referenced image hosts |

Image generation is macOS-specific because JavLibrarian intentionally uses the system-provided `sips` tool instead of adding Pillow. Metadata-only operation does not require `sips`.

## Installation

After cloning or downloading the repository:

```bash
cd JavLibrarian
uv sync
uv run javlibrarian.py --help
```

Run the script through `uv run` so that the locked project environment is used. The script intentionally does not include PEP 723 inline metadata.

## Expected library layout

The media root should contain one immediate subdirectory per title:

```text
/path/to/JAV/
├── SONE-035/
│   └── SONE-035.mp4
├── IPVR-256-C/
│   └── IPVR-256-C.mkv
└── FC2-PPV-1234567/
    └── FC2-PPV-1234567.mp4
```

Supported video extensions:

```text
.mp4  .mkv  .avi  .wmv  .mov  .m4v  .ts  .iso  .rmvb  .flv
```

Hidden directories are ignored. Catalog-number cleanup is performed in memory during scraping; folder names are changed only through the explicit rename workflow.

## Quick start

First inspect catalog-number recognition without network or disk writes:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --dry-run
```

Then process a small sample:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --limit 5
```

Process the complete library:

```bash
uv run javlibrarian.py --dir "/path/to/JAV"
```

Process selected folders only:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" \
  --only "SONE-035" \
  --only "IPVR-256-C"
```

Generate NFO files without downloading or processing images:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --no-images
```

### Default media directory

`--dir` takes precedence. For repeated commands, set `JAVLIBRARIAN_DIR`:

```bash
export JAVLIBRARIAN_DIR="/path/to/JAV"
uv run javlibrarian.py --dry-run
uv run javlibrarian.py
```

An exported environment variable lasts for the current shell and its child processes. Add it to the appropriate shell startup file only if a persistent shell default is desired.

## Generated files

For a successfully processed folder:

```text
SONE-035/
├── SONE-035.mp4
├── SONE-035.nfo
├── movie.nfo
├── fanart.jpg
├── poster.jpg
└── Samples/
    ├── sample1.jpg
    └── ...
```

- `{video-name}.nfo` supports media centers that require a sidecar matching the video filename, including UGOS.
- `movie.nfo` supports folder-level readers such as Emby, Jellyfin, and Kodi.
- `fanart.jpg` is the landscape cover.
- `poster.jpg` is the portrait poster. Standard titles are cropped from the front-cover area; VR titles first look for a dedicated portrait asset among the samples.
- `Samples/` contains valid sample images, with all samples downloaded by default.

The NFO includes the catalog number, display and original titles, release date and year, runtime, studio, label, director, series, genres, semantic tags, actors, artwork references, source attribution, and original folder name when available.

`movie.nfo` is written atomically after all requested image work and video-sidecar NFO writes complete. If it already exists, the folder is skipped immediately unless `--force` is supplied.

## Request policy

Defaults can be overridden from the command line:

| Scope | Default | Notes |
| --- | ---: | --- |
| HTML requests | 5 seconds | Tracked independently per host |
| Image requests | 2 seconds | Separate bucket from HTML requests |
| Scraped titles | 10 seconds | Measured between titles that actually entered network scraping |

The first scraped title does not wait. Local skips do not wait and do not reset the movie timer. The final title does not incur an unnecessary trailing delay.

HTTP 408, 429, 500, 502, 503, and 504 responses are retryable, with at most five attempts. Backoff starts at 10 seconds, doubles, and is capped at 300 seconds. A 429 response—and a 503 response where appropriate—slows the affected host/type bucket by 1.5× for the rest of the run, capped at a 30-second base interval. Permanent client errors return immediately.

## Folder and video renaming

Folder and video workflows are intentionally separate and preview-first.

Preview normalized folder names:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --rename-folders
```

Apply the reviewed folder plan:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --rename-folders --apply
```

Preview and apply safe video cleanup:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --rename-videos
uv run javlibrarian.py --dir "/path/to/JAV" --rename-videos --apply
```

Rollback the most recent batch:

```bash
uv run javlibrarian.py --dir "/path/to/JAV" --undo-folders
uv run javlibrarian.py --dir "/path/to/JAV" --undo-videos
```

Add `--undo-all` to the relevant undo command to process every recorded batch.

Default journals:

| Workflow | Journal |
| --- | --- |
| Folder rename | `folder_rename_log.json` |
| Video rename | `video_rename_log.json` |

The journals are stored beside the script by default, contain local paths and media filenames, and are excluded by `.gitignore`. Keep them for as long as rollback may be needed. Use `--folder-log` or `--video-log` to select a different path.

## Command reference

| Option | Purpose |
| --- | --- |
| `--dir PATH` | Media root; overrides `JAVLIBRARIAN_DIR` |
| `--dry-run` | Parse folder names only; no network and no writes |
| `--limit N` | Process only the first N selected folders |
| `--only NAME` | Select an exact folder name; repeatable |
| `--delay SECONDS` | HTML request interval; default 5.0 |
| `--img-delay SECONDS` | Image request interval; default 2.0 |
| `--movie-delay SECONDS` | Interval between network-scraped titles; default 10.0 |
| `--force` | Process folders with an existing `movie.nfo` and replace existing NFO output |
| `--no-images` | Generate NFO files without image work |
| `--max-samples N` | Maximum samples per title; 0 means all |
| `-v`, `--verbose` | Show throttling and wait details |
| `--rename-folders` | Preview folder normalization |
| `--rename-videos` | Preview safe video filename cleanup |
| `--apply` | Apply the selected rename preview |
| `--undo-folders` | Roll back the latest folder-rename batch |
| `--undo-videos` | Roll back the latest video-rename batch |
| `--undo-all` | Roll back all batches for the selected undo workflow |
| `--folder-log PATH` | Override the folder-rename journal path |
| `--video-log PATH` | Override the video-rename journal path |

## Metadata sources

JavLibrarian queries both sources rather than treating one as a fallback:

- **JavBus** supplies the primary metadata structure, release-era actor names and thumbnails, and stable cover information.
- **JavDB** supplements titles, series, genres, and assets that may be missing from JavBus.

Search results are not trusted by position. The catalog number reported by the detail page must match the normalized local catalog number before a result is accepted.

Websites can change their HTML without notice. Parser failures are reported per folder and do not trigger destructive cleanup.

## Testing

Run the existing offline test suite:

```bash
uv run test_throttle.py
```

The suite uses fake HTTP sessions, a fake clock, and system temporary directories. It does not contact the live metadata sites. It covers retry behavior, request buckets, movie spacing, source fallback, atomic image/NFO handling, rollback convergence, and the fast `movie.nfo` skip path.

## Privacy and operational notes

- Rename journals contain local filesystem paths and media filenames. They are ignored by Git but should still be handled as private data.
- JavLibrarian does not require account credentials.
- Scraping sends catalog-number requests to the configured public metadata sources and downloads referenced images unless `--no-images` is used.
- No metadata cache is retained; a forced refresh fetches current source data again.
- Respect applicable laws, source-site terms, and network policies. Use the project only with media you are authorized to manage.

## Known limitations

- Image processing depends on macOS `sips`.
- Metadata extraction depends on the current HTML structure of JavBus and JavDB.
- Requests are serial and intentionally conservative; large libraries take time.
- The scanner expects one title per immediate child directory.
- Duplicate video sources and unrelated files require human review and are never resolved automatically.
- The project is a command-line tool; it does not include a scheduler, daemon, or graphical interface.

## License

Licensed under the [Apache License 2.0](LICENSE).
