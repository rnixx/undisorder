"""Audio tag extraction via mutagen."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

import mutagen


@dataclass
class AudioMetadata:
    """Extracted metadata for a single audio file."""

    source_path: pathlib.Path
    artist: str | None = None
    album: str | None = None
    title: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    year: int | None = None
    genre: str | None = None


def _parse_int_field(value: str) -> int | None:
    """Parse an integer from a tag value like '3' or '3/12'."""
    try:
        return int(value.split("/")[0])
    except (ValueError, IndexError):
        return None


def _parse_year(value: str) -> int | None:
    """Parse a year from a date string like '2024' or '2024-03-15'."""
    try:
        return int(value[:4])
    except (ValueError, IndexError):
        return None


def _get_tag(tags: mutagen.FileType, key: str) -> str | None:
    """Get first value of a tag, or None if missing."""
    if key in tags:
        values = tags[key]
        if values:
            return str(values[0])
    return None


def extract_audio(path: pathlib.Path) -> AudioMetadata:
    """Extract metadata from a single audio file using mutagen."""
    meta = AudioMetadata(source_path=path)
    try:
        tags = mutagen.File(path, easy=True)
    except Exception:
        return meta

    if tags is None:
        return meta

    meta.artist = _get_tag(tags, "artist")
    meta.album = _get_tag(tags, "album")
    meta.title = _get_tag(tags, "title")
    meta.genre = _get_tag(tags, "genre")

    raw_track = _get_tag(tags, "tracknumber")
    if raw_track is not None:
        meta.track_number = _parse_int_field(raw_track)

    raw_disc = _get_tag(tags, "discnumber")
    if raw_disc is not None:
        meta.disc_number = _parse_int_field(raw_disc)

    raw_date = _get_tag(tags, "date")
    if raw_date is not None:
        meta.year = _parse_year(raw_date)

    return meta


def extract_audio_batch(paths: list[pathlib.Path]) -> dict[pathlib.Path, AudioMetadata]:
    """Extract metadata from multiple audio files."""
    if not paths:
        return {}
    return {p: extract_audio(p) for p in paths}
