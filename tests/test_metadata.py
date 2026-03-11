"""Tests for undisorder.metadata — EXIF/metadata extraction via exiftool."""

from undisorder.metadata import extract_batch
from undisorder.metadata import Metadata
from unittest.mock import patch

import datetime
import pathlib


def _make_exiftool_result(**overrides: object) -> dict[str, object]:
    """Build a fake exiftool JSON result dict."""
    base: dict[str, object] = {"SourceFile": "/fake/photo.jpg"}
    base.update(overrides)
    return base


class TestMetadataDataclass:
    """Test the Metadata dataclass itself."""

    def test_defaults(self):
        m = Metadata(source_path=pathlib.Path("x.jpg"))
        assert m.date_taken is None
        assert m.date_from_mtime is False


class TestExtractBatchDateParsing:
    """Test date extraction logic via extract_batch."""

    def test_extracts_date_taken(self):
        raw = [
            _make_exiftool_result(**{"EXIF:DateTimeOriginal": "2024:03:15 14:30:00"})
        ]
        path = pathlib.Path("/fake/photo.jpg")
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([path])
        assert results[path].date_taken == datetime.datetime(2024, 3, 15, 14, 30, 0)

    def test_falls_back_to_createdate(self):
        raw = [_make_exiftool_result(**{"EXIF:CreateDate": "2023:12:25 10:00:00"})]
        path = pathlib.Path("/fake/photo.jpg")
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([path])
        assert results[path].date_taken == datetime.datetime(2023, 12, 25, 10, 0, 0)

    def test_falls_back_to_quicktime_createdate(self):
        raw = [_make_exiftool_result(**{"QuickTime:CreateDate": "2023:06:01 12:00:00"})]
        path = pathlib.Path("/fake/photo.jpg")
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([path])
        assert results[path].date_taken == datetime.datetime(2023, 6, 1, 12, 0, 0)

    def test_no_metadata_returns_defaults(self):
        raw = [_make_exiftool_result()]
        path = pathlib.Path("/fake/photo.jpg")
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([path])
        assert results[path].date_taken is None

    def test_invalid_date_returns_none(self):
        raw = [
            _make_exiftool_result(**{"EXIF:DateTimeOriginal": "0000:00:00 00:00:00"})
        ]
        path = pathlib.Path("/fake/photo.jpg")
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([path])
        assert results[path].date_taken is None


class TestMtimeFallback:
    """Test filesystem mtime as date fallback when no EXIF date is found."""

    def test_mtime_fallback_when_no_exif_date(self, tmp_path: pathlib.Path):
        """No EXIF date → mtime is used, date_from_mtime=True."""
        photo = tmp_path / "photo.jpg"
        photo.write_bytes(b"fake image")
        import os

        mtime = 1710500000.0  # 2024-03-15 ~13:33 UTC
        os.utime(photo, (mtime, mtime))

        raw = [_make_exiftool_result(SourceFile=str(photo))]
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([photo])
        m = results[photo]
        assert m.date_taken is not None
        assert m.date_taken.year == 2024
        assert m.date_from_mtime is True

    def test_exif_date_takes_precedence_over_mtime(self, tmp_path: pathlib.Path):
        """EXIF date present → mtime ignored, date_from_mtime=False."""
        photo = tmp_path / "photo.jpg"
        photo.write_bytes(b"fake image")
        import os

        mtime = 1710500000.0
        os.utime(photo, (mtime, mtime))

        raw = [
            _make_exiftool_result(
                SourceFile=str(photo),
                **{"EXIF:DateTimeOriginal": "2023:06:01 12:00:00"},
            )
        ]
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([photo])
        m = results[photo]
        assert m.date_taken == datetime.datetime(2023, 6, 1, 12, 0, 0)
        assert m.date_from_mtime is False

    def test_mtime_fallback_in_extract_batch(self, tmp_path: pathlib.Path):
        """Batch extraction with files lacking EXIF date uses mtime."""
        photo = tmp_path / "photo.jpg"
        photo.write_bytes(b"fake image")
        import os

        mtime = 1710500000.0
        os.utime(photo, (mtime, mtime))

        raw = [_make_exiftool_result(SourceFile=str(photo))]
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch([photo])
        m = results[photo]
        assert m.date_taken is not None
        assert m.date_from_mtime is True


class TestExtractBatch:
    """Test batch metadata extraction."""

    def test_extracts_multiple_files(self):
        raw = [
            _make_exiftool_result(
                SourceFile="/fake/a.jpg",
                **{"EXIF:DateTimeOriginal": "2024:01:01 12:00:00"},
            ),
            _make_exiftool_result(
                SourceFile="/fake/b.jpg",
                **{"EXIF:DateTimeOriginal": "2024:06:15 08:00:00"},
            ),
        ]
        paths = [pathlib.Path("/fake/a.jpg"), pathlib.Path("/fake/b.jpg")]
        with patch("undisorder.metadata._run_exiftool", return_value=raw):
            results = extract_batch(paths)
        assert len(results) == 2
        assert results[pathlib.Path("/fake/a.jpg")].date_taken == datetime.datetime(
            2024, 1, 1, 12, 0, 0
        )
        assert results[pathlib.Path("/fake/b.jpg")].date_taken == datetime.datetime(
            2024, 6, 15, 8, 0, 0
        )

    def test_empty_list(self):
        results = extract_batch([])
        assert results == {}
