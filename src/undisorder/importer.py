"""Import photo/video/audio files into organized collections."""

from __future__ import annotations

from undisorder.audio_metadata import AudioMetadata
from undisorder.audio_metadata import extract_audio_batch
from undisorder.audio_metadata import write_audio_tags
from undisorder.config import config_dir
from undisorder.hashdb import HashDB
from undisorder.hasher import hash_file
from undisorder.metadata import extract_batch
from undisorder.metadata import Metadata
from undisorder.musicbrainz import identify_audio
from undisorder.organizer import determine_audio_target_path
from undisorder.organizer import resolve_collision
from undisorder.organizer import suggest_dirname
from undisorder.scanner import classify
from undisorder.scanner import FileType
from undisorder.scanner import scan
from undisorder.selector import apply_exclude_patterns
from undisorder.selector import filter_scan_result
from undisorder.selector import group_by_directory
from undisorder.selector import interactive_select

import argparse
import datetime
import json
import logging
import os
import pathlib
import shutil
import sys
import traceback

logger = logging.getLogger(__name__)


def _log_failure(
    rel_dir: pathlib.PurePosixPath,
    media_type: str,
    batch: list[pathlib.Path],
    exc: Exception,
) -> None:
    """Append a structured failure record to the import failures log."""
    log_path = config_dir() / "import_failures.jsonl"
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "source_dir": str(rel_dir),
        "media_type": media_type,
        "files": [str(f) for f in batch],
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "traceback": traceback.format_exc(),
    }
    with open(log_path, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def _group_by_source_dir(
    files: list[pathlib.Path],
    source_root: pathlib.Path,
) -> list[tuple[pathlib.PurePosixPath, list[pathlib.Path]]]:
    """Group files by parent directory relative to source_root.

    Returns list of (rel_dir, [files]) sorted deepest-first, then alphabetically.
    """
    groups: dict[pathlib.PurePosixPath, list[pathlib.Path]] = {}
    for f in files:
        rel = pathlib.PurePosixPath(f.parent.relative_to(source_root))
        groups.setdefault(rel, []).append(f)

    # Sort: deepest first (most path parts), then alphabetical
    return sorted(groups.items(), key=lambda item: (-len(item[0].parts), item[0]))


def _iter_batches(
    dir_groups: list[tuple[pathlib.PurePosixPath, list[pathlib.Path]]],
    batch_size: int,
) -> list[tuple[pathlib.PurePosixPath, list[pathlib.Path]]]:
    """Slice directory groups into batches of at most batch_size files.

    Small directories pass through as-is. Large directories yield multiple chunks.
    """
    batches: list[tuple[pathlib.PurePosixPath, list[pathlib.Path]]] = []
    for rel_dir, files in dir_groups:
        for i in range(0, len(files), batch_size):
            batches.append((rel_dir, files[i : i + batch_size]))
    return batches


# ---------------------------------------------------------------------------
# Base importer
# ---------------------------------------------------------------------------


class BaseImporter:
    """Base class for media file importers.

    Subclasses override hooks for metadata extraction, target path logic,
    and optional pre/post-import steps.  The shared workflow is:

        extract metadata → hash → dedup → (dry-run log | copy/move + db insert)
    """

    media_label: str = ""
    failure_label: str = ""
    batch_size: int = 100

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self._dbs: list[HashDB] = []

    def __enter__(self) -> BaseImporter:
        self._open_dbs()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        for db in self._dbs:
            db.close()

    # -- hooks for subclasses -----------------------------------------------

    def _open_dbs(self) -> None:
        """Open database connections.  Populate self._dbs."""
        raise NotImplementedError

    def _get_db(self, src_path: pathlib.Path) -> HashDB:
        """Return the HashDB instance for *src_path*."""
        raise NotImplementedError

    def _get_target_base(self, src_path: pathlib.Path) -> pathlib.Path:
        """Return the root target directory for *src_path*."""
        raise NotImplementedError

    def _extract_metadata(self, batch: list[pathlib.Path]) -> dict:
        """Return a mapping {src_path: metadata} for the batch."""
        raise NotImplementedError

    def _default_metadata(self, src_path: pathlib.Path):
        """Return a fallback metadata object when extraction yielded nothing."""
        raise NotImplementedError

    def _determine_target_path(self, src_path: pathlib.Path, metadata) -> pathlib.Path:
        """Return the full target path (before collision resolution)."""
        raise NotImplementedError

    def _pre_dedup(
        self,
        f: pathlib.Path,
        i: int,
        batch_len: int,
        file_hash: str,
        metadata_map: dict,
    ) -> None:
        """Hook called per-file before the dedup check.  Default: log progress."""
        if not self.args.dry_run:
            logger.info(f"  [{i}/{batch_len}] {f.name}")

    def _should_move(self, src_path: pathlib.Path) -> bool:
        """Whether to move (vs copy) *src_path*."""
        return self.args.move

    def _post_import(
        self,
        src_path: pathlib.Path,
        target_path: pathlib.Path,
        file_hash: str,
        metadata,
    ) -> str:
        """Hook after copy/move.  Returns the current_hash to store in the DB."""
        return file_hash

    def _post_move_cleanup(self, src_path: pathlib.Path) -> None:
        """Hook for deferred cleanup (e.g. delete source after copy + tag write)."""

    # -- shared workflow ----------------------------------------------------

    def run(self, files: list[pathlib.Path]) -> int:
        """Run the full batch pipeline.  Returns the number of failed batches."""
        dir_groups = _group_by_source_dir(files, self.args.source)
        total_imported = 0
        total_skipped = 0
        total_failures = 0

        if self.args.dry_run:
            logger.info(f"\n[DRY RUN] Importing {self.media_label} file(s) ...\n")

        batches = _iter_batches(dir_groups, batch_size=self.batch_size)
        total_batches = len(batches)
        for batch_idx, (rel_dir, batch) in enumerate(batches, 1):
            n = len(batch)
            label = "file" if n == 1 else "files"
            logger.info(
                f"Processing {self.media_label} {batch_idx}/{total_batches}: {rel_dir}/ ({n} {label})"
            )
            try:
                imported, skipped = self.import_batch(batch)
                total_imported += imported
                total_skipped += skipped
            except Exception as exc:
                logger.exception(f"Error importing {rel_dir}, skipping")
                _log_failure(rel_dir, self.failure_label, batch, exc)
                total_failures += 1

        if total_skipped:
            logger.info(
                f"\nSkipping {total_skipped} {self.media_label} file(s) already present in target."
            )
        if self.args.dry_run:
            if total_imported:
                logger.info(
                    f"\n[DRY RUN] Would import {total_imported} {self.media_label} file(s)."
                )
            else:
                logger.info(f"No {self.media_label} files to import.")
        else:
            if total_imported:
                logger.info(f"\nImported {total_imported} {self.media_label} file(s).")
            elif not total_skipped:
                logger.info(f"No {self.media_label} files to import.")

        return total_failures

    def import_batch(self, batch: list[pathlib.Path]) -> tuple[int, int]:
        """Process one batch of files.  Returns (imported, skipped)."""
        metadata_map = self._extract_metadata(batch)

        imported = 0
        skipped = 0
        to_import: list[tuple[pathlib.Path, str]] = []

        for i, f in enumerate(batch, 1):
            h = hash_file(f)

            self._pre_dedup(f, i, len(batch), h, metadata_map)

            if self._get_db(f).hash_exists(h):
                skipped += 1
                if self.args.dry_run:
                    logger.info(
                        f"  [{i}/{len(batch)}] {f.name} (already imported, skipping)"
                    )
                continue

            to_import.append((f, h))

        if not to_import:
            return imported, skipped

        if self.args.dry_run:
            grouped: dict[str, list[str]] = {}
            for src_path, file_hash in to_import:
                meta = metadata_map.get(src_path, self._default_metadata(src_path))
                target_path = self._determine_target_path(src_path, meta)
                target_base = self._get_target_base(src_path)
                dirname = str(target_path.parent.relative_to(target_base))
                grouped.setdefault(dirname, []).append(target_path.name)

            for dirname, filenames in grouped.items():
                n = len(filenames)
                label = "file" if n == 1 else "files"
                logger.info(f"  {dirname}/ ({n} {label})")
                for name in filenames:
                    logger.info(f"    {name}")

            imported = len(to_import)
        else:
            for src_path, file_hash in to_import:
                meta = metadata_map.get(src_path, self._default_metadata(src_path))
                target_path = self._determine_target_path(src_path, meta)
                target_path = resolve_collision(target_path)

                target_path.parent.mkdir(parents=True, exist_ok=True)
                if self._should_move(src_path):
                    shutil.move(str(src_path), str(target_path))
                else:
                    shutil.copy2(str(src_path), str(target_path))

                current_hash = self._post_import(src_path, target_path, file_hash, meta)

                target_base = self._get_target_base(src_path)
                rel_path = target_path.relative_to(target_base)
                self._get_db(src_path).insert(
                    original_hash=file_hash,
                    current_hash=current_hash,
                    file_path=str(rel_path),
                )
                imported += 1

                self._post_move_cleanup(src_path)

        return imported, skipped


# ---------------------------------------------------------------------------
# Photo / Video importer
# ---------------------------------------------------------------------------


class PhotoVideoImporter(BaseImporter):
    """Importer for photo and video files."""

    media_label = "photo/video"
    failure_label = "photo_video"
    batch_size = 100

    def _open_dbs(self) -> None:
        if not self.args.dry_run:
            self.args.images_target.mkdir(parents=True, exist_ok=True)
            self.args.video_target.mkdir(parents=True, exist_ok=True)
        self._img_db = HashDB(self.args.images_target)
        self._vid_db = HashDB(self.args.video_target)
        self._dbs = [self._img_db, self._vid_db]

    def _get_db(self, src_path: pathlib.Path) -> HashDB:
        return self._vid_db if classify(src_path) is FileType.VIDEO else self._img_db

    def _get_target_base(self, src_path: pathlib.Path) -> pathlib.Path:
        return (
            self.args.video_target
            if classify(src_path) is FileType.VIDEO
            else self.args.images_target
        )

    def _extract_metadata(self, batch: list[pathlib.Path]) -> dict:
        return extract_batch(batch)

    def _default_metadata(self, src_path: pathlib.Path):
        return Metadata(source_path=src_path)

    def _determine_target_path(self, src_path: pathlib.Path, metadata) -> pathlib.Path:
        dirname = suggest_dirname(metadata, source_root=self.args.source)
        target_base = self._get_target_base(src_path)
        return target_base / dirname / src_path.name


# ---------------------------------------------------------------------------
# Audio importer
# ---------------------------------------------------------------------------


class AudioImporter(BaseImporter):
    """Importer for audio files with optional AcoustID identification."""

    media_label = "audio"
    failure_label = "audio"
    batch_size = 10

    def __init__(
        self,
        args: argparse.Namespace,
        *,
        acoustid_key: str | None = None,
    ) -> None:
        super().__init__(args)
        self._acoustid_key = acoustid_key
        self._identified: set[pathlib.Path] = set()

    def _open_dbs(self) -> None:
        if not self.args.dry_run:
            self.args.audio_target.mkdir(parents=True, exist_ok=True)
        self._aud_db = HashDB(self.args.audio_target)
        self._dbs = [self._aud_db]

    def _get_db(self, src_path: pathlib.Path) -> HashDB:
        return self._aud_db

    def _get_target_base(self, src_path: pathlib.Path) -> pathlib.Path:
        return self.args.audio_target

    def _extract_metadata(self, batch: list[pathlib.Path]) -> dict:
        return extract_audio_batch(batch)

    def _default_metadata(self, src_path: pathlib.Path):
        return AudioMetadata(source_path=src_path)

    def _determine_target_path(self, src_path: pathlib.Path, metadata) -> pathlib.Path:
        return determine_audio_target_path(metadata, self.args.audio_target)

    def _pre_dedup(self, f, i, batch_len, file_hash, metadata_map) -> None:
        if self._acoustid_key and f in metadata_map:
            cached = self._aud_db.get_acoustid_cache(file_hash)
            suffix = " \u2014 AcoustID (cached)" if cached else " \u2014 AcoustID ..."
            logger.info(f"  [{i}/{batch_len}] {f.name}{suffix}")
            original = metadata_map[f]
            metadata_map[f] = identify_audio(
                f,
                original,
                api_key=self._acoustid_key,
                file_hash=file_hash,
                db=self._aud_db,
            )
            if metadata_map[f] is not original:
                self._identified.add(f)
        elif not self.args.dry_run:
            logger.info(f"  [{i}/{batch_len}] {f.name}")

    def _should_move(self, src_path: pathlib.Path) -> bool:
        return self.args.move and not self._acoustid_key

    def _post_import(self, src_path, target_path, file_hash, metadata) -> str:
        if src_path in self._identified:
            write_audio_tags(target_path, metadata)
            return hash_file(target_path)
        return file_hash

    def _post_move_cleanup(self, src_path: pathlib.Path) -> None:
        if self.args.move and self._acoustid_key:
            src_path.unlink()

    def import_batch(self, batch: list[pathlib.Path]) -> tuple[int, int]:
        self._identified = set()
        return super().import_batch(batch)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _import_photo_video(args: argparse.Namespace, result) -> int:
    """Import photo/video files from source into the organized collection."""
    media_files = result.photos + result.videos
    if not media_files:
        return 0

    logger.info(
        f"Found {len(media_files)} photo/video files ({len(result.photos)} photos, {len(result.videos)} videos)"
    )

    with PhotoVideoImporter(args) as importer:
        return importer.run(media_files)


def _import_audio(args: argparse.Namespace, result) -> int:
    """Import audio files from source into the organized collection."""
    audio_files = result.audios
    if not audio_files:
        return 0

    logger.info(f"\nFound {len(audio_files)} audio file(s)")

    if args.identify and args.dry_run:
        logger.info("[DRY RUN] Skipping --identify (no API calls in dry-run mode)")

    acoustid_key = (
        (args.acoustid_key or os.environ.get("ACOUSTID_API_KEY"))
        if args.identify and not args.dry_run
        else None
    )

    if args.identify and acoustid_key is None and not args.dry_run:
        logger.error(
            "--identify requires an AcoustID API key (--acoustid-key, ACOUSTID_API_KEY, or config.toml)"
        )
        sys.exit(1)

    with AudioImporter(args, acoustid_key=acoustid_key) as importer:
        return importer.run(audio_files)


def run_import(args: argparse.Namespace) -> None:
    """Import files from source into the organized collection."""
    logger.info(f"Scanning {args.source} ...")
    result = scan(args.source)

    # Apply exclude patterns (non-interactive)
    if args.exclude or args.exclude_dir:
        before = result.total
        result = apply_exclude_patterns(
            result,
            args.source,
            exclude_file=args.exclude,
            exclude_dir=args.exclude_dir,
        )
        excluded = before - result.total
        if excluded:
            logger.info(f"Excluded {excluded} file(s) by pattern.")

    # Interactive selection
    if args.select:
        groups = group_by_directory(result, args.source)
        if not groups:
            logger.info("No files to select from.")
            return
        logger.info(
            f"\nFound files in {len(groups)} director{'y' if len(groups) == 1 else 'ies'}:\n"
        )
        try:
            accepted = interactive_select(groups, args.source)
        except KeyboardInterrupt:
            logger.info("\nAborted.")
            return
        result = filter_scan_result(result, args.source, accepted)
        logger.info(f"\nSelected {result.total} file(s) for import.\n")

    has_media = result.photos or result.videos
    has_audio = bool(result.audios)

    if not has_media and not has_audio:
        logger.info("No media files found.")
        return

    failures = 0
    if has_media:
        failures += _import_photo_video(args, result)
    if has_audio:
        failures += _import_audio(args, result)

    if failures:
        log_path = config_dir() / "import_failures.jsonl"
        logger.warning(f"\n{failures} batch(es) failed. Details written to {log_path}")
