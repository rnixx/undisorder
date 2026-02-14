"""Tests for undisorder.organizer — sorting logic with intelligent directory naming."""

import datetime
import pathlib

import pytest

from undisorder.audio_metadata import AudioMetadata
from undisorder.metadata import Metadata
from undisorder.organizer import (
    determine_audio_target_path,
    determine_target_path,
    is_meaningful_dirname,
    resolve_collision,
    suggest_dirname,
)


class TestIsMeaningfulDirname:
    """Test filtering of generic/meaningless directory names."""

    def test_dcim_not_meaningful(self):
        assert is_meaningful_dirname("DCIM") is False

    def test_camera_not_meaningful(self):
        assert is_meaningful_dirname("Camera") is False

    def test_img_not_meaningful(self):
        assert is_meaningful_dirname("IMG") is False

    def test_download_not_meaningful(self):
        assert is_meaningful_dirname("Download") is False

    def test_downloads_not_meaningful(self):
        assert is_meaningful_dirname("Downloads") is False

    def test_backup_not_meaningful(self):
        assert is_meaningful_dirname("Backup") is False

    def test_temp_not_meaningful(self):
        assert is_meaningful_dirname("temp") is False

    def test_tmp_not_meaningful(self):
        assert is_meaningful_dirname("tmp") is False

    def test_pictures_not_meaningful(self):
        assert is_meaningful_dirname("Pictures") is False

    def test_photos_not_meaningful(self):
        assert is_meaningful_dirname("Photos") is False

    def test_meaningful_name(self):
        assert is_meaningful_dirname("Geburtstag-Oma") is True

    def test_meaningful_vacation(self):
        assert is_meaningful_dirname("Urlaub-Kroatien-2024") is True

    def test_case_insensitive(self):
        assert is_meaningful_dirname("dcim") is False
        assert is_meaningful_dirname("DOWNLOADS") is False

    def test_100apple_not_meaningful(self):
        """Camera subfolder pattern like 100APPLE, 101_PANA."""
        assert is_meaningful_dirname("100APPLE") is False

    def test_misc_not_meaningful(self):
        assert is_meaningful_dirname("misc") is False

    def test_new_folder_not_meaningful(self):
        assert is_meaningful_dirname("New folder") is False

    def test_empty_not_meaningful(self):
        assert is_meaningful_dirname("") is False


class TestSuggestDirname:
    """Test directory name suggestion logic."""

    def test_date_only_fallback(self):
        meta = Metadata(
            source_path=pathlib.Path("/source/DCIM/photo.jpg"),
            date_taken=datetime.datetime(2024, 3, 15),
        )
        assert suggest_dirname(meta) == "2024/2024-03"

    def test_meaningful_source_dir(self):
        meta = Metadata(
            source_path=pathlib.Path("/source/Geburtstag-Oma/photo.jpg"),
            date_taken=datetime.datetime(2024, 3, 15),
        )
        assert suggest_dirname(meta) == "2024/2024-03_Geburtstag-Oma"

    def test_keywords_used_when_no_meaningful_dir(self):
        meta = Metadata(
            source_path=pathlib.Path("/source/DCIM/photo.jpg"),
            date_taken=datetime.datetime(2024, 6, 20),
            keywords=["vacation", "beach"],
        )
        assert suggest_dirname(meta) == "2024/2024-06_vacation"

    def test_description_used_as_fallback(self):
        meta = Metadata(
            source_path=pathlib.Path("/source/DCIM/photo.jpg"),
            date_taken=datetime.datetime(2024, 1, 10),
            description="A winter hike in the mountains",
        )
        result = suggest_dirname(meta)
        assert result.startswith("2024/2024-01_")
        # Should contain first few words of description
        assert "winter" in result.lower() or "hike" in result.lower()

    def test_gps_place_name(self):
        meta = Metadata(
            source_path=pathlib.Path("/source/DCIM/photo.jpg"),
            date_taken=datetime.datetime(2024, 3, 15),
            gps_lat=48.2082,
            gps_lon=16.3738,
        )
        # With a place name provided
        assert suggest_dirname(meta, place_name="Wien") == "2024/2024-03_Wien"

    def test_no_date_uses_unknown(self):
        meta = Metadata(source_path=pathlib.Path("/source/DCIM/photo.jpg"))
        assert suggest_dirname(meta) == "unknown_date"

    def test_no_date_with_meaningful_dir(self):
        meta = Metadata(
            source_path=pathlib.Path("/source/Hochzeit/photo.jpg"),
        )
        assert suggest_dirname(meta) == "unknown_date/Hochzeit"

    def test_priority_source_dir_over_keywords(self):
        """Source directory name takes priority over keywords."""
        meta = Metadata(
            source_path=pathlib.Path("/source/Hochzeit/photo.jpg"),
            date_taken=datetime.datetime(2024, 7, 1),
            keywords=["party"],
        )
        assert suggest_dirname(meta) == "2024/2024-07_Hochzeit"

    def test_subject_used_like_keywords(self):
        meta = Metadata(
            source_path=pathlib.Path("/source/DCIM/photo.jpg"),
            date_taken=datetime.datetime(2024, 8, 5),
            subject=["concert"],
        )
        assert suggest_dirname(meta) == "2024/2024-08_concert"


