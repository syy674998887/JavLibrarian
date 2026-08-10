import json

import pytest

from javlibrarian.rename import (
    RenameLog,
    do_rename_folders,
    do_rename_videos,
    do_undo_folders,
    do_undo_videos,
    plan_renames,
)


def write_journal(path, root, batches):
    payload = {"root": str(root.resolve()), "batches": batches}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_folder_rollback_preview_and_partial_resume(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "DONE").mkdir()
    journal = tmp_path / "folder_rename_log.json"
    payload = write_journal(
        journal,
        root,
        [
            {
                "time": "test",
                "entries": [
                    {"old": "OLD1", "new": "DONE"},
                    {"old": "OLD2", "new": "MISSING"},
                ],
            }
        ],
    )

    do_undo_folders(root, journal)
    assert (root / "DONE").exists()
    assert not (root / "OLD1").exists()
    assert json.loads(journal.read_text(encoding="utf-8")) == payload

    do_undo_folders(root, journal, apply=True)
    kept = json.loads(journal.read_text(encoding="utf-8"))
    assert len(kept["batches"]) == 1
    assert kept["batches"][0]["entries"] == [
        {"old": "OLD2", "new": "MISSING"}
    ]
    assert (root / "OLD1").exists()

    (root / "MISSING").mkdir()
    do_undo_folders(root, journal, apply=True)
    assert (root / "OLD2").exists()
    assert not journal.exists()


def test_folder_rollback_applies_latest_batch_only(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "FIRST-NEW").mkdir()
    (root / "LATEST-NEW").mkdir()
    journal = tmp_path / "history.json"
    write_journal(
        journal,
        root,
        [
            {
                "time": "older",
                "entries": [{"old": "FIRST-OLD", "new": "FIRST-NEW"}],
            },
            {
                "time": "latest",
                "entries": [{"old": "LATEST-OLD", "new": "LATEST-NEW"}],
            },
        ],
    )

    do_undo_folders(root, journal, apply=True)

    kept = json.loads(journal.read_text(encoding="utf-8"))
    assert (root / "FIRST-NEW").exists()
    assert not (root / "FIRST-OLD").exists()
    assert not (root / "LATEST-NEW").exists()
    assert (root / "LATEST-OLD").exists()
    assert [batch["time"] for batch in kept["batches"]] == ["older"]


def test_corrupt_or_foreign_journal_is_rejected_before_rename(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    bad_journal = tmp_path / "bad.json"
    bad_journal.write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit):
        RenameLog(bad_journal, root)

    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    mixed_journal = tmp_path / "mixed.json"
    write_journal(
        mixed_journal,
        foreign_root,
        [{"time": "old", "entries": [{"old": "A", "new": "B"}]}],
    )
    folder = root / "abc-001"
    folder.mkdir()

    with pytest.raises(SystemExit):
        do_rename_folders([folder], mixed_journal, apply=True)
    assert folder.exists()


def test_journal_prewrite_failure_stops_before_rename(tmp_path):
    root = tmp_path / "library"
    folder = root / "abc-001"
    folder.mkdir(parents=True)
    unwritable_journal = tmp_path / "missing" / "rename.json"

    with pytest.raises(OSError):
        do_rename_folders([folder], unwritable_journal, apply=True)

    assert folder.exists()


def test_folder_plan_reports_normalized_case_real_and_collisions(tmp_path):
    folders = []
    for name in ("SONE-035", "sone-036", "hhd800.com@SONE-037", "SONE-038-C"):
        path = tmp_path / name
        path.mkdir()
        folders.append(path)

    plan, collisions = plan_renames(folders)

    assert [(path.name, target, kind) for path, target, kind in plan] == [
        ("SONE-035", "SONE-035", "same"),
        ("sone-036", "SONE-036", "case"),
        ("hhd800.com@SONE-037", "SONE-037", "real"),
        ("SONE-038-C", "SONE-038-C", "same"),
    ]
    assert collisions == {}

    duplicate = tmp_path / "sone-035"
    _, collisions = plan_renames([folders[0], duplicate])
    assert collisions == {"sone-035": ["SONE-035", "sone-035"]}


