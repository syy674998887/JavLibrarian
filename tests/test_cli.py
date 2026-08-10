import argparse
import io
from contextlib import redirect_stderr

import pytest

from javlibrarian import cli as cli_module
from javlibrarian.cli import build_parser, parse_cli_args


def cli_parse(*argv):
    with redirect_stderr(io.StringIO()):
        return parse_cli_args([*argv, "--dir", "/tmp"])


def cli_rejects(*argv):
    try:
        cli_parse(*argv)
    except SystemExit as error:
        return error.code == 2
    return False


def command_help():
    parser = build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return parser.format_help(), {
        name: child.format_help() for name, child in subparsers.choices.items()
    }


def test_scrape_accepts_selection_and_pacing_options():
    parsed = cli_parse(
        "scrape",
        "--limit",
        "2",
        "--only",
        "SONE-035",
        "--only",
        "IPVR-256-C",
        "--page-delay",
        "1.5",
        "--image-delay",
        "0",
        "--delay",
        "2",
    )

    assert (
        parsed.command,
        parsed.limit,
        parsed.only,
        parsed.page_delay,
        parsed.image_delay,
        parsed.delay,
    ) == ("scrape", 2, ["SONE-035", "IPVR-256-C"], 1.5, 0.0, 2.0)


def test_top_level_help_lists_all_explicit_commands():
    top_help, _ = command_help()

    assert all(
        name in top_help
        for name in (
            "scrape",
            "inspect",
            "rename-folders",
            "rename-videos",
            "undo-folders",
            "undo-videos",
        )
    )


def test_scrape_help_and_removed_options():
    _, help_by_command = command_help()
    scrape_help = help_by_command["scrape"]

    assert all(
        item in scrape_help
        for item in (
            "--limit N",
            "--only NAME",
            "--page-delay SECONDS",
            "--image-delay SECONDS",
            "--delay SECONDS",
            "--verbose",
        )
    )
    assert "--html-delay" not in scrape_help
    assert "--movie-delay" not in scrape_help
    assert cli_rejects("scrape", "--html-delay", "1")
    assert cli_rejects("scrape", "--movie-delay", "1")
    assert "--no-images" not in scrape_help
    assert "--sample-limit" not in scrape_help
    assert cli_rejects("scrape", "--no-images")
    assert cli_rejects("scrape", "--sample-limit", "1")


def test_options_are_scoped_to_their_workflows():
    _, help_by_command = command_help()

    assert cli_rejects("inspect", "--force")
    assert not cli_rejects("rename-folders", "--only", "SONE-035", "--apply")
    assert "--journal PATH" in help_by_command["rename-folders"]
    assert cli_rejects("rename-folders", "--page-delay", "1")
    assert not cli_rejects("undo-videos", "--journal", "x.json", "--apply")
    assert cli_rejects("undo-videos", "--all")
    assert cli_rejects("undo-videos", "--only", "SONE-035")


def test_explicit_command_is_required_and_old_flat_options_are_rejected():
    assert cli_rejects()
    assert all(
        cli_rejects("scrape", option, "1")
        for option in ("--max-samples", "--img-delay")
    )
    assert cli_rejects("--inspect")
    assert cli_rejects("rename-folders", "--folder-log", "x.json")
    assert cli_rejects("undo-folders", "--undo-all")


def test_scoped_action_modifiers_are_accepted():
    assert (
        cli_parse("inspect").command,
        cli_parse("rename-folders", "--apply").apply,
        cli_parse("undo-videos", "--apply").apply,
    ) == ("inspect", True, True)


@pytest.mark.parametrize(
    "argv",
    [
        ("scrape", "--limit", "-1"),
        ("scrape", "--page-delay", "-0.1"),
        ("scrape", "--image-delay", "nan"),
        ("scrape", "--delay", "inf"),
    ],
)
def test_negative_counts_and_invalid_delays_are_rejected(argv):
    assert cli_rejects(*argv)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("rename-folders", "folder_rename_log.json"),
        ("undo-folders", "folder_rename_log.json"),
        ("rename-videos", "video_rename_log.json"),
        ("undo-videos", "video_rename_log.json"),
    ],
)
def test_default_journal_is_a_relative_working_directory_path(command, expected):
    parsed = cli_parse(command)

    assert parsed.journal == expected


def test_media_root_can_come_from_environment(monkeypatch):
    monkeypatch.setenv("JAVLIBRARIAN_DIR", "/media/JAV")

    assert parse_cli_args(["inspect"]).dir == "/media/JAV"


def test_main_replaces_standard_stream_encoding_errors(monkeypatch):
    class ReconfigurableStream(io.StringIO):
        def __init__(self):
            super().__init__()
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    stdout = ReconfigurableStream()
    stderr = ReconfigurableStream()
    monkeypatch.setattr(cli_module.sys, "stdout", stdout)
    monkeypatch.setattr(cli_module.sys, "stderr", stderr)

    def stop_after_stream_setup():
        raise RuntimeError("stop after stream setup")

    monkeypatch.setattr(cli_module, "parse_cli_args", stop_after_stream_setup)

    with pytest.raises(RuntimeError, match="stop after stream setup"):
        cli_module.main()

    assert stdout.calls == [{"errors": "replace"}]
    assert stderr.calls == [{"errors": "replace"}]
