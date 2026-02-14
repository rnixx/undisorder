"""Tests for undisorder.musicbrainz — AcoustID + MusicBrainz lookup."""

from undisorder.audio_metadata import AudioMetadata
from undisorder.musicbrainz import identify_audio
from undisorder.musicbrainz import lookup_acoustid
from undisorder.musicbrainz import lookup_musicbrainz
from unittest.mock import patch

import pathlib


class TestLookupAcoustid:
    """Test AcoustID fingerprint lookup."""

    def test_returns_recording_id(self):
        with patch("undisorder.musicbrainz.acoustid.match", return_value=iter([
            ("mb-recording-456", "Title", "Artist", "Album", None),
        ])):
            result = lookup_acoustid(pathlib.Path("/fake/song.mp3"), api_key="test-key")
        assert result == "mb-recording-456"

    def test_returns_none_without_api_key(self):
        result = lookup_acoustid(pathlib.Path("/fake/song.mp3"), api_key=None)
        assert result is None

    def test_returns_none_on_no_results(self):
        with patch("undisorder.musicbrainz.acoustid.match", return_value=iter([])):
            result = lookup_acoustid(pathlib.Path("/fake/song.mp3"), api_key="test-key")
        assert result is None

    def test_returns_none_on_exception(self):
        with patch("undisorder.musicbrainz.acoustid.match", side_effect=Exception("network error")):
            result = lookup_acoustid(pathlib.Path("/fake/song.mp3"), api_key="test-key")
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
            patch("undisorder.musicbrainz.lookup_acoustid", return_value="rec-id"),
            patch("undisorder.musicbrainz.lookup_musicbrainz", return_value=lookup_meta),
        ):
            result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key="key")
        assert result.artist == "My Artist"  # preserved
        assert result.album == "Lookup Album"  # filled
        assert result.title == "Lookup Title"  # filled

    def test_returns_existing_when_acoustid_fails(self):
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        with patch("undisorder.musicbrainz.lookup_acoustid", return_value=None):
            result = identify_audio(pathlib.Path("/fake/song.mp3"), existing, api_key="key")
        assert result is existing

    def test_returns_existing_when_musicbrainz_fails(self):
        existing = AudioMetadata(
            source_path=pathlib.Path("/fake/song.mp3"),
            artist=None,
        )
        with (
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
