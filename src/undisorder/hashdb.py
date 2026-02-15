"""SQLite hash index for target directories."""

from __future__ import annotations

from undisorder.hasher import hash_file

import datetime
import os
import pathlib
import sqlite3


_SCHEMA = """\
CREATE TABLE IF NOT EXISTS files (
    target_dir TEXT NOT NULL,
    hash TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    date_taken TEXT,
    import_date TEXT NOT NULL,
    source_path TEXT,
    PRIMARY KEY (target_dir, hash, file_path)
);
CREATE INDEX IF NOT EXISTS idx_hash ON files(target_dir, hash);
CREATE INDEX IF NOT EXISTS idx_size ON files(target_dir, file_size);
CREATE TABLE IF NOT EXISTS imports (
    target_dir TEXT NOT NULL,
    source_path TEXT NOT NULL,
    hash TEXT NOT NULL,
    file_path TEXT,
    PRIMARY KEY (target_dir, source_path)
);
CREATE TABLE IF NOT EXISTS acoustid_cache (
    file_hash TEXT PRIMARY KEY,
    fingerprint TEXT,
    duration REAL,
    recording_id TEXT,
    artist TEXT,
    album TEXT,
    title TEXT,
    track_number INTEGER,
    disc_number INTEGER,
    year INTEGER,
    lookup_date TEXT NOT NULL
);
"""


def _config_dir() -> pathlib.Path:
    """Return the undisorder config directory, creating it if needed."""
    base = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    d = base / "undisorder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_db_path() -> pathlib.Path:
    """Return the default central database path."""
    return _config_dir() / "undisorder.db"


class HashDB:
    """SQLite-backed hash index for a target directory."""

    def __init__(
        self,
        target_dir: pathlib.Path,
        *,
        db_path: pathlib.Path | None = None,
    ) -> None:
        self.target_dir = str(target_dir.resolve())
        self.db_path = db_path if db_path is not None else _default_db_path()
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def insert(
        self,
        *,
        hash: str,
        file_size: int,
        file_path: str,
        date_taken: str | None = None,
        source_path: str | None = None,
        import_date: str | None = None,
    ) -> None:
        """Insert a file record into the hash DB."""
        if import_date is None:
            import_date = datetime.datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO files (target_dir, hash, file_size, file_path, date_taken, import_date, source_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.target_dir, hash, file_size, file_path, date_taken, import_date, source_path),
        )
        self._conn.commit()

    def hash_exists(self, hash: str) -> bool:
        """Check if a hash exists in the DB."""
        cursor = self._conn.execute(
            "SELECT 1 FROM files WHERE target_dir = ? AND hash = ?",
            (self.target_dir, hash),
        )
        return cursor.fetchone() is not None

    def get_by_hash(self, hash: str) -> list[dict[str, object]]:
        """Get all records for a given hash."""
        cursor = self._conn.execute(
            "SELECT * FROM files WHERE target_dir = ? AND hash = ?",
            (self.target_dir, hash),
        )
        return [dict(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Return the total number of records."""
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM files WHERE target_dir = ?",
            (self.target_dir,),
        )
        return cursor.fetchone()[0]

    def find_duplicates(self) -> list[dict[str, object]]:
        """Find hashes that appear at more than one path."""
        cursor = self._conn.execute(
            "SELECT hash, COUNT(*) as count FROM files "
            "WHERE target_dir = ? GROUP BY hash HAVING count > 1",
            (self.target_dir,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def delete_by_path(self, file_path: str) -> None:
        """Delete a record by file path."""
        self._conn.execute(
            "DELETE FROM files WHERE target_dir = ? AND file_path = ?",
            (self.target_dir, file_path),
        )
        self._conn.commit()

    def delete_by_hash_and_path(self, hash: str, file_path: str) -> None:
        """Delete a specific files entry by hash and file_path."""
        self._conn.execute(
            "DELETE FROM files WHERE target_dir = ? AND hash = ? AND file_path = ?",
            (self.target_dir, hash, file_path),
        )
        self._conn.commit()

    def source_path_imported(self, path: str) -> bool:
        """Check if a source path has been previously imported."""
        cursor = self._conn.execute(
            "SELECT 1 FROM imports WHERE target_dir = ? AND source_path = ?",
            (self.target_dir, path),
        )
        return cursor.fetchone() is not None

    def get_import(self, source_path: str) -> dict | None:
        """Get the full import record for a source path."""
        cursor = self._conn.execute(
            "SELECT * FROM imports WHERE target_dir = ? AND source_path = ?",
            (self.target_dir, source_path),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def record_import(
        self, source_path: str, hash: str, file_path: str | None = None
    ) -> None:
        """Record a source path as imported (INSERT OR IGNORE)."""
        self._conn.execute(
            "INSERT OR IGNORE INTO imports (target_dir, source_path, hash, file_path) VALUES (?, ?, ?, ?)",
            (self.target_dir, source_path, hash, file_path),
        )
        self._conn.commit()

    def update_import(
        self, source_path: str, hash: str, file_path: str | None = None
    ) -> None:
        """Update an existing import record."""
        self._conn.execute(
            "UPDATE imports SET hash = ?, file_path = ? WHERE target_dir = ? AND source_path = ?",
            (hash, file_path, self.target_dir, source_path),
        )
        self._conn.commit()

    def get_acoustid_cache(self, file_hash: str) -> dict | None:
        """Get cached AcoustID lookup result for a file hash."""
        cursor = self._conn.execute(
            "SELECT * FROM acoustid_cache WHERE file_hash = ?",
            (file_hash,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def store_acoustid_cache(
        self,
        file_hash: str,
        fingerprint: str | None,
        duration: float | None,
        recording_id: str | None,
        metadata: dict,
    ) -> None:
        """Store an AcoustID lookup result in the cache."""
        self._conn.execute(
            "INSERT OR REPLACE INTO acoustid_cache "
            "(file_hash, fingerprint, duration, recording_id, "
            "artist, album, title, track_number, disc_number, year, lookup_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                file_hash,
                fingerprint,
                duration,
                recording_id,
                metadata.get("artist"),
                metadata.get("album"),
                metadata.get("title"),
                metadata.get("track_number"),
                metadata.get("disc_number"),
                metadata.get("year"),
                datetime.datetime.now().isoformat(),
            ),
        )
        self._conn.commit()

    def rebuild(self, target_dir: pathlib.Path) -> int:
        """Rebuild the hash DB by scanning the target directory.

        Clears all existing entries and re-hashes all files found.
        Returns the number of files indexed.
        """
        self._conn.execute(
            "DELETE FROM files WHERE target_dir = ?",
            (self.target_dir,),
        )
        self._conn.commit()

        count = 0
        for path in sorted(target_dir.rglob("*")):
            if not path.is_file():
                continue
            # Skip hidden files
            rel = path.relative_to(target_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue

            h = hash_file(path)
            self.insert(
                hash=h,
                file_size=path.stat().st_size,
                file_path=str(rel),
            )
            count += 1

        return count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
