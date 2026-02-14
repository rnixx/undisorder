"""AcoustID fingerprinting and MusicBrainz metadata lookup."""

from __future__ import annotations

import pathlib

import acoustid
import musicbrainzngs

from undisorder.audio_metadata import AudioMetadata

musicbrainzngs.set_useragent("undisorder", "0.1.0", "https://github.com/undisorder")


def lookup_acoustid(path: pathlib.Path, *, api_key: str | None) -> str | None:
    """Fingerprint a file and query AcoustID for a MusicBrainz recording ID."""
    if api_key is None:
        return None
    try:
        for recording_id, _title, _artist, _album, _extra in acoustid.match(api_key, str(path)):
            return recording_id
    except Exception:
        return None


def lookup_musicbrainz(recording_id: str) -> AudioMetadata | None:
    """Look up full metadata from MusicBrainz by recording ID."""
    try:
        result = musicbrainzngs.get_recording_by_id(
            recording_id, includes=["artists", "releases"]
        )
    except Exception:
        return None

    rec = result.get("recording", {})
    title = rec.get("title")

    artist = None
    artist_credit = rec.get("artist-credit", [])
    if artist_credit:
        artist = artist_credit[0].get("artist", {}).get("name")

    album = None
    year = None
    track_number = None
    disc_number = None

    releases = rec.get("release-list", [])
    if releases:
        release = releases[0]
        album = release.get("title")
        date_str = release.get("date", "")
        if date_str and len(date_str) >= 4:
            try:
                year = int(date_str[:4])
            except ValueError:
                pass

        # Extract track/disc number from medium-list
        media = release.get("medium-list", [])
        if media:
            medium = media[0]
            try:
                disc_number = int(medium.get("position", 0)) or None
            except (ValueError, TypeError):
                pass
            tracks = medium.get("track-list", [])
            if tracks:
                try:
                    track_number = int(tracks[0].get("position", 0)) or None
                except (ValueError, TypeError):
                    pass

    return AudioMetadata(
        source_path=pathlib.Path(""),
        artist=artist,
        album=album,
        title=title,
        track_number=track_number,
        disc_number=disc_number,
        year=year,
    )


def identify_audio(
    path: pathlib.Path,
    existing_meta: AudioMetadata,
    *,
    api_key: str | None,
) -> AudioMetadata:
    """Identify an audio file: if tags are incomplete, try AcoustID + MusicBrainz.

    Merges results, preserving existing tag data over lookup data.
    """
    if api_key is None:
        return existing_meta

    recording_id = lookup_acoustid(path, api_key=api_key)
    if recording_id is None:
        return existing_meta

    lookup_meta = lookup_musicbrainz(recording_id)
    if lookup_meta is None:
        return existing_meta

    # Merge: existing fields take priority
    return AudioMetadata(
        source_path=existing_meta.source_path,
        artist=existing_meta.artist or lookup_meta.artist,
        album=existing_meta.album or lookup_meta.album,
        title=existing_meta.title or lookup_meta.title,
        track_number=existing_meta.track_number or lookup_meta.track_number,
        disc_number=existing_meta.disc_number or lookup_meta.disc_number,
        year=existing_meta.year or lookup_meta.year,
        genre=existing_meta.genre,
    )
