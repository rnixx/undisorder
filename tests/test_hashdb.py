"""Tests for undisorder.hashdb — SQLite hash index CRUD."""

from undisorder.hashdb import HashDB

import pathlib
import pytest
import sqlite3


@pytest.fixture
def db(tmp_path: pathlib.Path, tmp_target: pathlib.Path) -> HashDB:
    """Create a HashDB instance with a temp DB file."""
    return HashDB(tmp_target, db_path=tmp_path / "test.db")


class TestHashDBInit:
    """Test database initialization."""

    def test_creates_db_file(self, tmp_path: pathlib.Path, tmp_target: pathlib.Path):
        db_path = tmp_path / "test.db"
        HashDB(tmp_target, db_path=db_path)
        assert db_path.exists()

    def test_creates_tables(self, db: HashDB):
        """The files table should exist after init."""
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_idempotent_init(self, tmp_path: pathlib.Path, tmp_target: pathlib.Path):
        """Creating HashDB twice on the same dir should not fail."""
        db_path = tmp_path / "test.db"
        HashDB(tmp_target, db_path=db_path)
        HashDB(tmp_target, db_path=db_path)

    def test_target_dir_isolation(self, tmp_path: pathlib.Path):
        """Two HashDB instances with different target_dirs share the DB but see different data."""
        db_path = tmp_path / "test.db"
        target_a = tmp_path / "a"
        target_a.mkdir()
        target_b = tmp_path / "b"
        target_b.mkdir()

        db_a = HashDB(target_a, db_path=db_path)
        db_b = HashDB(target_b, db_path=db_path)

        db_a.insert(hash="h1", file_size=100, file_path="photo.jpg")
        assert db_a.hash_exists("h1")
        assert db_b.hash_exists("h1") is False
        assert db_a.count() == 1
        assert db_b.count() == 0


class TestHashDBInsert:
    """Test inserting records."""

    def test_insert_and_lookup(self, db: HashDB):
        db.insert(
            hash="abc123",
            file_size=1024,
            file_path="2024/2024-03/photo.jpg",
            date_taken="2024:03:15 14:30:00",
            source_path="/media/sd/DCIM/photo.jpg",
        )
        assert db.hash_exists("abc123")

    def test_lookup_missing_hash(self, db: HashDB):
        assert db.hash_exists("nonexistent") is False

    def test_insert_multiple_same_hash(self, db: HashDB):
        """Same hash but different file_path is allowed (same content, different locations)."""
        db.insert(hash="abc", file_size=100, file_path="a/photo.jpg")
        db.insert(hash="abc", file_size=100, file_path="b/photo.jpg")
        assert db.hash_exists("abc")

    def test_duplicate_hash_and_path_raises(self, db: HashDB):
        """Same hash + same file_path should raise (PRIMARY KEY violation)."""
        db.insert(hash="abc", file_size=100, file_path="a/photo.jpg")
        with pytest.raises(sqlite3.IntegrityError):
            db.insert(hash="abc", file_size=100, file_path="a/photo.jpg")


class TestHashDBQuery:
    """Test querying records."""

    def test_get_by_hash(self, db: HashDB):
        db.insert(hash="h1", file_size=100, file_path="a.jpg")
        db.insert(hash="h1", file_size=100, file_path="b.jpg")
        rows = db.get_by_hash("h1")
        assert len(rows) == 2
        paths = {r["file_path"] for r in rows}
        assert paths == {"a.jpg", "b.jpg"}

    def test_get_by_hash_empty(self, db: HashDB):
        assert db.get_by_hash("missing") == []

    def test_count(self, db: HashDB):
        assert db.count() == 0
        db.insert(hash="h1", file_size=100, file_path="a.jpg")
        db.insert(hash="h2", file_size=200, file_path="b.jpg")
        assert db.count() == 2

    def test_find_internal_duplicates(self, db: HashDB):
        """Find hashes that appear at more than one path in the DB."""
        db.insert(hash="h1", file_size=100, file_path="a.jpg")
        db.insert(hash="h1", file_size=100, file_path="b.jpg")
        db.insert(hash="h2", file_size=200, file_path="c.jpg")
        dupes = db.find_duplicates()
        assert len(dupes) == 1
        assert dupes[0]["hash"] == "h1"
        assert dupes[0]["count"] == 2

    def test_no_internal_duplicates(self, db: HashDB):
        db.insert(hash="h1", file_size=100, file_path="a.jpg")
        db.insert(hash="h2", file_size=200, file_path="b.jpg")
        assert db.find_duplicates() == []


