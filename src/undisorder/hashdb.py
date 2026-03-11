"""SQLite hash index for target directories."""

from __future__ import annotations

from undisorder.config import _config_dir
from undisorder.hasher import hash_file

import datetime
import logging
import pathlib
import sqlite3


logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS files (
    original_hash TEXT PRIMARY KEY,
    current_hash  TEXT NOT NULL,
    target_dir    TEXT NOT NULL,
    file_path     TEXT NOT NULL,
    import_date   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_target ON files(target_dir);
CREATE INDEX IF NOT EXISTS idx_file_path ON files(file_path, target_dir);
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


def _default_db_path() -> pathlib.Path:
    """Return the default central database path."""
    return _config_dir() / "undisorder.db"


class HashDB:
    """SQLite-backed hash index for a target directory.

    Use as a context manager to get automatic commit on success and
    rollback on exception::

        with HashDB(target) as db:
            db.insert(...)
    """

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
        self._check_schema_version()
        self._conn.executescript(_SCHEMA)

    def _check_schema_version(self) -> None:
        """Verify schema version; exit if incompatible."""
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            # Fresh database — stamp with current version
            self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        elif version != _SCHEMA_VERSION:
            self._conn.close()
            logger.error(
                f"Database {self.db_path} has schema version {version}, "
                f"expected {_SCHEMA_VERSION}. Delete the database and re-run."
            )
            raise SystemExit(1)

    def __enter__(self) -> HashDB:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._conn.close()

    def insert(
        self,
        *,
        original_hash: str,
        file_path: str,
        current_hash: str | None = None,
        import_date: str | None = None,
    ) -> None:
        """Insert a file record into the hash DB."""
        if current_hash is None:
            current_hash = original_hash
        if import_date is None:
            import_date = datetime.datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO files (original_hash, current_hash, target_dir, file_path, import_date) "
            "VALUES (?, ?, ?, ?, ?)",
            (original_hash, current_hash, self.target_dir, file_path, import_date),
        )
        self._conn.commit()

    def hash_exists(self, file_hash: str) -> bool:
        """Check if original_hash exists globally (not scoped to target_dir).

        Since original_hash is the primary key, a file can only be imported once
        across all targets.
        """
        cursor = self._conn.execute(
            "SELECT 1 FROM files WHERE original_hash = ?",
            (file_hash,),
        )
        return cursor.fetchone() is not None

    def get_by_hash(self, file_hash: str) -> dict[str, object] | None:
        """Get the record for a given original_hash, or None."""
        cursor = self._conn.execute(
            "SELECT * FROM files WHERE original_hash = ?",
            (file_hash,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def count(self) -> int:
        """Return the total number of records."""
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM files WHERE target_dir = ?",
            (self.target_dir,),
        )
        return cursor.fetchone()[0]

    def delete_by_path(self, file_path: str) -> None:
        """Delete a record by file path, scoped to this target_dir."""
        self._conn.execute(
            "DELETE FROM files WHERE file_path = ? AND target_dir = ?",
            (file_path, self.target_dir),
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
        """Incremental rebuild of the hash DB by scanning the target directory.

        - Known file_path: update current_hash
        - Unknown file_path: insert with original_hash = current_hash = disk_hash
        - DB records with missing files: delete

        Returns the number of files indexed.
        """
        # Load existing records for this target_dir: file_path → original_hash
        cursor = self._conn.execute(
            "SELECT file_path, original_hash FROM files WHERE target_dir = ?",
            (self.target_dir,),
        )
        existing = {row["file_path"]: row["original_hash"] for row in cursor}
        seen_paths: set[str] = set()

        count = 0
        for path in sorted(target_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(target_dir)
            if any(part.startswith(".") for part in rel.parts):
                continue

            rel_str = str(rel)
            h = hash_file(path)
            seen_paths.add(rel_str)

            if rel_str in existing:
                # Known file — update current_hash
                self._conn.execute(
                    "UPDATE files SET current_hash = ? WHERE original_hash = ? AND target_dir = ?",
                    (h, existing[rel_str], self.target_dir),
                )
            else:
                # New file — insert with original_hash = current_hash
                try:
                    self._conn.execute(
                        "INSERT INTO files (original_hash, current_hash, target_dir, file_path, import_date) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (h, h, self.target_dir, rel_str, datetime.datetime.now().isoformat()),
                    )
                except sqlite3.IntegrityError:
                    logger.warning("Skipping duplicate hash during rebuild: %s (%s)", h[:12], rel)
                    continue
            count += 1

        # Delete DB records with missing files
        for file_path, orig_hash in existing.items():
            if file_path not in seen_paths:
                self._conn.execute(
                    "DELETE FROM files WHERE original_hash = ? AND target_dir = ?",
                    (orig_hash, self.target_dir),
                )

        self._conn.commit()
        return count

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
