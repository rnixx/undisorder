"""File filtering and interactive directory selection."""

from __future__ import annotations

import fnmatch
import pathlib
from dataclasses import dataclass

from undisorder.scanner import ScanResult, classify, FileType


@dataclass
class DirectoryGroup:
    """A group of files in the same directory."""

    rel_path: pathlib.PurePosixPath
    files: list[pathlib.Path]
    photo_count: int
    video_count: int
    audio_count: int
    unknown_count: int
    total_size: int


def _matches_any(name: str, patterns: list[str]) -> bool:
    """Check if name matches any of the glob patterns (case-insensitive)."""
    name_lower = name.lower()
    return any(fnmatch.fnmatch(name_lower, p.lower()) for p in patterns)


def _is_excluded(
    path: pathlib.Path,
    source_root: pathlib.Path,
    exclude_file: list[str],
    exclude_dir: list[str],
) -> bool:
    """Check if a file should be excluded by file or directory patterns."""
    if exclude_file and _matches_any(path.name, exclude_file):
        return True
    if exclude_dir:
        rel = path.relative_to(source_root)
        for part in rel.parent.parts:
            if _matches_any(part, exclude_dir):
                return True
    return False


def apply_exclude_patterns(
    result: ScanResult,
    source_root: pathlib.Path,
    *,
    exclude_file: list[str],
    exclude_dir: list[str],
) -> ScanResult:
    """Filter files matching exclude globs. Returns a new ScanResult."""

    def keep(path: pathlib.Path) -> bool:
        return not _is_excluded(path, source_root, exclude_file, exclude_dir)

    return ScanResult(
        photos=[p for p in result.photos if keep(p)],
        videos=[p for p in result.videos if keep(p)],
        audios=[p for p in result.audios if keep(p)],
        unknown=[p for p in result.unknown if keep(p)],
    )


def group_by_directory(
    result: ScanResult, source_root: pathlib.Path,
) -> list[DirectoryGroup]:
    """Group all files by parent directory relative to source root."""
    all_files = result.photos + result.videos + result.audios + result.unknown
    if not all_files:
        return []

    groups: dict[pathlib.PurePosixPath, list[pathlib.Path]] = {}
    for f in all_files:
        rel = f.relative_to(source_root)
        parent = pathlib.PurePosixPath(str(rel.parent)) if rel.parent != pathlib.PurePosixPath() else pathlib.PurePosixPath(".")
        groups.setdefault(parent, []).append(f)

    result_groups = []
    for rel_path in sorted(groups):
        files = groups[rel_path]
        photo_count = 0
        video_count = 0
        audio_count = 0
        unknown_count = 0
        total_size = 0
        for f in files:
            ft = classify(f)
            if ft is FileType.PHOTO:
                photo_count += 1
            elif ft is FileType.VIDEO:
                video_count += 1
            elif ft is FileType.AUDIO:
                audio_count += 1
            else:
                unknown_count += 1
            total_size += f.stat().st_size
        result_groups.append(DirectoryGroup(
            rel_path=rel_path,
            files=files,
            photo_count=photo_count,
            video_count=video_count,
            audio_count=audio_count,
            unknown_count=unknown_count,
            total_size=total_size,
        ))

    return result_groups


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.1f} GB"


def format_group_summary(group: DirectoryGroup) -> str:
    """Format a directory group as a human-readable summary line."""
    parts = []
    if group.photo_count:
        parts.append(f"{group.photo_count} photo{'s' if group.photo_count != 1 else ''}")
    if group.video_count:
        parts.append(f"{group.video_count} video{'s' if group.video_count != 1 else ''}")
    if group.audio_count:
        parts.append(f"{group.audio_count} audio")
    if group.unknown_count:
        parts.append(f"{group.unknown_count} unknown")
    counts = ", ".join(parts)
    return f"{group.rel_path}/  ({counts}, {format_size(group.total_size)})"


def interactive_select(
    groups: list[DirectoryGroup],
    source_root: pathlib.Path,
    *,
    input_fn=input,
    print_fn=print,
) -> set[pathlib.PurePosixPath]:
    """Interactively prompt user to accept/skip each directory group.

    Returns set of accepted directory relative paths.
    Raises KeyboardInterrupt on quit.
    """
    accepted: set[pathlib.PurePosixPath] = set()

    for i, group in enumerate(groups):
        print_fn(f"  {format_group_summary(group)}")

        while True:
            choice = input_fn("  [y] accept  [n] skip  [l] list  [a] all  [q] quit: ").strip().lower()

            if choice == "y":
                accepted.add(group.rel_path)
                break
            elif choice == "n":
                break
            elif choice == "a":
                accepted.add(group.rel_path)
                for remaining in groups[i + 1:]:
                    accepted.add(remaining.rel_path)
                return accepted
            elif choice == "q":
                raise KeyboardInterrupt
            elif choice == "l":
                for f in group.files:
                    print_fn(f"    {f.name}")
            # invalid input: loop again

        print_fn("")

    return accepted


def filter_scan_result(
    result: ScanResult,
    source_root: pathlib.Path,
    accepted_dirs: set[pathlib.PurePosixPath],
) -> ScanResult:
    """Keep only files whose parent directory is in accepted_dirs."""

    def is_accepted(path: pathlib.Path) -> bool:
        rel = path.relative_to(source_root)
        parent = pathlib.PurePosixPath(str(rel.parent)) if rel.parent != pathlib.PurePosixPath() else pathlib.PurePosixPath(".")
        return parent in accepted_dirs

    return ScanResult(
        photos=[p for p in result.photos if is_accepted(p)],
        videos=[p for p in result.videos if is_accepted(p)],
        audios=[p for p in result.audios if is_accepted(p)],
        unknown=[p for p in result.unknown if is_accepted(p)],
    )
