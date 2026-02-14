"""Tests for undisorder.hasher — 2-phase duplicate detection."""

import pathlib

import pytest

from undisorder.hasher import DuplicateGroup, find_duplicates, hash_file


class TestHashFile:
    """Test SHA256 hashing of individual files."""

    def test_hash_deterministic(self, tmp_path: pathlib.Path):
        f = tmp_path / "a.bin"
        f.write_bytes(b"hello world")
        assert hash_file(f) == hash_file(f)

    def test_identical_content_same_hash(self, tmp_path: pathlib.Path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"same content")
        f2.write_bytes(b"same content")
        assert hash_file(f1) == hash_file(f2)

    def test_different_content_different_hash(self, tmp_path: pathlib.Path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert hash_file(f1) != hash_file(f2)

    def test_hash_is_hex_sha256(self, tmp_path: pathlib.Path):
        f = tmp_path / "a.bin"
        f.write_bytes(b"test")
        h = hash_file(f)
        assert len(h) == 64  # SHA256 hex digest is 64 chars
        assert all(c in "0123456789abcdef" for c in h)

    def test_nonexistent_file_raises(self, tmp_path: pathlib.Path):
        with pytest.raises(FileNotFoundError):
            hash_file(tmp_path / "nope.bin")


class TestFindDuplicates:
    """Test 2-phase duplicate detection."""

    def test_no_files_returns_empty(self):
        assert find_duplicates([]) == []

    def test_unique_files_returns_empty(self, tmp_path: pathlib.Path):
        f1 = tmp_path / "a.jpg"
        f2 = tmp_path / "b.jpg"
        f1.write_bytes(b"unique content 1")
        f2.write_bytes(b"different unique content 2")
        assert find_duplicates([f1, f2]) == []

    def test_finds_exact_duplicates(self, tmp_path: pathlib.Path):
        content = b"duplicate content here"
        f1 = tmp_path / "a.jpg"
        f2 = tmp_path / "b.jpg"
        f1.write_bytes(content)
        f2.write_bytes(content)
        groups = find_duplicates([f1, f2])
        assert len(groups) == 1
        assert set(groups[0].paths) == {f1, f2}

    def test_same_size_different_content_not_duplicate(self, tmp_path: pathlib.Path):
        """Files with same size but different content should not be grouped."""
        f1 = tmp_path / "a.jpg"
        f2 = tmp_path / "b.jpg"
        f1.write_bytes(b"AAAA")  # 4 bytes
        f2.write_bytes(b"BBBB")  # 4 bytes
        assert find_duplicates([f1, f2]) == []

    def test_different_sizes_not_hashed(self, tmp_path: pathlib.Path):
        """Files with different sizes should not be compared by hash at all."""
        f1 = tmp_path / "small.jpg"
        f2 = tmp_path / "big.jpg"
        f1.write_bytes(b"short")
        f2.write_bytes(b"this is much longer content")
        assert find_duplicates([f1, f2]) == []

    def test_multiple_duplicate_groups(self, tmp_path: pathlib.Path):
        a1 = tmp_path / "a1.jpg"
        a2 = tmp_path / "a2.jpg"
        b1 = tmp_path / "b1.jpg"
        b2 = tmp_path / "b2.jpg"
        a1.write_bytes(b"group A content")
        a2.write_bytes(b"group A content")
        b1.write_bytes(b"group B content")
        b2.write_bytes(b"group B content")
        groups = find_duplicates([a1, a2, b1, b2])
        assert len(groups) == 2
        path_sets = [set(g.paths) for g in groups]
        assert {a1, a2} in path_sets
        assert {b1, b2} in path_sets

    def test_three_way_duplicate(self, tmp_path: pathlib.Path):
        content = b"triple"
        files = []
        for name in ("x.jpg", "y.jpg", "z.jpg"):
            f = tmp_path / name
            f.write_bytes(content)
            files.append(f)
        groups = find_duplicates(files)
        assert len(groups) == 1
        assert len(groups[0].paths) == 3

    def test_duplicate_group_has_hash_and_size(self, tmp_path: pathlib.Path):
        content = b"some bytes"
        f1 = tmp_path / "a.jpg"
        f2 = tmp_path / "b.jpg"
        f1.write_bytes(content)
        f2.write_bytes(content)
        groups = find_duplicates([f1, f2])
        assert groups[0].hash is not None
        assert groups[0].file_size == len(content)

    def test_single_file_not_duplicate(self, tmp_path: pathlib.Path):
        f = tmp_path / "only.jpg"
        f.write_bytes(b"alone")
        assert find_duplicates([f]) == []
