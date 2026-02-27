"""Import photo/video/audio files into organized collections."""

from __future__ import annotations

from undisorder.audio_metadata import AudioMetadata
from undisorder.audio_metadata import extract_audio_batch
from undisorder.audio_metadata import write_audio_tags
from undisorder.config import _config_dir
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
import collections.abc
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
    log_path = _config_dir() / "import_failures.jsonl"
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
    files: list[pathlib.Path], source_root: pathlib.Path,
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


def _import_photo_video_batch(
    batch: list[pathlib.Path],
    args: argparse.Namespace,
    img_db: HashDB,
    vid_db: HashDB,
) -> tuple[int, int]:
    """Process one batch of photo/video files: metadata → hash → dedup → import.

    Returns (imported, skipped).
    """
    metadata_map = extract_batch(batch)

    imported = 0
    skipped = 0

    # Hash, dedup against target, and collect files to import
    to_import: list[tuple[pathlib.Path, str, bool]] = []

    for i, f in enumerate(batch, 1):
        if not args.dry_run:
            logger.info(f"  [{i}/{len(batch)}] {f.name}")
        h = hash_file(f)
        is_video = classify(f) is FileType.VIDEO
        db = vid_db if is_video else img_db

        if db.hash_exists(h):
            skipped += 1
            if args.dry_run:
                logger.info(f"  [{i}/{len(batch)}] {f.name} (already imported, skipping)")
            continue

        to_import.append((f, h, is_video))

    if not to_import:
        return imported, skipped

    if args.dry_run:
        grouped: dict[str, list[str]] = {}
        for src_path, file_hash, is_video in to_import:
            meta = metadata_map.get(src_path, Metadata(source_path=src_path))
            dirname = suggest_dirname(meta, source_root=args.source)
            grouped.setdefault(dirname, []).append(src_path.name)

        for dirname, filenames in grouped.items():
            n = len(filenames)
            label = "file" if n == 1 else "files"
            logger.info(f"  {dirname}/ ({n} {label})")
            for name in filenames:
                logger.info(f"    {name}")

        imported = len(to_import)
    else:
        for src_path, file_hash, is_video in to_import:
            meta = metadata_map.get(src_path, Metadata(source_path=src_path))
            dirname = suggest_dirname(meta, source_root=args.source)

            target_base = args.video_target if is_video else args.images_target
            target_path = target_base / dirname / src_path.name
            target_path = resolve_collision(target_path)

            target_path.parent.mkdir(parents=True, exist_ok=True)
            if args.move:
                shutil.move(str(src_path), str(target_path))
            else:
                shutil.copy2(str(src_path), str(target_path))

            db = vid_db if is_video else img_db
            rel_path = target_path.relative_to(target_base)
            db.insert(
                original_hash=file_hash,
                file_path=str(rel_path),
            )
            imported += 1

    return imported, skipped


def _run_batch_pipeline(
    files: list[pathlib.Path],
    args: argparse.Namespace,
    *,
    media_label: str,
    failure_label: str,
    batch_size: int,
    batch_fn: collections.abc.Callable[[list[pathlib.Path]], tuple[int, int]],
) -> int:
    """Shared batch loop: group → iterate → try/except → summary.

    batch_fn(batch) returns (imported, skipped).
    Returns the number of failed batches.
    """
    dir_groups = _group_by_source_dir(files, args.source)
    total_imported = 0
    total_skipped = 0
    total_failures = 0

    if args.dry_run:
        logger.info(f"\n[DRY RUN] Importing {media_label} file(s) ...\n")

    batches = _iter_batches(dir_groups, batch_size=batch_size)
    total_batches = len(batches)
    for batch_idx, (rel_dir, batch) in enumerate(batches, 1):
        n = len(batch)
        label = "file" if n == 1 else "files"
        logger.info(f"Processing {media_label} {batch_idx}/{total_batches}: {rel_dir}/ ({n} {label})")
        try:
            imported, skipped = batch_fn(batch)
            total_imported += imported
            total_skipped += skipped
        except Exception as exc:
            logger.exception(f"Error importing {rel_dir}, skipping")
            _log_failure(rel_dir, failure_label, batch, exc)
            total_failures += 1

    if total_skipped:
        logger.info(f"\nSkipping {total_skipped} {media_label} file(s) already present in target.")
    if args.dry_run:
        if total_imported:
            logger.info(f"\n[DRY RUN] Would import {total_imported} {media_label} file(s).")
        else:
            logger.info(f"No {media_label} files to import.")
    else:
        if total_imported:
            logger.info(f"\nImported {total_imported} {media_label} file(s).")
        elif not total_skipped:
            logger.info(f"No {media_label} files to import.")

    return total_failures


