"""Command-line interface for JavLibrarian."""

import argparse
import math
import os
import sys
from pathlib import Path

from .catalog import list_folders
from .fetcher import (
    DEFAULT_IMAGE_DELAY,
    DEFAULT_PAGE_DELAY,
    DEFAULT_TITLE_DELAY,
    Fetcher,
)
from .rename import (
    do_rename_folders,
    do_rename_videos,
    do_undo_folders,
    do_undo_videos,
)
from .scrape import do_inspect, do_scrape


DIR_ENV = "JAVLIBRARIAN_DIR"


def non_negative_int(value):
    """Argparse type for counts where zero means unlimited."""
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


def non_negative_float(value):
    """Argparse type for finite delays where zero disables the wait."""
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite number 0 or greater")
    return number


def build_parser():
    parser = argparse.ArgumentParser(
        description="JavLibrarian — JAV NAS media library builder "
        "(UGOS / Emby / Jellyfin / Kodi)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
        epilog="Run 'javlibrarian COMMAND --help' for command-specific options.",
    )
    commands = parser.add_subparsers(
        dest="command", metavar="COMMAND", required=True, title="commands"
    )

    def command(name, help_text, description=None):
        return commands.add_parser(
            name,
            help=help_text,
            description=description or help_text,
            allow_abbrev=False,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )

    def add_root(command_parser):
        command_parser.add_argument(
            "--dir",
            metavar="PATH",
            default=os.environ.get(DIR_ENV),
            help=f"media-library root (overrides {DIR_ENV})",
        )

    def add_selection(command_parser):
        command_parser.add_argument(
            "--limit",
            metavar="N",
            type=non_negative_int,
            default=0,
            help="process at most the first N folders after --only filtering "
            "(default 0 = all)",
        )
        command_parser.add_argument(
            "--only",
            metavar="NAME",
            action="append",
            default=[],
            help="select an exact, case-sensitive folder name (repeatable)",
        )

    def add_journal(command_parser, filename):
        command_parser.add_argument(
            "--journal",
            metavar="PATH",
            default=filename,
            help=f"rollback journal (default {filename}; reuse the same path for undo)",
        )

    scrape = command("scrape", "fetch metadata and write NFO/artwork")
    add_root(scrape)
    add_selection(scrape)
    scrape.add_argument(
        "--force",
        action="store_true",
        help="re-scrape folders with movie.nfo and replace same-named generated files "
        "without touching video bytes",
    )
    scrape.add_argument(
        "--page-delay",
        metavar="SECONDS",
        type=non_negative_float,
        default=DEFAULT_PAGE_DELAY,
        help=f"base page-request interval per source (default {DEFAULT_PAGE_DELAY:.1f}s; "
        "raised after HTTP 429/503)",
    )
    scrape.add_argument(
        "--image-delay",
        metavar="SECONDS",
        type=non_negative_float,
        default=DEFAULT_IMAGE_DELAY,
        help=f"base image interval per host (default {DEFAULT_IMAGE_DELAY:.1f}s; "
        "raised after HTTP 429/503)",
    )
    scrape.add_argument(
        "--delay",
        metavar="SECONDS",
        type=non_negative_float,
        default=DEFAULT_TITLE_DELAY,
        help=f"interval between networked titles (default {DEFAULT_TITLE_DELAY:.1f}s; "
        "no wait before the first title or for local skips)",
    )
    scrape.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show request waits, inter-title waits, adaptive slowdown, and retries",
    )

    inspect = command(
        "inspect", "inspect catalog numbers and tags without network or writes"
    )
    add_root(inspect)
    add_selection(inspect)

    rename_folders = command(
        "rename-folders", "preview or apply normalized folder names"
    )
    add_root(rename_folders)
    add_selection(rename_folders)
    add_journal(rename_folders, "folder_rename_log.json")
    rename_folders.add_argument(
        "--apply",
        action="store_true",
        help="apply the displayed plan (default is preview only)",
    )

    rename_videos = command(
        "rename-videos",
        "preview or apply safe video and matching-sidecar filename cleanup",
    )
    add_root(rename_videos)
    add_selection(rename_videos)
    add_journal(rename_videos, "video_rename_log.json")
    rename_videos.add_argument(
        "--apply",
        action="store_true",
        help="apply the displayed plan (default is preview only)",
    )

    undo_folders = command(
        "undo-folders", "preview or apply the latest folder-rename rollback batch"
    )
    add_root(undo_folders)
    add_journal(undo_folders, "folder_rename_log.json")
    undo_folders.add_argument(
        "--apply",
        action="store_true",
        help="apply the displayed rollback plan (default is preview only)",
    )

    undo_videos = command(
        "undo-videos", "preview or apply the latest video-rename rollback batch"
    )
    add_root(undo_videos)
    add_journal(undo_videos, "video_rename_log.json")
    undo_videos.add_argument(
        "--apply",
        action="store_true",
        help="apply the displayed rollback plan (default is preview only)",
    )
    return parser


def parse_cli_args(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.dir:
        parser.error(f"specify the media root with --dir or set {DIR_ENV}")
    return args


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    args = parse_cli_args()

    root = Path(args.dir).expanduser()
    if not root.is_dir():
        sys.exit(
            f"Directory does not exist or is not accessible: {root}\n"
            "Check the path, mount status, and permissions."
        )

    if args.command == "undo-folders":
        do_undo_folders(root, args.journal, apply=args.apply)
        return
    if args.command == "undo-videos":
        do_undo_videos(root, args.journal, apply=args.apply)
        return

    folders = list_folders(root)
    if args.only:
        selected = set(args.only)
        folders = [folder for folder in folders if folder.name in selected]
    if args.limit:
        folders = folders[: args.limit]

    if not folders:
        sys.exit("No folders found.")

    print(f"Root   : {root}")
    print(f"Folders: {len(folders)}")

    if args.command == "rename-folders":
        do_rename_folders(folders, args.journal, apply=args.apply)
        return
    if args.command == "rename-videos":
        do_rename_videos(folders, args.journal, apply=args.apply)
        return
    if args.command == "inspect":
        do_inspect(folders)
        return
    if args.command != "scrape":
        raise AssertionError(f"Unhandled command: {args.command}")

    fetcher = Fetcher(
        page_delay=args.page_delay,
        image_delay=args.image_delay,
        title_delay=args.delay,
        verbose=args.verbose,
    )
    do_scrape(folders, fetcher, args)