class TestResolveCollision:
    """Test filename collision resolution."""

    def test_no_collision(self, tmp_path: pathlib.Path):
        target = tmp_path / "photo.jpg"
        assert resolve_collision(target) == target

    def test_single_collision(self, tmp_path: pathlib.Path):
        existing = tmp_path / "photo.jpg"
        existing.write_bytes(b"x")
        result = resolve_collision(existing)
        assert result == tmp_path / "photo_1.jpg"

    def test_multiple_collisions(self, tmp_path: pathlib.Path):
        (tmp_path / "photo.jpg").write_bytes(b"x")
        (tmp_path / "photo_1.jpg").write_bytes(b"x")
        result = resolve_collision(tmp_path / "photo.jpg")
        assert result == tmp_path / "photo_2.jpg"

    def test_preserves_extension(self, tmp_path: pathlib.Path):
        (tmp_path / "video.mp4").write_bytes(b"x")
        result = resolve_collision(tmp_path / "video.mp4")
        assert result.suffix == ".mp4"
        assert result.stem == "video_1"


class TestDetermineTargetPath:
    """Test full target path determination."""

    def test_photo_goes_to_images_target(self, tmp_path: pathlib.Path):
        meta = Metadata(
            source_path=pathlib.Path("/source/photo.jpg"),
            date_taken=datetime.datetime(2024, 3, 15),
        )
        result = determine_target_path(
            meta=meta,
            images_target=tmp_path / "Fotos",
            video_target=tmp_path / "Videos",
            is_video=False,
        )
        assert str(result).startswith(str(tmp_path / "Fotos"))

    def test_video_goes_to_video_target(self, tmp_path: pathlib.Path):
        meta = Metadata(
            source_path=pathlib.Path("/source/clip.mp4"),
            date_taken=datetime.datetime(2024, 3, 15),
        )
        result = determine_target_path(
            meta=meta,
            images_target=tmp_path / "Fotos",
            video_target=tmp_path / "Videos",
            is_video=True,
        )
        assert str(result).startswith(str(tmp_path / "Videos"))

    def test_includes_original_filename(self, tmp_path: pathlib.Path):
        meta = Metadata(
            source_path=pathlib.Path("/source/DSC_1234.jpg"),
            date_taken=datetime.datetime(2024, 3, 15),
        )
        result = determine_target_path(
            meta=meta,
            images_target=tmp_path / "Fotos",
            video_target=tmp_path / "Videos",
            is_video=False,
        )
        assert result.name == "DSC_1234.jpg"


class TestDetermineAudioTargetPath:
    """Test audio file target path determination."""

    def test_full_metadata(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/song.mp3"),
            artist="The Beatles",
            album="Abbey Road",
            title="Come Together",
            track_number=1,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert result == tmp_path / "Musik" / "The Beatles" / "Abbey Road" / "01_Come Together.mp3"

    def test_two_digit_track_number(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/track.flac"),
            artist="Artist",
            album="Album",
            title="Track",
            track_number=12,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert result.name == "12_Track.flac"

    def test_no_artist_uses_unknown(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/song.mp3"),
            artist=None,
            album="Album",
            title="Song",
            track_number=1,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert "Unknown Artist" in str(result)

    def test_no_album_uses_unknown(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/song.mp3"),
            artist="Artist",
            album=None,
            title="Song",
            track_number=1,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert "Unknown Album" in str(result)

    def test_no_track_number_keeps_original_name(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/song.mp3"),
            artist="Artist",
            album="Album",
            title="Song",
            track_number=None,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert result.name == "song.mp3"

    def test_no_title_keeps_original_name(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/song.mp3"),
            artist="Artist",
            album="Album",
            title=None,
            track_number=5,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert result.name == "song.mp3"

    def test_all_missing_uses_fallbacks(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/unknown_file.mp3"),
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert result == tmp_path / "Musik" / "Unknown Artist" / "Unknown Album" / "unknown_file.mp3"

    def test_sanitizes_filename(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/song.mp3"),
            artist="AC/DC",
            album="Back in Black",
            title="You Shook Me All Night Long",
            track_number=6,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        # Should not contain path separators in components
        assert "/" not in result.parent.name  # album dir
        # Artist dir should have slash replaced
        artist_dir = result.parent.parent.name
        assert "/" not in artist_dir

    def test_preserves_extension(self, tmp_path: pathlib.Path):
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/track.flac"),
            artist="Artist",
            album="Album",
            title="Track",
            track_number=1,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert result.suffix == ".flac"

    def test_disc_number_not_in_path(self, tmp_path: pathlib.Path):
        """Disc number is metadata-only, not used in path."""
        meta = AudioMetadata(
            source_path=pathlib.Path("/source/song.mp3"),
            artist="Artist",
            album="Album",
            title="Song",
            track_number=1,
            disc_number=2,
        )
        result = determine_audio_target_path(meta, tmp_path / "Musik")
        assert result == tmp_path / "Musik" / "Artist" / "Album" / "01_Song.mp3"