def test_video_group_skips_when_sidecar_target_is_occupied(tmp_path):
    root = tmp_path / "library"
    folder = root / "SONE-035"
    folder.mkdir(parents=True)
    source = folder / "hhd800.com@SONE-035.mp4"
    source.write_bytes(b"video")
    source_sidecar = folder / "hhd800.com@SONE-035.srt"
    source_sidecar.write_bytes(b"source subtitle")
    occupied_sidecar = folder / "SONE-035.srt"
    occupied_sidecar.write_bytes(b"keep me")
    journal = tmp_path / "video.json"

    do_rename_videos([folder], journal, apply=True)

    assert source.exists()
    assert source_sidecar.exists()
    assert occupied_sidecar.read_bytes() == b"keep me"
    assert not (folder / "SONE-035.mp4").exists()
    assert not journal.exists()


def test_video_and_sidecar_are_journaled_and_rolled_back(tmp_path):
    root = tmp_path / "library"
    folder = root / "SONE-035"
    folder.mkdir(parents=True)
    source = folder / "hhd800.com@SONE-035.mp4"
    source.write_bytes(b"video")
    source_sidecar = folder / "hhd800.com@SONE-035.srt"
    source_sidecar.write_bytes(b"subtitle")
    journal = tmp_path / "video.json"

    do_rename_videos([folder], journal, apply=True)
    renamed = folder / "SONE-035.mp4"
    renamed_sidecar = folder / "SONE-035.srt"
    payload = json.loads(journal.read_text(encoding="utf-8"))
    assert renamed.exists() and renamed_sidecar.exists()
    assert payload["batches"][-1]["entries"][0]["sides"] == [
        {"old": source_sidecar.name, "new": renamed_sidecar.name}
    ]

    do_undo_videos(root, journal)
    assert renamed.exists() and renamed_sidecar.exists() and journal.exists()

    do_undo_videos(root, journal, apply=True)
    assert source.exists() and source_sidecar.exists()
    assert not renamed.exists() and not renamed_sidecar.exists()
    assert not journal.exists()


def test_video_cleanup_never_treats_movie_nfo_as_sidecar(tmp_path):
    root = tmp_path / "library"
    folder = root / "SONE-035"
    folder.mkdir(parents=True)
    video = folder / "movie.mp4"
    video.write_bytes(b"video")
    completion_marker = folder / "movie.nfo"
    completion_marker.write_bytes(b"folder metadata")

    do_rename_videos([folder], tmp_path / "video.json", apply=True)

    assert (folder / "SONE-035.mp4").exists()
    assert completion_marker.read_bytes() == b"folder metadata"
    assert not (folder / "SONE-035.nfo").exists()


def test_video_rollback_never_overwrites_original_path(tmp_path):
    root = tmp_path / "library"
    folder = root / "SONE-035"
    folder.mkdir(parents=True)
    current = folder / "SONE-035.mp4"
    current.write_bytes(b"renamed video")
    original = folder / "dirty-name.mp4"
    original.write_bytes(b"must survive")
    journal = tmp_path / "video.json"
    write_journal(
        journal,
        root,
        [
            {
                "time": "test",
                "entries": [
                    {
                        "dir": folder.name,
                        "old": original.name,
                        "new": current.name,
                        "sides": [],
                    }
                ],
            }
        ],
    )

    do_undo_videos(root, journal, apply=True)

    assert current.read_bytes() == b"renamed video"
    assert original.read_bytes() == b"must survive"
    assert journal.exists()


def test_folder_undo_rejects_video_journal_before_renaming(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    victim = root / "SONE-035.mp4"
    victim.mkdir()
    journal = tmp_path / "video.json"
    write_journal(
        journal,
        root,
        [
            {
                "time": "test",
                "entries": [
                    {
                        "dir": "SONE-035",
                        "old": "dirty.mp4",
                        "new": victim.name,
                        "sides": [],
                    }
                ],
            }
        ],
    )

    with pytest.raises(SystemExit, match="video rename journal"):
        do_undo_folders(root, journal, apply=True)

    assert victim.is_dir()
    assert not (root / "dirty.mp4").exists()
    assert journal.exists()


def test_video_undo_rejects_folder_journal(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    journal = tmp_path / "folder.json"
    write_journal(
        journal,
        root,
        [{"time": "test", "entries": [{"old": "OLD", "new": "NEW"}]}],
    )

    with pytest.raises(SystemExit, match="folder rename journal"):
        do_undo_videos(root, journal, apply=True)

    assert journal.exists()
