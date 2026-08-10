"""Filesystem primitives shared by scraping and rename workflows."""

import os
from pathlib import Path


def atomic_write_bytes(path, data):
    """Atomically replace *path* with bytes written in the same directory."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def path_present(path):
    """Like exists(), but also treat a dangling symlink as occupied."""
    path = Path(path)
    return path.exists() or path.is_symlink()


def same_entry(left, right):
    """Return whether two spellings resolve to the same filesystem entry."""
    try:
        return os.path.samefile(left, right)
    except (OSError, ValueError):
        return False


def target_conflicts(source, target):
    """Return whether *target* is occupied by something other than *source*."""
    return path_present(target) and not same_entry(source, target)


def rename_folder(folder, new_name):
    """Rename a folder safely, including case-only changes on macOS and SMB."""
    parent = folder.parent
    target = parent / new_name

    if folder.name == new_name:
        return True, "Already normalized"

    case_only = folder.name.lower() == new_name.lower()
    if target_conflicts(folder, target):
        return False, f"Target already exists; skipped: {new_name}"

    def landed():
        try:
            return new_name in {p.name for p in parent.iterdir()}
        except Exception:
            return False

    try:
        folder.rename(target)
        if not case_only or landed():
            return True, new_name
    except Exception as exc:
        if not case_only:
            return False, f"{type(exc).__name__}: {exc}"

    if case_only:
        try:
            source = target if target.exists() else folder
            tmp = parent / f"__casetmp__{new_name}"
            index = 0
            while tmp.exists():
                index += 1
                tmp = parent / f"__casetmp{index}__{new_name}"
            source.rename(tmp)
            tmp.rename(parent / new_name)
            return (True, new_name) if landed() else (False, "Rename verification failed")
        except Exception as exc:
            return False, f"Two-step rename failed: {type(exc).__name__}: {exc}"

    return False, "Rename verification failed"


def rename_path(source, new_name):
    """Rename one file without overwriting, including case-only changes."""
    parent = source.parent
    if source.name == new_name:
        return
    target = parent / new_name
    if target_conflicts(source, target):
        raise FileExistsError(f"Target already exists; refusing to overwrite: {target}")
    source.rename(target)
    if source.name.lower() != new_name.lower():
        return
    if new_name in {p.name for p in parent.iterdir()}:
        return
    tmp = parent / f"__casetmp__{new_name}"
    index = 0
    while tmp.exists():
        index += 1
        tmp = parent / f"__casetmp{index}__{new_name}"
    (parent / new_name).rename(tmp)
    tmp.rename(parent / new_name)
