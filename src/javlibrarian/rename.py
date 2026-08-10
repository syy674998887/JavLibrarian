"""Previewable folder/video renaming with write-ahead rollback journals."""

import json
import re
import sys
import time
from pathlib import Path

from .catalog import SUFFIX_MAP, VIDEO_EXT, normalize, standard_name
from .filesystem import (
    atomic_write_bytes,
    path_present,
    rename_folder,
    rename_path,
    same_entry,
    target_conflicts,
)


class RenameLog:
    """A root-bound, batch-oriented, write-ahead rename journal."""

    def __init__(self, path, root):
        self.path = Path(path)
        self.root = str(Path(root).resolve())
        self.data = {"root": self.root, "batches": []}
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                sys.exit(
                    "Unable to read rename journal; stopped to avoid overwriting "
                    f"rollback history: {self.path}\n{error}"
                )
            if not isinstance(loaded, dict) or not isinstance(
                loaded.get("batches"), list
            ):
                sys.exit(
                    "Invalid rename journal format; stopped to avoid overwriting "
                    f"rollback history: {self.path}"
                )
            self.data = loaded
        self.batch = None

    def root_matches(self):
        return self.data.get("root") == self.root

    def open_batch(self):
        self.batch = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "entries": []}
        self.data["root"] = self.root
        self.data["batches"].append(self.batch)

    def add(self, entry):
        if self.batch is None:
            self.open_batch()
        self.batch["entries"].append(entry)
        self.flush()

    def flush(self):
        try:
            payload = json.dumps(self.data, ensure_ascii=False, indent=1).encode("utf-8")
            atomic_write_bytes(self.path, payload)
        except OSError as error:
            raise OSError(
                f"Unable to write rename journal; operation stopped: {self.path}: {error}"
            ) from error

    def batches(self):
        return self.data.get("batches", [])

    def drop_batch(self, index):
        try:
            del self.data["batches"][index]
        except Exception:
            return
        if self.data["batches"]:
            self.flush()
        elif self.path.exists():
            self.path.unlink()


def load_log_for_undo(path, root):
    """Load and validate a journal, returning it and its latest batch index."""
    journal_path = Path(path)
    if not journal_path.exists():
        sys.exit(f"Rename journal not found: {path}")
    log = RenameLog(path, root)
    if not log.batches():
        sys.exit("Rename journal is empty; nothing to undo.")
    if not log.root_matches():
        sys.exit(
            "Rename journal root does not match; stopped to protect the wrong library:\n"
            f"  Journal root : {log.data.get('root')}\n"
            f"  Selected root: {log.root}\n"
            "Point --dir to the root recorded in the journal to undo that library."
        )
    return log, len(log.batches()) - 1


def plan_renames(folders):
    """Return folder rename plans and case-insensitive destination collisions."""
    plan = []
    targets = {}
    for folder in folders:
        new_name = standard_name(folder.name)
        if not new_name:
            continue
        if new_name == folder.name:
            kind = "same"
        elif new_name.lower() == folder.name.lower():
            kind = "case"
        else:
            kind = "real"
        plan.append((folder, new_name, kind))
        targets.setdefault(new_name.lower(), []).append(folder.name)

    collisions = {key: value for key, value in targets.items() if len(value) > 1}
    return plan, collisions