class TestHashDBDelete:
    """Test deleting records."""

    def test_delete_by_path(self, db: HashDB):
        db.insert(hash="h1", file_size=100, file_path="a.jpg")
        db.delete_by_path("a.jpg")
        assert db.count() == 0

    def test_delete_nonexistent_is_noop(self, db: HashDB):
        db.delete_by_path("nope.jpg")  # should not raise


class TestHashDBRebuild:
    """Test rebuilding the hash DB from the filesystem."""

    def test_rebuild_adds_files(self, tmp_path: pathlib.Path, tmp_target: pathlib.Path):
        # Create some files in the target
        sub = tmp_target / "2024" / "2024-03"
        sub.mkdir(parents=True)
        (sub / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        count = db.rebuild(tmp_target)
        assert count == 1
        assert db.count() == 1

    def test_rebuild_clears_old_entries(self, tmp_path: pathlib.Path, tmp_target: pathlib.Path):
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        db.insert(hash="old", file_size=1, file_path="gone.jpg")
        db.rebuild(tmp_target)
        # gone.jpg doesn't exist, so it should be cleared
        assert db.hash_exists("old") is False


class TestHashDBImports:
    """Test the imports table for source-path-based re-import protection."""

    def test_record_and_check_import(self, db: HashDB):
        db.record_import("/media/sd/DCIM/photo.jpg", "abc123", "2024/photo.jpg")
        assert db.source_path_imported("/media/sd/DCIM/photo.jpg") is True

    def test_source_path_not_imported(self, db: HashDB):
        assert db.source_path_imported("/unknown/path.jpg") is False

    def test_record_import_idempotent(self, db: HashDB):
        db.record_import("/media/sd/photo.jpg", "hash1", "2024/photo.jpg")
        # Second insert with same source_path should be ignored (INSERT OR IGNORE)
        db.record_import("/media/sd/photo.jpg", "hash2", "2025/photo.jpg")
        imp = db.get_import("/media/sd/photo.jpg")
        assert imp is not None
        # Original values should be preserved
        assert imp["hash"] == "hash1"
        assert imp["file_path"] == "2024/photo.jpg"

    def test_get_import(self, db: HashDB):
        db.record_import("/media/sd/photo.jpg", "abc123", "2024/photo.jpg")
        imp = db.get_import("/media/sd/photo.jpg")
        assert imp is not None
        assert imp["source_path"] == "/media/sd/photo.jpg"
        assert imp["hash"] == "abc123"
        assert imp["file_path"] == "2024/photo.jpg"

    def test_get_import_missing(self, db: HashDB):
        assert db.get_import("/unknown/path.jpg") is None

    def test_update_import(self, db: HashDB):
        db.record_import("/media/sd/photo.jpg", "hash1", "2024/photo.jpg")
        db.update_import("/media/sd/photo.jpg", "hash2", "2025/photo.jpg")
        imp = db.get_import("/media/sd/photo.jpg")
        assert imp is not None
        assert imp["hash"] == "hash2"
        assert imp["file_path"] == "2025/photo.jpg"

    def test_delete_by_hash_and_path(self, db: HashDB):
        db.insert(hash="h1", file_size=100, file_path="a.jpg")
        db.insert(hash="h1", file_size=100, file_path="b.jpg")
        db.delete_by_hash_and_path("h1", "a.jpg")
        rows = db.get_by_hash("h1")
        assert len(rows) == 1
        assert rows[0]["file_path"] == "b.jpg"

    def test_rebuild_preserves_imports(self, tmp_path: pathlib.Path, tmp_target: pathlib.Path):
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        db.record_import("/media/sd/photo.jpg", "abc123", "2024/photo.jpg")
        db.insert(hash="old", file_size=1, file_path="gone.jpg")
        db.rebuild(tmp_target)
        # files table should be cleared
        assert db.hash_exists("old") is False
        # imports table should be preserved
        assert db.source_path_imported("/media/sd/photo.jpg") is True

    def test_imports_isolated_by_target_dir(self, tmp_path: pathlib.Path):
        """Import records are scoped to target_dir."""
        db_path = tmp_path / "test.db"
        target_a = tmp_path / "a"
        target_a.mkdir()
        target_b = tmp_path / "b"
        target_b.mkdir()

        db_a = HashDB(target_a, db_path=db_path)
        db_b = HashDB(target_b, db_path=db_path)

        db_a.record_import("/media/sd/photo.jpg", "h1", "2024/photo.jpg")
        assert db_a.source_path_imported("/media/sd/photo.jpg") is True
        assert db_b.source_path_imported("/media/sd/photo.jpg") is False
