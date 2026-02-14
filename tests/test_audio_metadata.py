"""Tests for undisorder.audio_metadata — audio tag extraction via mutagen."""

import pathlib
from unittest.mock import MagicMock, patch

import pytest

from undisorder.audio_metadata import AudioMetadata, extract_audio, extract_audio_batch


class TestAudioMetadataDataclass:
    """Test the AudioMetadata dataclass itself."""

    def test_defaults(self):
        m = AudioMetadata(source_path=pathlib.Path("song.mp3"))
        assert m.artist is None
        assert m.album is None
        assert m.title is None
        assert m.track_number is None
        assert m.disc_number is None
        assert m.year is None
        assert m.genre is None

    def test_all_fields(self):
        m = AudioMetadata(
            source_path=pathlib.Path("song.mp3"),
            artist="Artist",
            album="Album",
            title="Title",
            track_number=3,
            disc_number=1,
            year=2024,
            genre="Rock",
        )
        assert m.artist == "Artist"
        assert m.album == "Album"
        assert m.title == "Title"
        assert m.track_number == 3
        assert m.disc_number == 1
        assert m.year == 2024
        assert m.genre == "Rock"


class TestExtractAudio:
    """Test single-file audio metadata extraction."""

    def test_extracts_mp3_id3_tags(self):
        mock_file = MagicMock()
        mock_file.__getitem__ = lambda self, key: {
            "artist": ["The Beatles"],
            "album": ["Abbey Road"],
            "title": ["Come Together"],
            "tracknumber": ["1/17"],
            "discnumber": ["1/1"],
            "date": ["1969"],
            "genre": ["Rock"],
        }[key]
        mock_file.__contains__ = lambda self, key: key in {
            "artist", "album", "title", "tracknumber", "discnumber", "date", "genre"
        }
        with patch("undisorder.audio_metadata.mutagen.File", return_value=mock_file):
            m = extract_audio(pathlib.Path("/fake/song.mp3"))
        assert m.artist == "The Beatles"
        assert m.album == "Abbey Road"
        assert m.title == "Come Together"
        assert m.track_number == 1
        assert m.disc_number == 1
        assert m.year == 1969
        assert m.genre == "Rock"

    def test_extracts_flac_vorbis_tags(self):
        mock_file = MagicMock()
        mock_file.__getitem__ = lambda self, key: {
            "artist": ["Pink Floyd"],
            "album": ["The Dark Side of the Moon"],
            "title": ["Time"],
            "tracknumber": ["4"],
            "date": ["1973"],
        }[key]
        mock_file.__contains__ = lambda self, key: key in {
            "artist", "album", "title", "tracknumber", "date"
        }
        with patch("undisorder.audio_metadata.mutagen.File", return_value=mock_file):
            m = extract_audio(pathlib.Path("/fake/track.flac"))
        assert m.artist == "Pink Floyd"
        assert m.album == "The Dark Side of the Moon"
        assert m.title == "Time"
        assert m.track_number == 4
        assert m.year == 1973
        assert m.disc_number is None
        assert m.genre is None

    def test_extracts_m4a_mp4_tags(self):
        mock_file = MagicMock()
        mock_file.__getitem__ = lambda self, key: {
            "artist": ["Radiohead"],
            "album": ["OK Computer"],
            "title": ["Paranoid Android"],
            "tracknumber": ["2"],
            "date": ["1997"],
            "genre": ["Alternative Rock"],
        }[key]
        mock_file.__contains__ = lambda self, key: key in {
            "artist", "album", "title", "tracknumber", "date", "genre"
        }
        with patch("undisorder.audio_metadata.mutagen.File", return_value=mock_file):
            m = extract_audio(pathlib.Path("/fake/song.m4a"))
        assert m.artist == "Radiohead"
        assert m.album == "OK Computer"
        assert m.title == "Paranoid Android"
        assert m.track_number == 2
        assert m.year == 1997

    def test_handles_missing_tags(self):
        mock_file = MagicMock()
        mock_file.__getitem__ = lambda self, key: {"artist": ["Unknown"]}[key]
        mock_file.__contains__ = lambda self, key: key in {"artist"}
        with patch("undisorder.audio_metadata.mutagen.File", return_value=mock_file):
            m = extract_audio(pathlib.Path("/fake/song.mp3"))
        assert m.artist == "Unknown"
        assert m.album is None
        assert m.title is None
        assert m.track_number is None

    def test_handles_unreadable_file(self):
        with patch("undisorder.audio_metadata.mutagen.File", return_value=None):
            m = extract_audio(pathlib.Path("/fake/corrupt.mp3"))
        assert m.artist is None
        assert m.album is None
        assert m.title is None

    def test_handles_mutagen_exception(self):
        with patch("undisorder.audio_metadata.mutagen.File", side_effect=Exception("bad file")):
            m = extract_audio(pathlib.Path("/fake/bad.mp3"))
        assert m.artist is None
        assert m.album is None

    def test_track_number_slash_format(self):
        """Track numbers like '3/12' should extract just the number."""
        mock_file = MagicMock()
        mock_file.__getitem__ = lambda self, key: {"tracknumber": ["3/12"]}[key]
        mock_file.__contains__ = lambda self, key: key in {"tracknumber"}
        with patch("undisorder.audio_metadata.mutagen.File", return_value=mock_file):
            m = extract_audio(pathlib.Path("/fake/song.mp3"))
        assert m.track_number == 3

    def test_track_number_plain_int(self):
        """Track numbers like '7' should work."""
        mock_file = MagicMock()
        mock_file.__getitem__ = lambda self, key: {"tracknumber": ["7"]}[key]
        mock_file.__contains__ = lambda self, key: key in {"tracknumber"}
        with patch("undisorder.audio_metadata.mutagen.File", return_value=mock_file):
            m = extract_audio(pathlib.Path("/fake/song.mp3"))
        assert m.track_number == 7

    def test_year_from_full_date(self):
        """Dates like '2024-03-15' should extract just the year."""
        mock_file = MagicMock()
        mock_file.__getitem__ = lambda self, key: {"date": ["2024-03-15"]}[key]
        mock_file.__contains__ = lambda self, key: key in {"date"}
        with patch("undisorder.audio_metadata.mutagen.File", return_value=mock_file):
            m = extract_audio(pathlib.Path("/fake/song.mp3"))
        assert m.year == 2024


class TestExtractAudioBatch:
    """Test batch audio metadata extraction."""

    def test_extracts_multiple_files(self):
        def make_mock(artist: str):
            m = MagicMock()
            m.__getitem__ = lambda self, key: {"artist": [artist]}[key]
            m.__contains__ = lambda self, key: key in {"artist"}
            return m

        mocks = {
            "/fake/a.mp3": make_mock("Artist A"),
            "/fake/b.flac": make_mock("Artist B"),
        }
        with patch("undisorder.audio_metadata.mutagen.File", side_effect=lambda p, easy: mocks[str(p)]):
            paths = [pathlib.Path("/fake/a.mp3"), pathlib.Path("/fake/b.flac")]
            results = extract_audio_batch(paths)
        assert len(results) == 2
        assert results[pathlib.Path("/fake/a.mp3")].artist == "Artist A"
        assert results[pathlib.Path("/fake/b.flac")].artist == "Artist B"

    def test_empty_list(self):
        results = extract_audio_batch([])
        assert results == {}
