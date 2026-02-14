"""Tests for undisorder.metadata — EXIF/metadata extraction via exiftool."""

from undisorder.metadata import extract
from undisorder.metadata import extract_batch
from undisorder.metadata import Metadata
from unittest.mock import patch

import datetime
import pathlib
import pytest


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
        assert m.gps_lat is None
        assert m.gps_lon is None
        assert m.keywords == []
        assert m.description is None

    def test_has_gps(self):
        m = Metadata(source_path=pathlib.Path("x.jpg"), gps_lat=48.2, gps_lon=16.3)
        assert m.has_gps is True

    def test_has_no_gps(self):
        m = Metadata(source_path=pathlib.Path("x.jpg"))
        assert m.has_gps is False

    def test_has_gps_partial(self):
        m = Metadata(source_path=pathlib.Path("x.jpg"), gps_lat=48.2)
        assert m.has_gps is False


class TestExtract:
    """Test single-file metadata extraction."""

    def test_extracts_date_taken(self):
        raw = _make_exiftool_result(
            **{"EXIF:DateTimeOriginal": "2024:03:15 14:30:00"}
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.date_taken == datetime.datetime(2024, 3, 15, 14, 30, 0)

    def test_falls_back_to_createdate(self):
        raw = _make_exiftool_result(**{"EXIF:CreateDate": "2023:12:25 10:00:00"})
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/video.mp4"))
        assert m.date_taken == datetime.datetime(2023, 12, 25, 10, 0, 0)

    def test_falls_back_to_quicktime_createdate(self):
        raw = _make_exiftool_result(
            **{"QuickTime:CreateDate": "2023:06:01 12:00:00"}
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/video.mov"))
        assert m.date_taken == datetime.datetime(2023, 6, 1, 12, 0, 0)

    def test_extracts_gps(self):
        raw = _make_exiftool_result(
            **{
                "EXIF:GPSLatitude": 48.2082,
                "EXIF:GPSLongitude": 16.3738,
                "EXIF:GPSLatitudeRef": "N",
                "EXIF:GPSLongitudeRef": "E",
            }
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.gps_lat == pytest.approx(48.2082)
        assert m.gps_lon == pytest.approx(16.3738)

    def test_gps_south_west_negative(self):
        raw = _make_exiftool_result(
            **{
                "EXIF:GPSLatitude": 33.8688,
                "EXIF:GPSLongitude": 151.2093,
                "EXIF:GPSLatitudeRef": "S",
                "EXIF:GPSLongitudeRef": "W",
            }
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.gps_lat == pytest.approx(-33.8688)
        assert m.gps_lon == pytest.approx(-151.2093)

    def test_extracts_keywords_list(self):
        raw = _make_exiftool_result(**{"IPTC:Keywords": ["vacation", "beach"]})
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.keywords == ["vacation", "beach"]

    def test_extracts_keywords_single_string(self):
        raw = _make_exiftool_result(**{"IPTC:Keywords": "portrait"})
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.keywords == ["portrait"]

    def test_extracts_description(self):
        raw = _make_exiftool_result(
            **{"EXIF:ImageDescription": "A beautiful sunset"}
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.description == "A beautiful sunset"

    def test_falls_back_to_xmp_description(self):
        raw = _make_exiftool_result(
            **{"XMP:Description": "Mountain view"}
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.description == "Mountain view"

    def test_no_metadata_returns_defaults(self):
        raw = _make_exiftool_result()
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.date_taken is None
        assert m.gps_lat is None
        assert m.gps_lon is None
        assert m.keywords == []
        assert m.description is None

    def test_invalid_date_returns_none(self):
        raw = _make_exiftool_result(
            **{"EXIF:DateTimeOriginal": "0000:00:00 00:00:00"}
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.date_taken is None

    def test_extracts_user_comment(self):
        raw = _make_exiftool_result(**{"EXIF:UserComment": "Family gathering"})
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.user_comment == "Family gathering"

    def test_extracts_subject(self):
        raw = _make_exiftool_result(**{"XMP:Subject": ["birthday", "party"]})
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.subject == ["birthday", "party"]

    def test_composite_gps_coordinates(self):
        """Test extraction from Composite GPS tags (pre-computed by exiftool)."""
        raw = _make_exiftool_result(
            **{
                "Composite:GPSLatitude": 52.5200,
                "Composite:GPSLongitude": 13.4050,
            }
        )
        with patch("undisorder.metadata._run_exiftool", return_value=[raw]):
            m = extract(pathlib.Path("/fake/photo.jpg"))
        assert m.gps_lat == pytest.approx(52.5200)
        assert m.gps_lon == pytest.approx(13.4050)


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
