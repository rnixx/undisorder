"""Sorting logic with intelligent directory naming."""

from __future__ import annotations

from undisorder.audio_metadata import AudioMetadata
from undisorder.metadata import Metadata

import pathlib
import re


# Directory names that are generic and not meaningful for organization
_GENERIC_NAMES: set[str] = {
    "dcim", "camera", "img", "image", "images",
    "download", "downloads",
    "backup", "backups",
    "temp", "tmp",
    "pictures", "photos", "fotos", "bilder",
    "videos", "movies", "clips",
    "desktop", "documents",
    "misc", "miscellaneous", "various",
    "untitled", "new folder", "neuer ordner",
    "export", "output", "import",
    "sd card", "sdcard", "usb",
    "iphone", "android", "samsung",
    "whatsapp images", "whatsapp video",
}

# Camera subfolder patterns like 100APPLE, 101_PANA, 100CANON
_CAMERA_FOLDER_RE = re.compile(r"^\d{3}[A-Z_]", re.IGNORECASE)


def is_meaningful_dirname(name: str) -> bool:
    """Check if a directory name is meaningful (not generic)."""
    if not name or not name.strip():
        return False
    if name.lower() in _GENERIC_NAMES:
        return False
    if _CAMERA_FOLDER_RE.match(name):
        return False
    return True


def _get_meaningful_source_dir(
    source_path: pathlib.Path,
    source_root: pathlib.Path | None = None,
) -> str | None:
    """Extract a meaningful directory name from the source path.

    When source_root is set, walks up from source_path.parent to source_root,
    returning the first meaningful directory name found. Stops at source_root.
    Without source_root, only checks the immediate parent (legacy behavior).
    """
    if source_root is None:
        parent = source_path.parent.name
        if is_meaningful_dirname(parent):
            return parent
        return None

    current = source_path.parent
    while current != source_root and current != current.parent:
        if is_meaningful_dirname(current.name):
            return current.name
        current = current.parent
    return None


def suggest_dirname(meta: Metadata, *, source_root: pathlib.Path | None = None) -> str:
    """Suggest a target directory name based on metadata.

    Priority order:
    1. Source directory name (if meaningful)
    2. Fallback: YYYY/YYYY-MM
    """
    # Determine the date prefix
    if meta.date_taken:
        year = str(meta.date_taken.year)
        month = f"{meta.date_taken.year}-{meta.date_taken.month:02d}"
        date_prefix = f"{year}/{month}"
    else:
        date_prefix = None

    # Try to find a topic name from source directory
    topic = _get_meaningful_source_dir(meta.source_path, source_root=source_root)

    # Build path
    if date_prefix and topic:
        return f"{date_prefix}_{topic}"
    if date_prefix:
        return date_prefix
    if topic:
        return f"unknown_date/{topic}"
    return "unknown_date"


def resolve_collision(target: pathlib.Path) -> pathlib.Path:
    """Resolve filename collision by appending _1, _2, etc."""
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    parent = target.parent

    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _sanitize_path_component(name: str) -> str:
    """Sanitize a string for use as a directory or file name component."""
    # Replace path separators and other problematic characters
    name = re.sub(r'[/\\:*?"<>|]', "_", name)
    return name.strip()


def determine_target_path(
    *,
    meta: Metadata,
    images_target: pathlib.Path,
    video_target: pathlib.Path,
    is_video: bool,
    source_root: pathlib.Path | None = None,
) -> pathlib.Path:
    """Determine the full target path for a file."""
    base_target = video_target if is_video else images_target
    dirname = suggest_dirname(meta, source_root=source_root)
    filename = meta.source_path.name
    return base_target / dirname / filename


def determine_audio_target_path(
    meta: AudioMetadata,
    audio_target: pathlib.Path,
) -> pathlib.Path:
    """Determine the full target path for an audio file.

    Layout: audio_target/Artist/Album/NN_Title.ext
    """
    artist = _sanitize_path_component(meta.artist) if meta.artist else "Unknown Artist"
    album = _sanitize_path_component(meta.album) if meta.album else "Unknown Album"

    ext = meta.source_path.suffix

    if meta.track_number is not None and meta.title is not None:
        title = _sanitize_path_component(meta.title)
        filename = f"{meta.track_number:02d}_{title}{ext}"
    else:
        filename = meta.source_path.name

    return audio_target / artist / album / filename
