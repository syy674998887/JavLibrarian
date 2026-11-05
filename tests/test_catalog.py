from pathlib import Path

import pytest

from javlibrarian.catalog import list_folders, normalize, standard_name


@pytest.mark.parametrize(
    ("folder_name", "expected"),
    [
        ("SONE-035", ("SONE-035", [])),
        ("IPVR-256-C", ("IPVR-256", ["中文字幕"])),
        ("SONE-035-UC", ("SONE-035", ["无码破解", "中文字幕"])),
        ("SONE-035-leak", ("SONE-035", ["无码流出"])),
        ("ipvr00256", ("IPVR-256", [])),
        ("vrkm01422", ("VRKM-1422", [])),
        ("sone00035", ("SONE-035", [])),
        ("[LD-024] title", ("LD-024", [])),
        ("hhd800.com@SSIS-001", ("SSIS-001", [])),
        ("SONE-267.[4K]@R", ("SONE-267", [])),
        ("SIVR-315 8K Konan Koyoi", ("SIVR-315", [])),
        ("FC2PPV1234567", ("FC2-PPV-1234567", [])),
        ("FC2-PPV-1234567-C", ("FC2-PPV-1234567", ["中文字幕"])),
        ("not-a-code", (None, [])),
    ],
)
def test_normalize_catalog_numbers(folder_name, expected):
    assert normalize(folder_name) == expected


@pytest.mark.parametrize(
    ("folder_name", "expected"),
    [
        ("ipvr00256-C", "IPVR-256-C"),
        ("ssis00001-C", "SSIS-001-C"),
        ("SONE-035-UC", "SONE-035-UC"),
        ("SONE-035-leak", "SONE-035-U"),
        ("not-a-code", None),
    ],
)
def test_standard_name_preserves_semantic_suffix(folder_name, expected):
    assert standard_name(folder_name) == expected


def test_list_folders_is_first_level_visible_and_case_insensitive_sorted(tmp_path):
    for name in ("zeta", "Alpha", ".hidden"):
        (tmp_path / name).mkdir()
    (tmp_path / "file.txt").write_text("not a folder", encoding="utf-8")
    (tmp_path / "Alpha" / "nested").mkdir()

    assert list_folders(tmp_path) == [tmp_path / "Alpha", tmp_path / "zeta"]
