"""EXIF/IPTC/XMP metadata extraction via exiftool."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

import datetime
import json
import pathlib
import subprocess


@dataclass
class Metadata:
    """Extracted metadata for a single file."""

    source_path: pathlib.Path
    date_taken: datetime.datetime | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None
    keywords: list[str] = field(default_factory=list)
    description: str | None = None
    user_comment: str | None = None
    subject: list[str] = field(default_factory=list)

    @property
    def has_gps(self) -> bool:
        return self.gps_lat is not None and self.gps_lon is not None


# Date tag lookup order (first match wins)
_DATE_TAGS = [
    "EXIF:DateTimeOriginal",
    "EXIF:CreateDate",
    "QuickTime:CreateDate",
    "QuickTime:MediaCreateDate",
    "XMP:DateTimeOriginal",
    "XMP:CreateDate",
]

_DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


def _run_exiftool(paths: list[pathlib.Path]) -> list[dict[str, object]]:
    """Run exiftool and return parsed JSON output."""
    cmd = [
        "exiftool",
        "-json",
        "-n",  # numeric output (no conversion for GPS etc.)
        "-G",  # group names in tags
        *[str(p) for p in paths],
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _parse_date(raw: dict[str, object]) -> datetime.datetime | None:
    """Extract date from the first available date tag."""
    for tag in _DATE_TAGS:
        value = raw.get(tag)
        if not value or not isinstance(value, str):
            continue
        try:
            dt = datetime.datetime.strptime(value, _DATE_FORMAT)
            # Reject placeholder dates like 0000:00:00
            if dt.year < 1900:
                continue
            return dt
        except ValueError:
            continue
    return None


def _parse_gps(raw: dict[str, object]) -> tuple[float | None, float | None]:
    """Extract GPS coordinates, handling ref tags and composite tags."""
    # Try Composite tags first (pre-computed, already signed)
    comp_lat = raw.get("Composite:GPSLatitude")
    comp_lon = raw.get("Composite:GPSLongitude")
    if isinstance(comp_lat, (int, float)) and isinstance(comp_lon, (int, float)):
        return float(comp_lat), float(comp_lon)

    # Try EXIF tags with ref
    lat = raw.get("EXIF:GPSLatitude")
    lon = raw.get("EXIF:GPSLongitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None, None

    lat_ref = raw.get("EXIF:GPSLatitudeRef", "N")
    lon_ref = raw.get("EXIF:GPSLongitudeRef", "E")

    lat_val = float(lat)
    lon_val = float(lon)

    if lat_ref == "S":
        lat_val = -lat_val
    if lon_ref == "W":
        lon_val = -lon_val

    return lat_val, lon_val


def _parse_keywords(raw: dict[str, object]) -> list[str]:
    """Extract keywords from IPTC or XMP tags."""
    for tag in ("IPTC:Keywords", "XMP:Subject"):
        value = raw.get(tag)
        if value is None:
            continue
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]
    return []


def _parse_description(raw: dict[str, object]) -> str | None:
    """Extract description from available tags."""
    for tag in ("EXIF:ImageDescription", "XMP:Description", "IPTC:Caption-Abstract"):
        value = raw.get(tag)
        if value and isinstance(value, str):
            return value
    return None


def _parse_subject(raw: dict[str, object]) -> list[str]:
    """Extract XMP subject tags."""
    value = raw.get("XMP:Subject")
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _parse_one(raw: dict[str, object], path: pathlib.Path) -> Metadata:
    """Parse a single exiftool JSON result into a Metadata object."""
    gps_lat, gps_lon = _parse_gps(raw)
    return Metadata(
        source_path=path,
        date_taken=_parse_date(raw),
        gps_lat=gps_lat,
        gps_lon=gps_lon,
        keywords=_parse_keywords(raw),
        description=_parse_description(raw),
        user_comment=comment if isinstance(comment := raw.get("EXIF:UserComment"), str) else None,
        subject=_parse_subject(raw),
    )


def extract(path: pathlib.Path) -> Metadata:
    """Extract metadata from a single file."""
    results = _run_exiftool([path])
    if not results:
        return Metadata(source_path=path)
    return _parse_one(results[0], path)


def extract_batch(paths: list[pathlib.Path]) -> dict[pathlib.Path, Metadata]:
    """Extract metadata from multiple files in one exiftool call."""
    if not paths:
        return {}
    results = _run_exiftool(paths)
    out: dict[pathlib.Path, Metadata] = {}
    for raw in results:
        source = pathlib.Path(str(raw.get("SourceFile", "")))
        out[source] = _parse_one(raw, source)
    return out
