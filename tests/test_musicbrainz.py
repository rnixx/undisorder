"""Tests for undisorder.musicbrainz — AcoustID + MusicBrainz lookup."""

from undisorder.audio_metadata import AudioMetadata
from undisorder.hashdb import HashDB
from undisorder.musicbrainz import fingerprint_audio
from undisorder.musicbrainz import identify_audio
from undisorder.musicbrainz import lookup_acoustid
from undisorder.musicbrainz import lookup_musicbrainz
from unittest.mock import patch

import pathlib


class TestFingerprintAudio:
    """Test local audio fingerprinting."""

    def test_returns_duration_and_fingerprint(self):
        with patch("undisorder.musicbrainz.acoustid.fingerprint_file", return_value=(240.5, "AQAA...")):
            result = fingerprint_audio(pathlib.Path("/fake/song.mp3"))
        assert result == (240.5, "AQAA...")

    def test_returns_none_on_exception(self):
        with patch("undisorder.musicbrainz.acoustid.fingerprint_file", side_effect=Exception("fpcalc not found")):
            result = fingerprint_audio(pathlib.Path("/fake/song.mp3"))
        assert result is None


class TestLookupAcoustid:
    """Test AcoustID API lookup (fingerprint → recording ID)."""

    def test_returns_recording_id(self):
        mock_response = {
            "status": "ok",
            "results": [{
                "id": "acoustid-uuid",
                "score": 0.98,
                "recordings": [{"id": "mb-recording-456"}],
            }],
        }
        with patch("undisorder.musicbrainz.acoustid.lookup", return_value=mock_response):
            result = lookup_acoustid("AQAA...", 240.5, api_key="test-key")
        assert result == "mb-recording-456"

    def test_returns_none_without_api_key(self):
        result = lookup_acoustid("AQAA...", 240.5, api_key=None)
        assert result is None

    def test_returns_none_on_no_results(self):
        mock_response = {"status": "ok", "results": []}
        with patch("undisorder.musicbrainz.acoustid.lookup", return_value=mock_response):
            result = lookup_acoustid("AQAA...", 240.5, api_key="test-key")
        assert result is None

    def test_returns_none_on_no_recordings(self):
        mock_response = {
            "status": "ok",
            "results": [{"id": "acoustid-uuid", "score": 0.5, "recordings": []}],
        }
        with patch("undisorder.musicbrainz.acoustid.lookup", return_value=mock_response):
            result = lookup_acoustid("AQAA...", 240.5, api_key="test-key")
        assert result is None

    def test_returns_none_on_exception(self):
        with patch("undisorder.musicbrainz.acoustid.lookup", side_effect=Exception("network error")):
            result = lookup_acoustid("AQAA...", 240.5, api_key="test-key")
        assert result is None


class TestLookupMusicbrainz:
    """Test MusicBrainz recording lookup."""

    def test_returns_metadata(self):
        mock_result = {
            "recording": {
                "title": "Come Together",
                "artist-credit": [
                    {"artist": {"name": "The Beatles"}}
                ],
                "release-list": [
                    {
                        "title": "Abbey Road",
                        "date": "1969-09-26",
                        "medium-list": [
                            {
                                "track-list": [
                                    {"number": "1", "recording": {"id": "rec-id"}}
                                ],
                                "position": "1",
                            }
                        ],
                    }
                ],
            }
        }
        with patch("undisorder.musicbrainz.musicbrainzngs.get_recording_by_id", return_value=mock_result):
            meta = lookup_musicbrainz("rec-id")
        assert meta is not None
        assert meta.artist == "The Beatles"
        assert meta.album == "Abbey Road"
        assert meta.title == "Come Together"
        assert meta.year == 1969

    def test_returns_none_on_not_found(self):
        with patch(
            "undisorder.musicbrainz.musicbrainzngs.get_recording_by_id",
            side_effect=Exception("not found"),
        ):
            meta = lookup_musicbrainz("nonexistent-id")
        assert meta is None

    def test_handles_missing_release_list(self):
        mock_result = {
            "recording": {
                "title": "Unknown Track",
                "artist-credit": [
                    {"artist": {"name": "Unknown Artist"}}
                ],
            }
        }
        with patch("undisorder.musicbrainz.musicbrainzngs.get_recording_by_id", return_value=mock_result):
            meta = lookup_musicbrainz("rec-id")
        assert meta is not None
        assert meta.title == "Unknown Track"
        assert meta.artist == "Unknown Artist"
        assert meta.album is None


class TestIdentifyAudio:
    """Test the orchestrator that merges tag data with lookup results."""

    def test_returns_existing_meta_when_complete(self):
        """If tags are already complete, no lookup needed."""
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist="Artist",
            album="Album",
            title="Title",
            track_number=1,
        )
        result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key=None)
        assert result.artist == "Artist"
        assert result.album == "Album"
        assert result.title == "Title"

    def test_fills_missing_fields_from_lookup(self):
        """If tags are incomplete, fill from AcoustID + MusicBrainz."""
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
            album=None,
            title=None,
        )
        lookup_meta = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist="Discovered Artist",
            album="Discovered Album",
            title="Discovered Title",
            year=2020,
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(240.0, "FP...")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value="rec-id"),
            patch("undisorder.musicbrainz.lookup_musicbrainz", return_value=lookup_meta),
        ):
            result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key="key")
        assert result.artist == "Discovered Artist"
        assert result.album == "Discovered Album"
        assert result.title == "Discovered Title"
        assert result.year == 2020

    def test_preserves_existing_over_lookup(self):
        """Existing tag data takes priority over lookup results."""
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist="My Artist",
            album=None,
            title=None,
        )
        lookup_meta = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist="Different Artist",
            album="Lookup Album",
            title="Lookup Title",
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(240.0, "FP...")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value="rec-id"),
            patch("undisorder.musicbrainz.lookup_musicbrainz", return_value=lookup_meta),
        ):
            result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key="key")
        assert result.artist == "My Artist"  # preserved
        assert result.album == "Lookup Album"  # filled
        assert result.title == "Lookup Title"  # filled

    def test_returns_existing_when_fingerprint_fails(self):
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        with patch("undisorder.musicbrainz.fingerprint_audio", return_value=None):
            result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key="key")
        assert result is existing

    def test_returns_existing_when_acoustid_fails(self):
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(240.0, "FP...")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value=None),
        ):
            result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key="key")
        assert result is existing

    def test_returns_existing_when_musicbrainz_fails(self):
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(240.0, "FP...")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value="rec-id"),
            patch("undisorder.musicbrainz.lookup_musicbrainz", return_value=None),
        ):
            result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key="key")
        assert result is existing

    def test_no_api_key_skips_lookup(self):
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key=None)
        assert result is existing


