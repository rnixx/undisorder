"""Import photo/video/audio files into organized collections."""

from __future__ import annotations

from undisorder.audio_metadata import AudioMetadata
from undisorder.audio_metadata import extract_audio_batch
from undisorder.config import _config_dir
from undisorder.geocoder import Geocoder
from undisorder.geocoder import GeocodingMode
from undisorder.hashdb import HashDB
from undisorder.hasher import hash_file
from undisorder.metadata import extract_batch
from undisorder.metadata import Metadata
from undisorder.musicbrainz import identify_audio
from undisorder.organizer import determine_audio_target_path
from undisorder.organizer import determine_target_path
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


def _source_is_newer(source_path: pathlib.Path, target_path: pathlib.Path) -> bool:
    """Check if source file mtime is strictly newer than target file mtime."""
    return source_path.stat().st_mtime > target_path.stat().st_mtime


def _import_photo_video_batch(
    batch: list[pathlib.Path],
    args: argparse.Namespace,
    geocoder,
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
    # (path, hash, is_video, old_hash, old_file_path) — old_* set for updates
    to_import: list[tuple[pathlib.Path, str, bool, str | None, str | None]] = []

    for i, f in enumerate(batch, 1):
        logger.info(f"  [{i}/{len(batch)}] {f.name}")
        h = hash_file(f)
        is_video = classify(f) is FileType.VIDEO
        db = vid_db if is_video else img_db
        target_base = args.video_target if is_video else args.images_target

        if db.hash_exists(h):
            skipped += 1
            continue

        # Source-path check
        imp = db.get_import(str(f))
        if imp is not None:
            old_target = target_base / imp["file_path"] if imp["file_path"] else None
            source_newer = old_target is not None and old_target.exists() and _source_is_newer(f, old_target)

            if not source_newer:
                skipped += 1
                continue

            if args.interactive:
                answer = input(f"  {f.name} has changed since last import. Update? [y/N]: ").strip().lower()
                if answer != "y":
                    skipped += 1
                    continue
            elif not args.update:
                skipped += 1
                continue

            to_import.append((f, h, is_video, imp["hash"], imp["file_path"]))
            continue

        to_import.append((f, h, is_video, None, None))

    if not to_import:
        return imported, skipped

    if args.dry_run:
        grouped: dict[str, list[str]] = {}
        updates: list[str] = []
        for src_path, file_hash, is_video, old_hash, old_file_path in to_import:
            meta = metadata_map.get(src_path, Metadata(source_path=src_path))
            target_base = args.video_target if is_video else args.images_target

            if old_file_path is not None:
                old_target = target_base / old_file_path
                updates.append(f"  [UPDATE] {src_path} -> {old_target}")
                continue

            place_name = None
            if meta.has_gps and meta.gps_lat is not None and meta.gps_lon is not None:
                place_name = geocoder.reverse(meta.gps_lat, meta.gps_lon)
            dirname = suggest_dirname(meta, place_name=place_name, source_root=args.source)
            grouped.setdefault(dirname, []).append(src_path.name)

        for dirname, filenames in grouped.items():
            n = len(filenames)
            label = "file" if n == 1 else "files"
            logger.info(f"  {dirname}/ ({n} {label})")
            for name in filenames:
                logger.info(f"    {name}")
        for line in updates:
            logger.info(line)

        imported = len(to_import)
    else:
        # Separate updates from new files
        update_entries = []
        new_entries = []
        for entry in to_import:
            if entry[4] is not None:
                update_entries.append(entry)
            else:
                new_entries.append(entry)

        # Process updates
        for src_path, file_hash, is_video, old_hash, old_file_path in update_entries:
            meta = metadata_map.get(src_path, Metadata(source_path=src_path))
            db = vid_db if is_video else img_db
            target_base = args.video_target if is_video else args.images_target

            old_target = target_base / old_file_path
            if old_target.exists():
                if args.move:
                    shutil.move(str(src_path), str(old_target))
                else:
                    shutil.copy2(str(src_path), str(old_target))

                if old_hash is not None:
                    db.delete_by_hash(old_hash)
                date_str = meta.date_taken.strftime("%Y:%m:%d %H:%M:%S") if meta.date_taken else None
                db.insert(
                    hash=file_hash,
                    file_size=old_target.stat().st_size,
                    file_path=old_file_path,
                    date_taken=date_str,
                    source_path=str(src_path),
                )
                db.update_import(str(src_path), file_hash, old_file_path)
                imported += 1

        # Resolve dirnames and geocoding for new files
        resolved_new: list[tuple[pathlib.Path, str, bool, str, str | None]] = []
        for src_path, file_hash, is_video, _, _ in new_entries:
            meta = metadata_map.get(src_path, Metadata(source_path=src_path))
            place_name = None
            if meta.has_gps and meta.gps_lat is not None and meta.gps_lon is not None:
                place_name = geocoder.reverse(meta.gps_lat, meta.gps_lon)
            dirname = suggest_dirname(meta, place_name=place_name, source_root=args.source)
            resolved_new.append((src_path, file_hash, is_video, dirname, place_name))

        # Interactive mode: group by dirname and prompt once per group
        if args.interactive and resolved_new:
            groups: dict[str, list[tuple[pathlib.Path, str, bool, str | None]]] = {}
            for src_path, file_hash, is_video, dirname, place_name in resolved_new:
                groups.setdefault(dirname, []).append((src_path, file_hash, is_video, place_name))

            for dirname, group_files in groups.items():
                n = len(group_files)
                label = "file" if n == 1 else "files"
                names = [f.name for f, _, _, _ in group_files]
                if n <= 5:
                    file_list = ", ".join(names)
                else:
                    file_list = ", ".join(names[:5]) + f", ... +{n - 5} more"
                user_input = input(
                    f"  {dirname}/ ({n} {label}: {file_list})\n"
                    f"  [Enter=accept, type new name, or 's' to skip]: "
                ).strip()

                if user_input == "s":
                    continue

                effective_dirname = user_input if user_input else dirname
                for src_path, file_hash, is_video, place_name in group_files:
                    target_base = args.video_target if is_video else args.images_target
                    target_path = target_base / effective_dirname / src_path.name
                    target_path = resolve_collision(target_path)

                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    if args.move:
                        shutil.move(str(src_path), str(target_path))
                    else:
                        shutil.copy2(str(src_path), str(target_path))

                    db = vid_db if is_video else img_db
                    meta = metadata_map.get(src_path, Metadata(source_path=src_path))
                    rel_path = target_path.relative_to(target_base)
                    date_str = meta.date_taken.strftime("%Y:%m:%d %H:%M:%S") if meta.date_taken else None
                    db.insert(
                        hash=file_hash,
                        file_size=src_path.stat().st_size if not args.move else target_path.stat().st_size,
                        file_path=str(rel_path),
                        date_taken=date_str,
                        source_path=str(src_path),
                    )
                    db.record_import(str(src_path), file_hash, str(rel_path))
                    imported += 1
        else:
            for src_path, file_hash, is_video, dirname, place_name in resolved_new:
                meta = metadata_map.get(src_path, Metadata(source_path=src_path))
                target_path = determine_target_path(
                    meta=meta,
                    images_target=args.images_target,
                    video_target=args.video_target,
                    is_video=is_video,
                    place_name=place_name,
                    source_root=args.source,
                )
                target_path = resolve_collision(target_path)

                target_path.parent.mkdir(parents=True, exist_ok=True)
                if args.move:
                    shutil.move(str(src_path), str(target_path))
                else:
                    shutil.copy2(str(src_path), str(target_path))

                db = vid_db if is_video else img_db
                target_base = args.video_target if is_video else args.images_target
                rel_path = target_path.relative_to(target_base)
                date_str = meta.date_taken.strftime("%Y:%m:%d %H:%M:%S") if meta.date_taken else None
                db.insert(
                    hash=file_hash,
                    file_size=src_path.stat().st_size if not args.move else target_path.stat().st_size,
                    file_path=str(rel_path),
                    date_taken=date_str,
                    source_path=str(src_path),
                )
                db.record_import(str(src_path), file_hash, str(rel_path))
                imported += 1

    return imported, skipped


def _import_photo_video(args: argparse.Namespace, result) -> int:
    """Import photo/video files from source into the organized collection.

    Returns the number of failed batches.
    """
    media_files = result.photos + result.videos
    if not media_files:
        return 0

    logger.info(f"Found {len(media_files)} photo/video files ({len(result.photos)} photos, {len(result.videos)} videos)")

    geocoding_mode = GeocodingMode(args.geocoding)
    geocoder = Geocoder(geocoding_mode)

    if not args.dry_run:
        args.images_target.mkdir(parents=True, exist_ok=True)
        args.video_target.mkdir(parents=True, exist_ok=True)
    img_db = HashDB(args.images_target)
    vid_db = HashDB(args.video_target)

    dir_groups = _group_by_source_dir(media_files, args.source)
    total_imported = 0
    total_skipped = 0
    total_failures = 0

    if args.dry_run:
        logger.info("\n[DRY RUN] Importing photo/video file(s) ...\n")

    batches = _iter_batches(dir_groups, batch_size=100)
    total_batches = len(batches)
    for batch_idx, (rel_dir, batch) in enumerate(batches, 1):
        n = len(batch)
        label = "file" if n == 1 else "files"
        logger.info(f"Processing photo/video {batch_idx}/{total_batches}: {rel_dir}/ ({n} {label})")
        try:
            imported, skipped = _import_photo_video_batch(
                batch, args, geocoder, img_db, vid_db,
            )
            total_imported += imported
            total_skipped += skipped
        except Exception as exc:
            logger.exception(f"Error importing {rel_dir}, skipping")
            _log_failure(rel_dir, "photo_video", batch, exc)
            total_failures += 1

    img_db.close()
    vid_db.close()

    if total_skipped:
        logger.info(f"\nSkipping {total_skipped} photo/video file(s) already present in target.")
    if args.dry_run:
        if total_imported:
            logger.info(f"\n[DRY RUN] Would import {total_imported} photo/video file(s).")
        else:
            logger.info("Nothing to import.")
    else:
        if total_imported:
            logger.info(f"\nImported {total_imported} photo/video file(s).")
        elif not total_skipped:
            logger.info("Nothing to import.")

    return total_failures


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

    # Hash, dedup against target, collect files to import
    # (path, hash, old_hash, old_file_path)
    to_import: list[tuple[pathlib.Path, str, str | None, str | None]] = []

    for i, f in enumerate(batch, 1):
        h = hash_file(f)

        # AcoustID identification (per-file, with cache)
        if acoustid_key and f in audio_meta_map:
            cached = aud_db.get_acoustid_cache(h)
            suffix = " \u2014 AcoustID (cached)" if cached else " \u2014 AcoustID ..."
            logger.info(f"  [{i}/{len(batch)}] {f.name}{suffix}")
            audio_meta_map[f] = identify_audio(
                f, audio_meta_map[f],
                api_key=acoustid_key, file_hash=h, db=aud_db,
            )
        else:
            logger.info(f"  [{i}/{len(batch)}] {f.name}")

        if aud_db.hash_exists(h):
            skipped += 1
            continue

        # Source-path check
        imp = aud_db.get_import(str(f))
        if imp is not None:
            old_target = args.audio_target / imp["file_path"] if imp["file_path"] else None
            source_newer = old_target is not None and old_target.exists() and _source_is_newer(f, old_target)

            if not source_newer:
                skipped += 1
                continue

            if args.interactive:
                answer = input(f"  {f.name} has changed since last import. Update? [y/N]: ").strip().lower()
                if answer != "y":
                    skipped += 1
                    continue
            elif not args.update:
                skipped += 1
                continue

            to_import.append((f, h, imp["hash"], imp["file_path"]))
            continue

        to_import.append((f, h, None, None))

    if not to_import:
        return imported, skipped

    if args.dry_run:
        grouped: dict[str, list[str]] = {}
        updates: list[str] = []
        for src_path, file_hash, old_hash, old_file_path in to_import:
            meta = audio_meta_map.get(src_path, AudioMetadata(source_path=src_path))

            if old_file_path is not None:
                old_target = args.audio_target / old_file_path
                updates.append(f"  [UPDATE] {src_path} -> {old_target}")
                continue

            target_path = determine_audio_target_path(meta, args.audio_target)
            dirname = str(target_path.parent.relative_to(args.audio_target))
            grouped.setdefault(dirname, []).append(target_path.name)

        for dirname, filenames in grouped.items():
            n = len(filenames)
            label = "file" if n == 1 else "files"
            logger.info(f"  {dirname}/ ({n} {label})")
            for name in filenames:
                logger.info(f"    {name}")
        for line in updates:
            logger.info(line)

        imported = len(to_import)
    else:
        for src_path, file_hash, old_hash, old_file_path in to_import:
            meta = audio_meta_map.get(src_path, AudioMetadata(source_path=src_path))

            # Update: overwrite old target if it exists
            if old_file_path is not None:
                old_target = args.audio_target / old_file_path
                if old_target.exists():
                    if args.move:
                        shutil.move(str(src_path), str(old_target))
                    else:
                        shutil.copy2(str(src_path), str(old_target))

                    if old_hash is not None:
                        aud_db.delete_by_hash(old_hash)
                    aud_db.insert(
                        hash=file_hash,
                        file_size=old_target.stat().st_size,
                        file_path=old_file_path,
                        source_path=str(src_path),
                    )
                    aud_db.update_import(str(src_path), file_hash, old_file_path)
                    imported += 1
                    continue

            target_path = determine_audio_target_path(meta, args.audio_target)
            target_path = resolve_collision(target_path)

            target_path.parent.mkdir(parents=True, exist_ok=True)
            if args.move:
                shutil.move(str(src_path), str(target_path))
            else:
                shutil.copy2(str(src_path), str(target_path))

            rel_path = target_path.relative_to(args.audio_target)
            aud_db.insert(
                hash=file_hash,
                file_size=src_path.stat().st_size if not args.move else target_path.stat().st_size,
                file_path=str(rel_path),
                source_path=str(src_path),
            )
            aud_db.record_import(str(src_path), file_hash, str(rel_path))
            imported += 1

    return imported, skipped


def _import_audio(args: argparse.Namespace, result) -> int:
    """Import audio files from source into the organized collection.

    Returns the number of failed batches.
    """
    audio_files = result.audios
    if not audio_files:
        return 0

    logger.info(f"\nFound {len(audio_files)} audio file(s)")

    acoustid_key = (args.acoustid_key or os.environ.get("ACOUSTID_API_KEY")) if args.identify else None

    if not args.dry_run:
        args.audio_target.mkdir(parents=True, exist_ok=True)
    aud_db = HashDB(args.audio_target)

    dir_groups = _group_by_source_dir(audio_files, args.source)
    total_imported = 0
    total_skipped = 0
    total_failures = 0

    if args.dry_run:
        logger.info("\n[DRY RUN] Importing audio file(s) ...\n")

    batches = _iter_batches(dir_groups, batch_size=10)
    total_batches = len(batches)
    for batch_idx, (rel_dir, batch) in enumerate(batches, 1):
        n = len(batch)
        label = "file" if n == 1 else "files"
        logger.info(f"Processing audio {batch_idx}/{total_batches}: {rel_dir}/ ({n} {label})")
        try:
            imported, skipped = _import_audio_batch(
                batch, args, aud_db, acoustid_key=acoustid_key,
            )
            total_imported += imported
            total_skipped += skipped
        except Exception as exc:
            logger.exception(f"Error importing audio {rel_dir}, skipping")
            _log_failure(rel_dir, "audio", batch, exc)
            total_failures += 1

    aud_db.close()

    if total_skipped:
        logger.info(f"\nSkipping {total_skipped} audio file(s) already present in target.")
    if args.dry_run:
        if total_imported:
            logger.info(f"\n[DRY RUN] Would import {total_imported} audio file(s).")
        else:
            logger.info("No audio files to import.")
    else:
        if total_imported:
            logger.info(f"\nImported {total_imported} audio file(s).")
        elif not total_skipped:
            logger.info("No audio files to import.")

    return total_failures


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