def do_rename_folders(folders, log_path, apply=False):
    plan, collisions = plan_renames(folders)

    same = [item for item in plan if item[2] == "same"]
    case = [item for item in plan if item[2] == "case"]
    real = [item for item in plan if item[2] == "real"]
    unknown = len(folders) - len(plan)

    print(f"\nFolders             : {len(folders)}")
    print(f"  Already normalized: {len(same)}")
    print(f"  Case-only changes : {len(case)}   (requires two-step mv)")
    print(f"  Renames           : {len(real)}")
    if unknown:
        print(f"  Unrecognized IDs  : {unknown}   (unchanged)")

    if collisions:
        print(
            f"\n⚠️  Found {len(collisions)} naming conflict group(s); "
            "all affected folders will be skipped:"
        )
        for target, sources in collisions.items():
            print(f"    [{target}] ← {sources}")
    else:
        print("\n✅ No naming conflicts")

    if real:
        print("\n─── Renames ───")
        for folder, new_name, _ in real:
            print(f"  {folder.name[:52]:<54} → {new_name}")
    if case:
        print("\n─── Case-only changes ───")
        for folder, new_name, _ in case:
            print(f"  {folder.name:<24} → {new_name}")

    if not apply:
        print("\n[Preview] No changes made. Review the plan, then add --apply.")
        return

    collision_names = {source for values in collisions.values() for source in values}
    root = folders[0].parent if folders else Path(".")
    log = RenameLog(log_path, root)
    if log.batches() and not log.root_matches():
        sys.exit(
            "Rename journal belongs to another media root; stopped to avoid mixing batches:\n"
            f"  Journal root : {log.data.get('root')}\n"
            f"  Selected root: {log.root}\n"
            "Use --journal to select a different journal."
        )
    log.open_batch()
    log.flush()
    ok = skip = fail = recorded = 0
    print("\n─── Applying changes ───")
    for folder, new_name, kind in plan:
        if kind == "same":
            continue
        if folder.name in collision_names:
            print(f"  ⏭  {folder.name}  (conflict; skipped)")
            skip += 1
            continue

        target = folder.parent / new_name
        if target_conflicts(folder, target):
            print(f"  ⏭  {folder.name} → {new_name}  (target exists; skipped)")
            skip += 1
            continue

        log.add({"old": folder.name, "new": new_name})
        recorded += 1
        good, message = rename_folder(folder, new_name)
        if good:
            ok += 1
            print(f"  ✅ {folder.name[:50]:<52} → {new_name}")
        else:
            fail += 1
            print(f"  ❌ {folder.name[:50]:<52} {message}")

    if not recorded:
        log.drop_batch(-1)

    print(f"\nFolder rename complete: succeeded {ok}  skipped {skip}  failed {fail}")
    if recorded:
        print(f"Journal saved: {log_path}")
        print('Preview undo:  uv run javlibrarian undo-folders --dir "<media-root>"')


def undo_path_state(source, target, kind):
    """Classify one reverse move without changing the filesystem."""
    source = Path(source)
    target = Path(target)
    source_present = path_present(source)
    target_present = path_present(target)
    is_expected = Path.is_dir if kind == "directory" else Path.is_file

    if source_present:
        if not is_expected(source):
            return "conflict", f"source exists but is not a {kind}: {source.name}"
        if target_present and not same_entry(source, target):
            return "conflict", f"target already exists: {target.name}"
        return "ready", ""
    if target_present:
        if is_expected(target):
            return "done", "already restored"
        return "conflict", f"original path is occupied by a non-{kind}: {target.name}"
    return "missing", f"neither current nor original path exists: {source.name}"


def preview_undo_group(present, moves):
    """Preview and virtually apply a group of ``(old, new)`` journal moves."""
    states = []
    for old, new in moves:
        if new in present:
            state = "conflict" if old in present and old != new else "ready"
        elif old in present:
            state = "done"
        else:
            state = "missing"
        states.append((old, new, state))

    issues = [item for item in states if item[2] in {"conflict", "missing"}]
    if issues:
        state = "conflict" if any(item[2] == "conflict" for item in issues) else "missing"
        details = []
        for old, new, item_state in issues:
            if item_state == "conflict":
                details.append(f"target exists: {old}")
            else:
                details.append(f"missing: {new}")
        return state, "; ".join(details)

    changed = False
    for old, new, state in states:
        if state == "ready":
            present.discard(new)
            present.add(old)
            changed = True
    return ("ready", "") if changed else ("done", "already restored")


def _undo_entries(root, entries, undo_fn, label):
    """Roll back a journal batch in reverse order."""
    ok = fail = skip = 0
    remaining = []
    for item in reversed(entries):
        state, message = undo_fn(root, item)
        shown_new = f"{item['dir']}/{item['new']}" if item.get("dir") else item["new"]
        shown_old = f"{item['dir']}/{item['old']}" if item.get("dir") else item["old"]
        if state == "ok":
            ok += 1
            print(f"  ↩️  {shown_new[:52]:<54} → {shown_old}")
        elif state == "done":
            ok += 1
            print(f"  ✅ {shown_old[:52]:<54} (already restored)")
        elif state == "missing":
            skip += 1
            remaining.append(item)
            print(f"  ⏭  {shown_new[:52]:<54} {message}")
        else:
            fail += 1
            remaining.append(item)
            print(f"  ❌ {shown_new[:52]:<54} {message}")
    print(f"\n{label} rollback complete: succeeded {ok}  skipped {skip}  failed {fail}")
    return ok, skip, fail, list(reversed(remaining))


