"""AcoustID fingerprinting and MusicBrainz metadata lookup."""

from __future__ import annotations

from undisorder.audio_metadata import AudioMetadata

import acoustid
import musicbrainzngs
import pathlib


musicbrainzngs.set_useragent("undisorder", "0.1.0", "https://github.com/undisorder")


def fingerprint_audio(path: pathlib.Path) -> tuple[float, str] | None:
    """Compute a local audio fingerprint via fpcalc (no network).

    Returns (duration, fingerprint) or None on failure.
    """
    try:
        duration, fingerprint = acoustid.fingerprint_file(str(path))
        return (duration, fingerprint)
    except Exception:
        return None


def lookup_acoustid(
    fingerprint: str, duration: float, *, api_key: str | None,
) -> str | None:
    """Query the AcoustID API with a fingerprint to get a MusicBrainz recording ID."""
    if api_key is None:
        return None
    try:
        response = acoustid.lookup(api_key, fingerprint, duration, meta="recordings")
        results = response.get("results", [])
        if not results:
            return None
        recordings = results[0].get("recordings", [])
        if not recordings:
            return None
        return recordings[0].get("id")
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
    file_hash: str | None = None,
    db=None,
) -> AudioMetadata:
    """Identify an audio file: if tags are incomplete, try AcoustID + MusicBrainz.

    Merges results, preserving existing tag data over lookup data.
    Uses cache (via db) when file_hash is provided.
    """
    if api_key is None:
        return existing_meta

    # 1. Cache check
    if db is not None and file_hash is not None:
        cached = db.get_acoustid_cache(file_hash)
        if cached is not None:
            lookup_meta = AudioMetadata(
                source_path=pathlib.Path(""),
                artist=cached["artist"],
                album=cached["album"],
                title=cached["title"],
                track_number=cached["track_number"],
                disc_number=cached["disc_number"],
                year=cached["year"],
            )
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

    # 2. Local fingerprint
    fp_result = fingerprint_audio(path)
    if fp_result is None:
        return existing_meta
    duration, fingerprint = fp_result

    # 3. AcoustID API lookup
    recording_id = lookup_acoustid(fingerprint, duration, api_key=api_key)

    # 4. MusicBrainz API lookup
    lookup_meta = None
    if recording_id is not None:
        lookup_meta = lookup_musicbrainz(recording_id)

    # 5. Store in cache
    if db is not None and file_hash is not None:
        metadata = {}
        if lookup_meta is not None:
            metadata = {
                "artist": lookup_meta.artist,
                "album": lookup_meta.album,
                "title": lookup_meta.title,
                "track_number": lookup_meta.track_number,
                "disc_number": lookup_meta.disc_number,
                "year": lookup_meta.year,
            }
        db.store_acoustid_cache(
            file_hash=file_hash,
            fingerprint=fingerprint,
            duration=duration,
            recording_id=recording_id,
            metadata=metadata,
        )

    # 6. Merge with existing
    if lookup_meta is None:
        return existing_meta

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
