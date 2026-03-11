"""Tests for undisorder.hashdb — SQLite hash index CRUD."""

from undisorder.hashdb import _SCHEMA_VERSION
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

    def test_context_manager_closes_connection(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """Using HashDB as context manager should close the connection on exit."""
        db_path = tmp_path / "test.db"
        with HashDB(tmp_target, db_path=db_path) as db:
            db.insert(original_hash="h1", file_path="a.jpg")
        # Connection is closed — operations should fail
        with pytest.raises(Exception):
            db.hash_exists("h1")

    def test_context_manager_preserves_data(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """Data inserted before context exit should be readable in a new connection."""
        db_path = tmp_path / "test.db"
        with HashDB(tmp_target, db_path=db_path) as db:
            db.insert(original_hash="h1", file_path="a.jpg")
        # Reopen and verify
        db2 = HashDB(tmp_target, db_path=db_path)
        assert db2.hash_exists("h1")

    def test_fresh_db_gets_schema_version(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """A new database should be stamped with the current schema version."""
        db_path = tmp_path / "test.db"
        HashDB(tmp_target, db_path=db_path)
        conn = sqlite3.connect(db_path)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        assert version == _SCHEMA_VERSION

    def test_incompatible_schema_version_exits(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """Opening a DB with a different schema version should exit."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION + 1}")
        conn.commit()
        conn.close()
        with pytest.raises(SystemExit):
            HashDB(tmp_target, db_path=db_path)


class TestHashDBInsert:
    """Test inserting records."""

    def test_insert_and_lookup(self, db: HashDB):
        db.insert(
            original_hash="abc123",
            file_path="2024/2024-03/photo.jpg",
        )
        assert db.hash_exists("abc123")

    def test_insert_with_current_hash(self, db: HashDB):
        db.insert(
            original_hash="abc123",
            file_path="2024/photo.jpg",
            current_hash="def456",
        )
        row = db.get_by_hash("abc123")
        assert row is not None
        assert row["current_hash"] == "def456"

    def test_insert_defaults_current_hash_to_original(self, db: HashDB):
        db.insert(
            original_hash="abc123",
            file_path="2024/photo.jpg",
        )
        row = db.get_by_hash("abc123")
        assert row is not None
        assert row["current_hash"] == "abc123"

    def test_lookup_missing_hash(self, db: HashDB):
        assert db.hash_exists("nonexistent") is False

    def test_insert_duplicate_hash_raises(self, db: HashDB):
        """Inserting the same original_hash twice should raise (PRIMARY KEY violation)."""
        db.insert(original_hash="abc", file_path="a/photo.jpg")
        with pytest.raises(sqlite3.IntegrityError):
            db.insert(original_hash="abc", file_path="b/photo.jpg")


class TestHashDBQuery:
    """Test querying records."""

    def test_get_by_hash(self, db: HashDB):
        db.insert(original_hash="h1", file_path="a.jpg")
        row = db.get_by_hash("h1")
        assert row is not None
        assert row["file_path"] == "a.jpg"

    def test_get_by_hash_empty(self, db: HashDB):
        assert db.get_by_hash("missing") is None

    def test_count(self, db: HashDB):
        assert db.count() == 0
        db.insert(original_hash="h1", file_path="a.jpg")
        db.insert(original_hash="h2", file_path="b.jpg")
        assert db.count() == 2


class TestHashDBDelete:
    """Test deleting records."""

    def test_delete_by_path(self, db: HashDB):
        db.insert(original_hash="h1", file_path="a.jpg")
        db.delete_by_path("a.jpg")
        assert db.count() == 0

    def test_delete_by_path_scoped_to_target_dir(self, tmp_path: pathlib.Path):
        """delete_by_path should only delete records for this target_dir."""
        db_path = tmp_path / "test.db"
        target_a = tmp_path / "a"
        target_a.mkdir()
        target_b = tmp_path / "b"
        target_b.mkdir()

        db_a = HashDB(target_a, db_path=db_path)
        db_b = HashDB(target_b, db_path=db_path)

        db_a.insert(original_hash="h1", file_path="photo.jpg")
        db_b.insert(original_hash="h2", file_path="photo.jpg")

        db_a.delete_by_path("photo.jpg")
        assert db_a.count() == 0
        assert db_b.count() == 1

    def test_delete_nonexistent_is_noop(self, db: HashDB):
        db.delete_by_path("nope.jpg")  # should not raise


class TestHashDBRebuild:
    """Test rebuilding the hash DB from the filesystem."""

    def test_rebuild_adds_new_files(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """New files on disk get inserted with original_hash = current_hash."""
        sub = tmp_target / "2024" / "2024-03"
        sub.mkdir(parents=True)
        (sub / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        count = db.rebuild(tmp_target)
        assert count == 1
        assert db.count() == 1

    def test_rebuild_updates_current_hash_for_known_files(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """Known file_path gets current_hash updated."""
        from undisorder.hasher import hash_file

        photo = tmp_target / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original")

        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        original_h = hash_file(photo)
        db.insert(original_hash=original_h, file_path="photo.jpg")

        # Modify the file (simulates external edit)
        photo.write_bytes(b"\xff\xd8\xff\xd9modified content")
        new_h = hash_file(photo)

        count = db.rebuild(tmp_target)
        assert count == 1

        row = db.get_by_hash(original_h)
        assert row is not None
        assert row["current_hash"] == new_h

    def test_rebuild_deletes_missing_files(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """DB records with no corresponding file on disk get deleted."""
        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        db.insert(original_hash="old", file_path="gone.jpg")
        db.rebuild(tmp_target)
        assert db.hash_exists("old") is False

    def test_rebuild_inserts_unknown_files(
        self, tmp_path: pathlib.Path, tmp_target: pathlib.Path
    ):
        """Files on disk not in DB get inserted with original_hash = current_hash."""
        from undisorder.hasher import hash_file

        photo = tmp_target / "new_photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9brand new")

        db = HashDB(tmp_target, db_path=tmp_path / "test.db")
        count = db.rebuild(tmp_target)
        assert count == 1

        h = hash_file(photo)
        row = db.get_by_hash(h)
        assert row is not None
        assert row["original_hash"] == h
        assert row["current_hash"] == h


class TestAcoustidCache:
    """Test the acoustid_cache table for caching AcoustID lookups."""

    def test_store_and_get(self, db: HashDB):
        """Store a cache entry and retrieve it."""
        db.store_acoustid_cache(
            file_hash="abc123",
            fingerprint="AQAA...",
            duration=240.5,
            recording_id="rec-001",
            metadata={
                "artist": "The Beatles",
                "album": "Abbey Road",
                "title": "Come Together",
                "track_number": 1,
                "disc_number": 1,
                "year": 1969,
            },
        )
        cached = db.get_acoustid_cache("abc123")
        assert cached is not None
        assert cached["fingerprint"] == "AQAA..."
        assert cached["duration"] == 240.5
        assert cached["recording_id"] == "rec-001"
        assert cached["artist"] == "The Beatles"
        assert cached["album"] == "Abbey Road"
        assert cached["title"] == "Come Together"
        assert cached["track_number"] == 1
        assert cached["disc_number"] == 1
        assert cached["year"] == 1969
        assert cached["lookup_date"] is not None

    def test_get_missing_returns_none(self, db: HashDB):
        """Getting a non-existent cache entry returns None."""
        assert db.get_acoustid_cache("nonexistent") is None

    def test_store_minimal_metadata(self, db: HashDB):
        """Store with only some metadata fields set."""
        db.store_acoustid_cache(
            file_hash="minimal",
            fingerprint="FP...",
            duration=180.0,
            recording_id=None,
            metadata={},
        )
        cached = db.get_acoustid_cache("minimal")
        assert cached is not None
        assert cached["recording_id"] is None
        assert cached["artist"] is None
        assert cached["album"] is None

    def test_cache_overwrites_on_duplicate(self, db: HashDB):
        """Storing the same file_hash again overwrites the old entry."""
        db.store_acoustid_cache(
            file_hash="dup",
            fingerprint="FP1",
            duration=100.0,
            recording_id="rec-old",
            metadata={"artist": "Old"},
        )
        db.store_acoustid_cache(
            file_hash="dup",
            fingerprint="FP2",
            duration=200.0,
            recording_id="rec-new",
            metadata={"artist": "New"},
        )
        cached = db.get_acoustid_cache("dup")
        assert cached is not None
        assert cached["fingerprint"] == "FP2"
        assert cached["artist"] == "New"

    def test_cache_not_scoped_to_target_dir(self, tmp_path: pathlib.Path):
        """acoustid_cache is global — same hash visible from any target_dir."""
        db_path = tmp_path / "test.db"
        target_a = tmp_path / "a"
        target_a.mkdir()
        target_b = tmp_path / "b"
        target_b.mkdir()

        db_a = HashDB(target_a, db_path=db_path)
        db_b = HashDB(target_b, db_path=db_path)

        db_a.store_acoustid_cache(
            file_hash="shared",
            fingerprint="FP",
            duration=120.0,
            recording_id="rec-shared",
            metadata={"artist": "Shared Artist"},
        )
        cached = db_b.get_acoustid_cache("shared")
        assert cached is not None
        assert cached["artist"] == "Shared Artist"

    def test_acoustid_cache_table_exists(self, db: HashDB):
        """The acoustid_cache table should exist after init."""
        conn = sqlite3.connect(db.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='acoustid_cache'"
        )
        assert cursor.fetchone() is not None
        conn.close()