def do_undo_folders(root, log_path, apply=False):
    log, index = load_log_for_undo(log_path, root)
    batches = log.batches()
    batch = batches[index]
    if any("dir" in item for item in batch["entries"]):
        sys.exit("This is a video rename journal; use undo-videos.")
    print(
        f"Journal batches: {len(batches)}; rollback selection: "
        f"latest batch / {len(batch['entries'])} entries"
    )

    if not apply:
        present = {path.name for path in Path(root).iterdir()}
        counts = {"ready": 0, "done": 0, "missing": 0, "conflict": 0}
        print(f"\n── Batch {index + 1}/{len(batches)}  {batch.get('time', '')}")
        for item in reversed(batch["entries"]):
            state, message = preview_undo_group(present, [(item["old"], item["new"])])
            counts[state] += 1
            arrow = f"{item['new'][:52]:<54} → {item['old']}"
            if state == "ready":
                print(f"  ↩️  {arrow}")
            elif state == "done":
                print(f"  ✅ {arrow}  (already restored)")
            elif state == "missing":
                print(f"  ⏭  {arrow}  ({message})")
            else:
                print(f"  ⚠️  {arrow}  ({message})")
        print(
            "\nFolder rollback preview: "
            f"ready {counts['ready']}  already restored {counts['done']}  "
            f"missing {counts['missing']}  conflicts {counts['conflict']}"
        )
        print(
            "[Preview] No names or journal records changed. "
            "Review the plan, then add --apply."
        )
        return

    def do_one(root_path, item):
        current = Path(root_path) / item["new"]
        target = Path(root_path) / item["old"]
        state, message = undo_path_state(current, target, "directory")
        if state != "ready":
            return state, message
        good, message = rename_folder(current, item["old"])
        return ("ok", "") if good else ("failed", message)

    print(f"\n── Batch {index + 1}/{len(batches)}  {batch.get('time', '')}")
    ok, skip, fail, remaining = _undo_entries(
        root, batch["entries"], do_one, "Folder"
    )
    if remaining:
        if ok:
            batch["entries"] = remaining
            log.flush()
        print("Skipped or failed entries remain in the journal; resolve them and retry.")
    else:
        log.drop_batch(index)
        print("Rolled-back batch records were removed from the journal.")


VID_SITE = re.compile(
    r"^(?:\[[^\]]*\]@?|[\w.-]+\.(?:com|me|net|la|cc|xyz|top|tv|info)@)+", re.I
)
VOL_PATTERNS = [
    (r"^(.*?)[-_\s](\d{1,2})[-_](?:\d+k|8k|4k)$", "num"),
    (r"^(.*?)[-_\s]([A-Fa-f])(?:[-_].*)?$", "alpha"),
    (r"^(.*?)[-_\s](\d{1,2})$", "num"),
    (r"^(.*?[a-z])(\d{1,2})$", "num"),
    (r"^(.*?\d)([a-f])(?:[-_].*)?$", "alpha"),
]
SIDECAR_EXT = {".nfo", ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}


def video_volume_key(stem):
    """Return a cleaned base name and optional volume number."""
    value = VID_SITE.sub("", stem)
    value = re.sub(r"[\[\]]", "", value)
    for pattern, kind in VOL_PATTERNS:
        match = re.search(pattern, value, re.I)
        if match:
            group = match.group(2)
            index = int(group) if kind == "num" else ord(group.upper()) - 64
            return match.group(1).lower().rstrip("-_ "), index
    return value.lower(), None


def classify_videos(folder):
    """Classify videos as single, split volumes, duplicate sources, or none."""
    videos = sorted(
        [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_EXT
        ],
        key=lambda path: path.name,
    )
    code, _ = normalize(folder.name)
    prefix_match = re.match(r"^([A-Za-z]+)", code) if code else None
    prefix = prefix_match.group(1).lower() if prefix_match else ""

    related = []
    junk = []
    for video in videos:
        clean = VID_SITE.sub("", video.stem).lower()
        (related if prefix and prefix in clean else junk).append(video)

    if not related and videos:
        related, junk = videos, []

    if not related:
        return "none", [], junk
    if len(related) == 1:
        return "single", related, junk

    keys = [video_volume_key(video.stem) for video in related]
    bases = {key[0] for key in keys}
    indexes = [key[1] for key in keys]
    if len(bases) == 1 and None not in indexes and len(set(indexes)) == len(indexes):
        ordered = [
            video for _, video in sorted(zip(indexes, related), key=lambda item: item[0])
        ]
        return "split", ordered, junk
    return "dup", related, junk


