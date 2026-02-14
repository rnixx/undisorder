"""Import photo/video/audio files into organized collections."""

from __future__ import annotations

from tqdm import tqdm
from undisorder.audio_metadata import AudioMetadata
from undisorder.audio_metadata import extract_audio_batch
from undisorder.geocoder import Geocoder
from undisorder.geocoder import GeocodingMode
from undisorder.hashdb import HashDB
from undisorder.hasher import find_duplicates
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
import logging
import os
import pathlib
import shutil


logger = logging.getLogger(__name__)


def _source_is_newer(source_path: pathlib.Path, target_path: pathlib.Path) -> bool:
    """Check if source file mtime is strictly newer than target file mtime."""
    return source_path.stat().st_mtime > target_path.stat().st_mtime


def _import_photo_video(args: argparse.Namespace, result) -> None:
    """Import photo/video files from source into the organized collection."""
    media_files = result.photos + result.videos
    if not media_files:
        return

    logger.info(f"Found {len(media_files)} photo/video files ({len(result.photos)} photos, {len(result.videos)} videos)")

    # Extract metadata
    logger.info("Extracting metadata ...")
    metadata_map = extract_batch(media_files)

    # Find duplicates in source
    source_dupes_groups = find_duplicates(media_files)
    if source_dupes_groups:
        logger.info(f"\nFound {len(source_dupes_groups)} duplicate group(s) in source:")
        for group in source_dupes_groups:
            logger.info(f"  {len(group.paths)} copies: {group.paths[0].name}")

    # Set up geocoder
    geocoding_mode = GeocodingMode(args.geocoding)
    geocoder = Geocoder(geocoding_mode)

    # Set up hash DBs for targets
    args.images_target.mkdir(parents=True, exist_ok=True)
    args.video_target.mkdir(parents=True, exist_ok=True)
    img_db = HashDB(args.images_target)
    vid_db = HashDB(args.video_target)

    # Phase 1: Deduplicate source files — keep one per hash, track dupes
    seen_hashes: dict[str, pathlib.Path] = {}  # hash -> first file
    unique_files: list[pathlib.Path] = []
    source_dupes: list[tuple[pathlib.Path, str]] = []  # (path, hash)
    for f in media_files:
        h = hash_file(f)
        if h not in seen_hashes:
            seen_hashes[h] = f
            unique_files.append(f)
        else:
            source_dupes.append((f, h))

    # Phase 2: Check against target
    skipped = 0
    # (path, hash, is_video, old_hash, old_file_path) — old_* set for updates
    to_import: list[tuple[pathlib.Path, str, bool, str | None, str | None]] = []

    for f in unique_files:
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

            # Source is newer — decide based on flags
            if args.interactive:
                answer = input(f"  {f.name} has changed since last import. Update? [y/N]: ").strip().lower()
                if answer != "y":
                    skipped += 1
                    continue
            elif not args.update:
                skipped += 1
                continue

            # Mark as update
            to_import.append((f, h, is_video, imp["hash"], imp["file_path"]))
            continue

        # New file
        to_import.append((f, h, is_video, None, None))

    if skipped:
        logger.info(f"\nSkipping {skipped} file(s) already present in target.")

    if not to_import:
        logger.info("Nothing to import.")
        # Phase 4: Record source dupes even if nothing new to import
        if not args.dry_run:
            for dup_path, dup_hash in source_dupes:
                is_video = classify(dup_path) is FileType.VIDEO
                db = vid_db if is_video else img_db
                db.record_import(str(dup_path), dup_hash)
        img_db.close()
        vid_db.close()
        return

    # Phase 3: Determine targets and execute
    logger.info(f"\n{'[DRY RUN] ' if args.dry_run else ''}Importing {len(to_import)} photo/video file(s) ...\n")

    imported = 0
    updated = 0
    for src_path, file_hash, is_video, old_hash, old_file_path in tqdm(to_import, desc="Importing", disable=args.dry_run):
        meta = metadata_map.get(src_path, Metadata(source_path=src_path))
        db = vid_db if is_video else img_db
        target_base = args.video_target if is_video else args.images_target

        # Update: overwrite old target if it exists
        if old_file_path is not None:
            old_target = target_base / old_file_path
            if old_target.exists():
                if args.dry_run:
                    logger.info(f"  [UPDATE] {src_path} -> {old_target}")
                    continue

                if args.move:
                    shutil.move(str(src_path), str(old_target))
                else:
                    shutil.copy2(str(src_path), str(old_target))

                # Update DB records
                if old_hash is not None:
                    db.delete_by_hash_and_path(old_hash, old_file_path)
                date_str = meta.date_taken.strftime("%Y:%m:%d %H:%M:%S") if meta.date_taken else None
                db.insert(
                    hash=file_hash,
                    file_size=old_target.stat().st_size,
                    file_path=old_file_path,
                    date_taken=date_str,
                    source_path=str(src_path),
                )
                db.update_import(str(src_path), file_hash, old_file_path)
                updated += 1
                continue
            # Old target doesn't exist — fall through to normal import

        # Geocode if applicable
        place_name = None
        if meta.has_gps and meta.gps_lat is not None and meta.gps_lon is not None:
            place_name = geocoder.reverse(meta.gps_lat, meta.gps_lon)

        # Determine target
        target_path = determine_target_path(
            meta=meta,
            images_target=args.images_target,
            video_target=args.video_target,
            is_video=is_video,
            place_name=place_name,
        )

        if args.interactive and not args.dry_run:
            dirname = suggest_dirname(meta, place_name=place_name)
            user_input = input(f"  {src_path.name} -> {dirname}/ [Enter=accept, or type new name]: ").strip()
            if user_input:
                target_path = target_base / user_input / src_path.name

        # Resolve collisions
        target_path = resolve_collision(target_path)

        if args.dry_run:
            logger.info(f"  {src_path} -> {target_path}")
            continue

        # Execute copy/move
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if args.move:
            shutil.move(str(src_path), str(target_path))
        else:
            shutil.copy2(str(src_path), str(target_path))

        # Update hash DB
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

    # Phase 4: Record source dupes
    if not args.dry_run:
        for dup_path, dup_hash in source_dupes:
            is_video = classify(dup_path) is FileType.VIDEO
            db = vid_db if is_video else img_db
            db.record_import(str(dup_path), dup_hash)

    img_db.close()
    vid_db.close()

    if args.dry_run:
        logger.info(f"\n[DRY RUN] Would import {len(to_import)} photo/video file(s).")
    else:
        msg = f"\nImported {imported} photo/video file(s)."
        if updated:
            msg += f" Updated {updated} file(s)."
        logger.info(msg)


