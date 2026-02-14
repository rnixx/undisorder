"""File discovery and photo/video/audio classification."""

from __future__ import annotations

import enum
import pathlib
from dataclasses import dataclass, field

PHOTO_EXTENSIONS: set[str] = {
    ".jpg", ".jpeg", ".png", ".tiff", ".tif",
    ".heic", ".heif", ".webp", ".bmp",
    # RAW formats
    ".cr2", ".cr3", ".nef", ".arw", ".orf",
    ".raf", ".rw2", ".dng", ".pef", ".srw",
}

VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mov", ".avi", ".mkv", ".mts",
    ".m2ts", ".wmv", ".flv", ".webm", ".3gp",
    ".m4v", ".mpg", ".mpeg", ".vob",
}

AUDIO_EXTENSIONS: set[str] = {
    ".mp3", ".flac", ".ogg", ".opus", ".m4a",
    ".aac", ".wma", ".wav", ".aiff", ".ape",
    ".mpc", ".wv", ".tta",
}


class FileType(enum.Enum):
    """Classification of a file."""

    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    UNKNOWN = "unknown"


@dataclass
class ScanResult:
    """Result of scanning a directory."""

    photos: list[pathlib.Path] = field(default_factory=list)
    videos: list[pathlib.Path] = field(default_factory=list)
    audios: list[pathlib.Path] = field(default_factory=list)
    unknown: list[pathlib.Path] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.photos) + len(self.videos) + len(self.audios) + len(self.unknown)

    @property
    def all_files(self) -> list[pathlib.Path]:
        return self.photos + self.videos + self.audios + self.unknown


def classify(path: pathlib.Path) -> FileType:
    """Classify a file as photo, video, audio, or unknown based on its extension."""
    ext = path.suffix.lower()
    if ext in PHOTO_EXTENSIONS:
        return FileType.PHOTO
    if ext in VIDEO_EXTENSIONS:
        return FileType.VIDEO
    if ext in AUDIO_EXTENSIONS:
        return FileType.AUDIO
    return FileType.UNKNOWN


def scan(directory: pathlib.Path) -> ScanResult:
    """Recursively scan a directory and classify all files.

    Skips hidden files and directories (names starting with '.').
    """
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    result = ScanResult()
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        # Skip hidden files and files inside hidden directories
        rel = path.relative_to(directory)
        if any(part.startswith(".") for part in rel.parts):
            continue

        file_type = classify(path)
        if file_type is FileType.PHOTO:
            result.photos.append(path)
        elif file_type is FileType.VIDEO:
            result.videos.append(path)
        elif file_type is FileType.AUDIO:
            result.audios.append(path)
        else:
            result.unknown.append(path)

    return result