def plan_video_renames(folders):
    """Return video rename plans, duplicate sources, and unrelated videos."""
    plan = []
    duplicates = []
    unrelated = []
    for folder in folders:
        code, tags = normalize(folder.name)
        if not code:
            continue
        base = f"{code}{SUFFIX_MAP.get(tuple(tags), '')}"
        kind, videos, junk = classify_videos(folder)
        if junk:
            unrelated.append((folder, junk))
        if kind == "dup":
            duplicates.append((folder, videos))
            continue
        if kind == "single":
            targets = [f"{base}{videos[0].suffix.lower()}"]
        elif kind == "split":
            targets = [
                f"{base}-{index}{video.suffix.lower()}"
                for index, video in enumerate(videos, 1)
            ]
        else:
            continue
        for video, target in zip(videos, targets):
            if video.name != target:
                plan.append((folder, video, target))
    return plan, duplicates, unrelated


def do_rename_videos(folders, log_path, apply=False):
    plan, duplicates, unrelated = plan_video_renames(folders)

    print(f"\nVideo files eligible for safe cleanup: {len(plan)}")
    print(
        f"⚠️  Folders with duplicate sources     : {len(duplicates)} "
        "(reported only; manual choice required)"
    )
    print(
        f"🚮 Folders with unrelated files        : {len(unrelated)} "
        "(reported only; manual review required)"
    )

    if duplicates:
        print("\n" + "─" * 78)
        print(
            "⚠️  Duplicate sources — multiple sources or qualities for one title "
            "require a manual choice"
        )
        print("─" * 78)
        for folder, videos in duplicates:
            print(f"  {folder.name}")
            for video in videos:
                print(f"     └ {video.name:<48} {video.stat().st_size / 2**30:6.2f} GB")

    if unrelated:
        print("\n" + "─" * 78)
        print(
            "🚮 Unrelated files — suspected promotional files; "
            "nothing will be deleted or renamed"
        )
        print("─" * 78)
        for folder, videos in unrelated:
            print(f"  {folder.name}")
            for video in videos:
                print(f"     └ {video.name:<48} {video.stat().st_size / 2**30:6.2f} GB")

    if plan:
        print("\n" + "─" * 78)
        print("✅ Video files eligible for cleanup")
        print("─" * 78)
        current = None
        for folder, video, target in plan:
            if folder.name != current:
                print(f"  {folder.name}/")
                current = folder.name
            print(f"     {video.name[:50]:<52} → {target}")

    if not apply:
        print("\n[Preview] No changes made. Review the plan, then add --apply.")
        return

    root = folders[0].parent if folders else Path(".")
    log = RenameLog(log_path, root)
    if log.batches() and not log.root_matches():
        sys.exit(
            "Rename journal belongs to another media root; stopped to avoid mixing batches:\n"
            f"  Journal root : {log.data.get('root')}\n"
            f"  Selected root: {log.root}\n"
            "Use --journal to select a different journal."
        )
    log.open_batch()
    log.flush()
    ok = skip = fail = recorded = 0
    print("\n─── Applying changes ───")
    for folder, video, target_name in plan:
        target = folder / target_name
        if target_conflicts(video, target):
            print(f"  ⏭  {video.name} → {target_name}  (target exists; skipped)")
            skip += 1
            continue

        side_moves = []
        for sidecar in folder.iterdir():
            if (
                sidecar.is_file()
                and sidecar.name.lower() != "movie.nfo"
                and sidecar.stem == video.stem
                and sidecar.suffix.lower() in SIDECAR_EXT
            ):
                side_target = folder / (Path(target_name).stem + sidecar.suffix)
                side_moves.append((sidecar, side_target))
        planned_targets = {}
        for sidecar, side_target in side_moves:
            planned_targets.setdefault(side_target.name.lower(), []).append(sidecar.name)
        duplicate_targets = {
            target_name: sources
            for target_name, sources in planned_targets.items()
            if len(sources) > 1
        }
        if duplicate_targets:
            details = ", ".join(
                f"{target_name} ← {sources}"
                for target_name, sources in duplicate_targets.items()
            )
            print(
                f"  ⏭  {video.name} → {target_name}  "
                f"(sidecar targets collide: {details})"
            )
            skip += 1
            continue
        side_conflicts = [
            (sidecar, side_target)
            for sidecar, side_target in side_moves
            if target_conflicts(sidecar, side_target)
        ]
        if side_conflicts:
            details = ", ".join(
                f"{sidecar.name} → {side_target.name}"
                for sidecar, side_target in side_conflicts
            )
            print(
                f"  ⏭  {video.name} → {target_name}  "
                f"(sidecar target exists: {details})"
            )
            skip += 1
            continue

        entry = {
            "dir": folder.name,
            "old": video.name,
            "new": target_name,
            "sides": [
                {"old": sidecar.name, "new": side_target.name}
                for sidecar, side_target in side_moves
            ],
        }
        log.add(entry)
        recorded += 1
        try:
            rename_path(video, target_name)
            for sidecar, side_target in side_moves:
                rename_path(sidecar, side_target.name)
        except Exception as error:
            fail += 1
            print(f"  ❌ {video.name[:50]:<52} {type(error).__name__}: {error}")
            continue
        ok += 1
        print(f"  ✅ {video.name[:50]:<52} → {target_name}")

    if not recorded:
        log.drop_batch(-1)

    print(f"\nVideo rename complete: succeeded {ok}  skipped {skip}  failed {fail}")
    if recorded:
        print(f"Journal saved: {log_path}")
        print('Preview undo:  uv run javlibrarian undo-videos --dir "<media-root>"')