def _import_photo_video(args: argparse.Namespace, result) -> int:
    """Import photo/video files from source into the organized collection."""
    media_files = result.photos + result.videos
    if not media_files:
        return 0

    logger.info(f"Found {len(media_files)} photo/video files ({len(result.photos)} photos, {len(result.videos)} videos)")

    if not args.dry_run:
        args.images_target.mkdir(parents=True, exist_ok=True)
        args.video_target.mkdir(parents=True, exist_ok=True)
    img_db = HashDB(args.images_target)
    vid_db = HashDB(args.video_target)

    failures = _run_batch_pipeline(
        media_files, args,
        media_label="photo/video",
        failure_label="photo_video",
        batch_size=100,
        batch_fn=lambda batch: _import_photo_video_batch(batch, args, img_db, vid_db),
    )

    img_db.close()
    vid_db.close()
    return failures


def _import_audio_batch(
    batch: list[pathlib.Path],
    args: argparse.Namespace,
    aud_db: HashDB,
    *,
    acoustid_key: str | None = None,
) -> tuple[int, int]:
    """Process one batch of audio files: metadata → hash → identify → dedup → import.

    Returns (imported, skipped).
    """
    audio_meta_map = extract_audio_batch(batch)

    imported = 0
    skipped = 0
    identified: set[pathlib.Path] = set()

    # Hash, dedup against target, collect files to import
    to_import: list[tuple[pathlib.Path, str]] = []

    for i, f in enumerate(batch, 1):
        h = hash_file(f)

        # AcoustID identification (per-file, with cache)
        if acoustid_key and f in audio_meta_map:
            cached = aud_db.get_acoustid_cache(h)
            suffix = " \u2014 AcoustID (cached)" if cached else " \u2014 AcoustID ..."
            logger.info(f"  [{i}/{len(batch)}] {f.name}{suffix}")
            original = audio_meta_map[f]
            audio_meta_map[f] = identify_audio(
                f, original,
                api_key=acoustid_key, file_hash=h, db=aud_db,
            )
            if audio_meta_map[f] is not original:
                identified.add(f)
        elif not args.dry_run:
            logger.info(f"  [{i}/{len(batch)}] {f.name}")

        if aud_db.hash_exists(h):
            skipped += 1
            if args.dry_run:
                logger.info(f"  [{i}/{len(batch)}] {f.name} (already imported, skipping)")
            continue

        to_import.append((f, h))

    if not to_import:
        return imported, skipped

    if args.dry_run:
        grouped: dict[str, list[str]] = {}
        for src_path, file_hash in to_import:
            meta = audio_meta_map.get(src_path, AudioMetadata(source_path=src_path))
            target_path = determine_audio_target_path(meta, args.audio_target)
            dirname = str(target_path.parent.relative_to(args.audio_target))
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
            meta = audio_meta_map.get(src_path, AudioMetadata(source_path=src_path))

            target_path = determine_audio_target_path(meta, args.audio_target)
            target_path = resolve_collision(target_path)

            target_path.parent.mkdir(parents=True, exist_ok=True)
            if args.move and not acoustid_key:
                shutil.move(str(src_path), str(target_path))
            else:
                shutil.copy2(str(src_path), str(target_path))

            current_hash = file_hash
            if src_path in identified:
                write_audio_tags(target_path, meta)
                current_hash = hash_file(target_path)

            rel_path = target_path.relative_to(args.audio_target)
            aud_db.insert(
                original_hash=file_hash,
                current_hash=current_hash,
                file_path=str(rel_path),
            )
            imported += 1

            if args.move and acoustid_key:
                src_path.unlink()

    return imported, skipped


def _import_audio(args: argparse.Namespace, result) -> int:
    """Import audio files from source into the organized collection."""
    audio_files = result.audios
    if not audio_files:
        return 0

    logger.info(f"\nFound {len(audio_files)} audio file(s)")

    if args.identify and args.dry_run:
        logger.info("[DRY RUN] Skipping --identify (no API calls in dry-run mode)")

    acoustid_key = (args.acoustid_key or os.environ.get("ACOUSTID_API_KEY")) if args.identify and not args.dry_run else None

    if args.identify and acoustid_key is None and not args.dry_run:
        logger.error("--identify requires an AcoustID API key (--acoustid-key, ACOUSTID_API_KEY, or config.toml)")
        sys.exit(1)

    if not args.dry_run:
        args.audio_target.mkdir(parents=True, exist_ok=True)
    aud_db = HashDB(args.audio_target)

    failures = _run_batch_pipeline(
        audio_files, args,
        media_label="audio",
        failure_label="audio",
        batch_size=10,
        batch_fn=lambda batch: _import_audio_batch(batch, args, aud_db, acoustid_key=acoustid_key),
    )

    aud_db.close()
    return failures


def run_import(args: argparse.Namespace) -> None:
    """Import files from source into the organized collection."""
    logger.info(f"Scanning {args.source} ...")
    result = scan(args.source)

    # Apply exclude patterns (non-interactive)
    if args.exclude or args.exclude_dir:
        before = result.total
        result = apply_exclude_patterns(
            result, args.source,
            exclude_file=args.exclude, exclude_dir=args.exclude_dir,
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
        logger.info(f"\nFound files in {len(groups)} director{'y' if len(groups) == 1 else 'ies'}:\n")
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
        log_path = _config_dir() / "import_failures.jsonl"
        logger.warning(
            f"\n{failures} batch(es) failed. Details written to {log_path}"
        )
