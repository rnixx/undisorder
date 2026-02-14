"""2-phase duplicate detection: file size grouping, then SHA256 hashing."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import hashlib
import pathlib


@dataclass
class DuplicateGroup:
    """A group of files with identical content."""

    hash: str
    file_size: int
    paths: list[pathlib.Path]


def hash_file(path: pathlib.Path, chunk_size: int = 8192) -> str:
    """Compute SHA256 hash of a file."""
    sha = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            sha.update(chunk)
    return sha.hexdigest()


def find_duplicates(paths: list[pathlib.Path]) -> list[DuplicateGroup]:
    """Find duplicate files using 2-phase detection.

    Phase 1: Group files by size (cheap).
    Phase 2: For same-size groups, compute SHA256 and group by hash.
    """
    if not paths:
        return []

    # Phase 1: group by file size
    size_groups: dict[int, list[pathlib.Path]] = defaultdict(list)
    for p in paths:
        size_groups[p.stat().st_size].append(p)

    # Phase 2: hash only same-size groups
    duplicates: list[DuplicateGroup] = []
    for size, group in size_groups.items():
        if len(group) < 2:
            continue

        hash_groups: dict[str, list[pathlib.Path]] = defaultdict(list)
        for p in group:
            h = hash_file(p)
            hash_groups[h].append(p)

        for h, files in hash_groups.items():
            if len(files) >= 2:
                duplicates.append(DuplicateGroup(hash=h, file_size=size, paths=files))

    return duplicates
