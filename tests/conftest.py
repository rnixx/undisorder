"""Shared fixtures for undisorder tests."""

import os
import pathlib

import pytest


@pytest.fixture
def tmp_source(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary source directory with sample files."""
    source = tmp_path / "source"
    source.mkdir()
    return source


@pytest.fixture
def tmp_target(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary target directory."""
    target = tmp_path / "target"
    target.mkdir()
    return target


@pytest.fixture
def sample_jpg(tmp_source: pathlib.Path) -> pathlib.Path:
    """Create a minimal JPEG file (valid JFIF header)."""
    p = tmp_source / "photo.jpg"
    # Minimal valid JPEG: SOI + APP0 (JFIF) + EOI
    p.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
    )
    return p


@pytest.fixture
def sample_mp4(tmp_source: pathlib.Path) -> pathlib.Path:
    """Create a minimal MP4 file (ftyp box)."""
    p = tmp_source / "video.mp4"
    # Minimal ftyp box
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom")
    return p


@pytest.fixture
def sample_txt(tmp_source: pathlib.Path) -> pathlib.Path:
    """Create a plain text file (not a media file)."""
    p = tmp_source / "notes.txt"
    p.write_text("not a photo")
    return p