def _import_audio(args: argparse.Namespace, result) -> None:
    """Import audio files from source into the organized collection."""
    audio_files = result.audios
    if not audio_files:
        return

    logger.info(f"\nFound {len(audio_files)} audio file(s)")

    # Extract audio metadata
    logger.info("Extracting audio tags ...")
    audio_meta_map = extract_audio_batch(audio_files)

    # Optionally identify via AcoustID
    acoustid_key = (args.acoustid_key or os.environ.get("ACOUSTID_API_KEY")) if args.identify else None
    if args.identify and acoustid_key:
        logger.info("Identifying audio via AcoustID ...")
        for path, meta in audio_meta_map.items():
            audio_meta_map[path] = identify_audio(path, meta, api_key=acoustid_key)

    # Set up hash DB for audio target
    args.audio_target.mkdir(parents=True, exist_ok=True)
    aud_db = HashDB(args.audio_target)

    # Phase 1: Deduplicate source files — keep one per hash, track dupes
    seen_hashes: dict[str, pathlib.Path] = {}
    unique_files: list[pathlib.Path] = []
    source_dupes: list[tuple[pathlib.Path, str]] = []
    for f in audio_files:
        h = hash_file(f)
        if h not in seen_hashes:
            seen_hashes[h] = f
            unique_files.append(f)
        else:
            source_dupes.append((f, h))

    # Phase 2: Check against target
    skipped = 0
    # (path, hash, old_hash, old_file_path)
    to_import: list[tuple[pathlib.Path, str, str | None, str | None]] = []

    for f in unique_files:
        h = hash_file(f)

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

    if skipped:
        logger.info(f"\nSkipping {skipped} audio file(s) already present in target.")

    if not to_import:
        logger.info("No audio files to import.")
        if not args.dry_run:
            for dup_path, dup_hash in source_dupes:
                aud_db.record_import(str(dup_path), dup_hash)
        aud_db.close()
        return

    # Phase 3: Import + record
    logger.info(f"\n{'[DRY RUN] ' if args.dry_run else ''}Importing {len(to_import)} audio file(s) ...\n")

    imported = 0
    updated = 0
    for src_path, file_hash, old_hash, old_file_path in tqdm(to_import, desc="Importing audio", disable=args.dry_run):
        meta = audio_meta_map.get(src_path, AudioMetadata(source_path=src_path))

        # Update: overwrite old target if it exists
        if old_file_path is not None:
            old_target = args.audio_target / old_file_path
            if old_target.exists():
                if args.dry_run:
                    logger.info(f"  [UPDATE] {src_path} -> {old_target}")
                    continue

                if args.move:
                    shutil.move(str(src_path), str(old_target))
                else:
                    shutil.copy2(str(src_path), str(old_target))

                if old_hash is not None:
                    aud_db.delete_by_hash_and_path(old_hash, old_file_path)
                aud_db.insert(
                    hash=file_hash,
                    file_size=old_target.stat().st_size,
                    file_path=old_file_path,
                    source_path=str(src_path),
                )
                aud_db.update_import(str(src_path), file_hash, old_file_path)
                updated += 1
                continue

        target_path = determine_audio_target_path(meta, args.audio_target)
        target_path = resolve_collision(target_path)

        if args.dry_run:
            logger.info(f"  {src_path} -> {target_path}")
            continue

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

    # Phase 4: Record source dupes
    if not args.dry_run:
        for dup_path, dup_hash in source_dupes:
            aud_db.record_import(str(dup_path), dup_hash)

    aud_db.close()

    if args.dry_run:
        logger.info(f"\n[DRY RUN] Would import {len(to_import)} audio file(s).")
    else:
        msg = f"\nImported {imported} audio file(s)."
        if updated:
            msg += f" Updated {updated} file(s)."
        logger.info(msg)


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

    if has_media:
        _import_photo_video(args, result)
    if has_audio:
        _import_audio(args, result)
