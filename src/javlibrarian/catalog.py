"""Catalog-number parsing and media-folder discovery."""

import re
from pathlib import Path


VIDEO_EXT = {".mp4", ".mkv", ".avi", ".wmv", ".mov", ".m4v", ".ts", ".iso", ".rmvb", ".flv"}

# Common site prefixes embedded in downloaded folder names.
SITE_PREFIX = re.compile(
    r"^\s*(?:[\w.-]+\.(?:com|me|net|la|cc|xyz|top|org|tv|info)[@\-])+", re.I
)
LEAD_BRACKET = re.compile(r"^\s*[\[\(]([^\]\)]*)[\]\)]\s*")
CONTENT_ID = re.compile(r"^([a-z]{2,7})(\d{4,6})$", re.I)
STD_ID = re.compile(r"^([A-Za-z]{2,7})[-_](\d{2,6})$")
ANY_ID = re.compile(r"([A-Za-z]{2,7})[-_](\d{2,6})")
FC2 = re.compile(r"FC2[-_]?(?:PPV[-_]?)?(\d{5,8})", re.I)

# Semantic suffixes are retained as NFO tags. Order matters: longer forms first.
TAG_RULES = [
    (re.compile(r"-UC(?![A-Za-z0-9])", re.I), ["无码破解", "中文字幕"]),
    (re.compile(r"-uncensored(?![A-Za-z])", re.I), ["无码破解"]),
    (re.compile(r"-leak(?![A-Za-z])", re.I), ["无码流出"]),
    (re.compile(r"-U(?![A-Za-z0-9])", re.I), ["无码破解"]),
    (re.compile(r"-C(?![A-Za-z0-9])", re.I), ["中文字幕"]),
]

# Noise stripped for lookup only. Order matters.
JUNK_PATTERNS = [
    r"\.?\[4K\]@R",
    r"\[MP4_[^\]]*\]",
    r"\[\d{3,4}[pP]\]",
    r"-Rife(?![A-Za-z])",
    r"-4k(?![A-Za-z])",
    r"-8k(?![A-Za-z])",
    r"-UC(?![A-Za-z0-9])",
    r"-uncensored(?![A-Za-z])",
    r"-leak(?![A-Za-z])",
    r"-U(?![A-Za-z0-9])",
    r"-C(?![A-Za-z0-9])",
    r"-cd\d+(?![0-9])",
    r"-[A-F](?![A-Za-z0-9])",
    r"-\d(?![0-9])",
]

SUFFIX_MAP = {
    ("无码破解", "中文字幕"): "-UC",
    ("无码破解",): "-U",
    ("无码流出",): "-U",
    ("中文字幕",): "-C",
}


def normalize(folder_name):
    """Return ``(catalog_number, tags)`` parsed from a folder name."""
    tags = []
    for pattern, matched_tags in TAG_RULES:
        if pattern.search(folder_name):
            tags = list(matched_tags)
            break

    match = FC2.search(folder_name)
    if match:
        return f"FC2-PPV-{match.group(1)}", tags

    text = folder_name.strip()
    bracket = LEAD_BRACKET.match(text)
    if bracket:
        inner = bracket.group(1).strip()
        match = STD_ID.match(inner) or ANY_ID.search(inner)
        if match:
            return f"{match.group(1).upper()}-{match.group(2)}", tags
        text = LEAD_BRACKET.sub("", text).strip()

    text = SITE_PREFIX.sub("", text).strip()
    text = re.sub(r"^\[[^\]]*\]\s*", "", text).strip()

    parts = re.split(r"[\s　]+", text)
    core = parts[0] if parts else text

    previous = None
    while previous != core:
        previous = core
        for pattern in JUNK_PATTERNS:
            core = re.sub(pattern, "", core, flags=re.I)
    core = core.strip(" -_.")

    match = CONTENT_ID.match(core)
    if match:
        return f"{match.group(1).upper()}-{int(match.group(2))}", tags

    match = STD_ID.match(core)
    if match:
        return f"{match.group(1).upper()}-{match.group(2)}", tags

    match = ANY_ID.search(core)
    if match:
        return f"{match.group(1).upper()}-{match.group(2)}", tags

    return None, tags


def standard_name(folder_name):
    """Return a normalized folder name while retaining semantic suffixes."""
    code, tags = normalize(folder_name)
    if not code:
        return None
    return f"{code}{SUFFIX_MAP.get(tuple(tags), '')}"


def list_folders(root):
    """Return visible first-level directories in stable name order."""
    return sorted(
        [path for path in Path(root).iterdir() if path.is_dir() and not path.name.startswith(".")],
        key=lambda path: path.name.lower(),
    )