class TestIdentifyAudioCache:
    """Test AcoustID cache integration in identify_audio."""

    def test_cache_hit_skips_api_calls(self, tmp_path, tmp_target):
        """When file_hash is in cache, no fingerprinting or API calls needed."""
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        db.store_acoustid_cache(
            file_hash="cached-hash",
            fingerprint="FP...",
            duration=240.0,
            recording_id="rec-cached",
            metadata={
                "artist": "Cached Artist",
                "album": "Cached Album",
                "title": "Cached Title",
                "track_number": 3,
                "disc_number": 1,
                "year": 2020,
            },
        )

        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
            album=None,
            title=None,
        )
        with patch("undisorder.musicbrainz.fingerprint_audio") as mock_fp:
            result = identify_audio(
                pathlib.Path("/fake/song.mp3"), existing, api_key="key",
                file_hash="cached-hash", db=db,
            )
            mock_fp.assert_not_called()

        assert result.artist == "Cached Artist"
        assert result.album == "Cached Album"
        assert result.title == "Cached Title"
        assert result.track_number == 3
        assert result.year == 2020
        db.close()

    def test_cache_hit_preserves_existing(self, tmp_path, tmp_target):
        """Cached data doesn't overwrite existing tag data."""
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        db.store_acoustid_cache(
            file_hash="cached-hash",
            fingerprint="FP...",
            duration=240.0,
            recording_id="rec-cached",
            metadata={"artist": "Cached Artist", "album": "Cached Album", "title": "Cached Title"},
        )

        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist="My Artist",
            album=None,
            title=None,
        )
        result = identify_audio(
            pathlib.Path("/fake/song.mp3"), existing, api_key="key",
            file_hash="cached-hash", db=db,
        )
        assert result.artist == "My Artist"  # preserved
        assert result.album == "Cached Album"  # filled from cache
        db.close()

    def test_cache_miss_stores_result(self, tmp_path, tmp_target):
        """On cache miss, the API result is stored in cache."""
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")

        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        lookup_meta = AudioMetadata(
            source_path=pathlib.Path(""),
            artist="API Artist",
            album="API Album",
            title="API Title",
            year=2021,
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(180.0, "FP-NEW")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value="rec-new"),
            patch("undisorder.musicbrainz.lookup_musicbrainz", return_value=lookup_meta),
        ):
            identify_audio(
                pathlib.Path("/fake/song.mp3"), existing, api_key="key",
                file_hash="new-hash", db=db,
            )

        cached = db.get_acoustid_cache("new-hash")
        assert cached is not None
        assert cached["fingerprint"] == "FP-NEW"
        assert cached["duration"] == 180.0
        assert cached["recording_id"] == "rec-new"
        assert cached["artist"] == "API Artist"
        db.close()

    def test_cache_stores_on_api_failure(self, tmp_path, tmp_target):
        """On API failure (no recording_id), cache stores fingerprint with null metadata."""
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")

        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(180.0, "FP-FAIL")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value=None),
        ):
            identify_audio(
                pathlib.Path("/fake/song.mp3"), existing, api_key="key",
                file_hash="fail-hash", db=db,
            )

        cached = db.get_acoustid_cache("fail-hash")
        assert cached is not None
        assert cached["fingerprint"] == "FP-FAIL"
        assert cached["recording_id"] is None
        assert cached["artist"] is None
        db.close()

    def test_no_db_skips_caching(self):
        """Without db parameter, caching is skipped entirely."""
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        lookup_meta = AudioMetadata(
            source_path=pathlib.Path(""),
            artist="Artist",
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(180.0, "FP")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value="rec-id"),
            patch("undisorder.musicbrainz.lookup_musicbrainz", return_value=lookup_meta),
        ):
            result = identify_audio(
                pathlib.Path("/fake/song.mp3"), existing, api_key="key",
            )
        assert result.artist == "Artist"

    def test_no_file_hash_skips_cache_check(self):
        """Without file_hash, cache is not checked even with db."""
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        lookup_meta = AudioMetadata(
            source_path=pathlib.Path(""),
            artist="Artist",
        )
        with (
            patch("undisorder.musicbrainz.fingerprint_audio", return_value=(180.0, "FP")),
            patch("undisorder.musicbrainz.lookup_acoustid", return_value="rec-id"),
            patch("undisorder.musicbrainz.lookup_musicbrainz", return_value=lookup_meta),
        ):
            result = identify_audio(
                pathlib.Path("/fake/song.mp3"), existing, api_key="key",
                db=None, file_hash=None,
            )
        assert result.artist == "Artist"