def video_undo_moves(item):
    """Return sidecar moves first and the video move last."""
    directory = item["dir"]
    moves = [
        (f"{directory}/{side['old']}", f"{directory}/{side['new']}")
        for side in item.get("sides", [])
    ]
    moves.append((f"{directory}/{item['old']}", f"{directory}/{item['new']}"))
    return moves


def do_undo_videos(root, log_path, apply=False):
    log, index = load_log_for_undo(log_path, root)
    batches = log.batches()
    batch = batches[index]
    if any("dir" not in item for item in batch["entries"]):
        sys.exit("This is a folder rename journal; use undo-folders.")
    print(
        f"Journal batches: {len(batches)}; rollback selection: "
        f"latest batch / {len(batch['entries'])} entries"
    )

    if not apply:
        present = set()
        for directory in Path(root).iterdir():
            if directory.is_dir():
                for child in directory.iterdir():
                    present.add(f"{directory.name}/{child.name}")
        counts = {"ready": 0, "done": 0, "missing": 0, "conflict": 0}
        print(f"\n── Batch {index + 1}/{len(batches)}  {batch.get('time', '')}")
        for item in reversed(batch["entries"]):
            moves = video_undo_moves(item)
            state, message = preview_undo_group(present, moves)
            counts[state] += 1
            prefix = f"{item['dir']}/"
            arrow = f"{prefix + item['new']:<54} → {item['old']}"
            if state == "ready":
                print(f"  ↩️  {arrow}")
            elif state == "done":
                print(f"  ✅ {arrow}  (already restored)")
            elif state == "missing":
                print(f"  ⏭  {arrow}  ({message})")
            else:
                print(f"  ⚠️  {arrow}  ({message})")
            for side in item.get("sides", []):
                print(f"      └ {side['new']} → {side['old']}")
        print(
            "\nVideo rollback preview: "
            f"ready {counts['ready']}  already restored {counts['done']}  "
            f"missing {counts['missing']}  conflicts {counts['conflict']}"
        )
        print(
            "[Preview] No names or journal records changed. "
            "Review the plan, then add --apply."
        )
        return

    def do_one(root_path, item):
        directory = Path(root_path) / item["dir"]
        moves = [
            (directory / side["new"], directory / side["old"])
            for side in item.get("sides", [])
        ]
        moves.append((directory / item["new"], directory / item["old"]))

        states = []
        for source, target in moves:
            state, message = undo_path_state(source, target, "file")
            states.append((source, target, state, message))
        conflicts = [item for item in states if item[2] == "conflict"]
        if conflicts:
            return "failed", "; ".join(item[3] for item in conflicts)
        missing = [item for item in states if item[2] == "missing"]
        if missing:
            return "missing", "; ".join(item[3] for item in missing)
        if all(item[2] == "done" for item in states):
            return "done", "already restored"

        try:
            for source, target, state, _ in states:
                if state == "ready":
                    rename_path(source, target.name)
            return "ok", ""
        except Exception as error:
            return "failed", f"{type(error).__name__}: {error}"

    print(f"\n── Batch {index + 1}/{len(batches)}  {batch.get('time', '')}")
    ok, skip, fail, remaining = _undo_entries(
        root, batch["entries"], do_one, "Video"
    )
    if remaining:
        if ok:
            batch["entries"] = remaining
            log.flush()
        print("Skipped or failed entries remain in the journal; resolve them and retry.")
    else:
        log.drop_batch(index)
        print("Rolled-back batch records were removed from the journal.")
