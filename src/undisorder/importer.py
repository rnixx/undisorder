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


def _execute_photo_video_import(
    to_import: list[tuple[pathlib.Path, str, bool, str | None, str | None]],
    metadata_map: dict[pathlib.Path, Metadata],
    args: argparse.Namespace,
    geocoder,
    img_db,
    vid_db,
) -> tuple[int, int]:
    """Execute the actual copy/move for photo/video files. Returns (imported, updated)."""
    imported = 0
    updated = 0

    # Separate updates from new files
    update_entries = []
    new_entries = []
    for entry in to_import:
        src_path, file_hash, is_video, old_hash, old_file_path = entry
        if old_file_path is not None:
            update_entries.append(entry)
        else:
            new_entries.append(entry)

    # Process updates first (no interactive grouping)
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

    # Pre-compute dirnames and geocoding for new files
    # Each entry: (src_path, file_hash, is_video, dirname, place_name)
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
        # Non-interactive: import directly
        for src_path, file_hash, is_video, dirname, place_name in tqdm(resolved_new, desc="Importing"):
            meta = metadata_map.get(src_path, Metadata(source_path=src_path))
            target_base = args.video_target if is_video else args.images_target
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

    return imported, updated


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
    if not args.dry_run:
        args.images_target.mkdir(parents=True, exist_ok=True)
        args.video_target.mkdir(parents=True, exist_ok=True)
    img_db = HashDB(args.images_target)
    vid_db = HashDB(args.video_target)

    # Phase 1: Deduplicate source files — keep oldest per hash, track dupes
    seen_hashes: dict[str, pathlib.Path] = {}  # hash -> oldest file
    unique_files: list[pathlib.Path] = []
    source_dupes: list[tuple[pathlib.Path, str]] = []  # (path, hash)
    for f in media_files:
        h = hash_file(f)
        if h not in seen_hashes:
            seen_hashes[h] = f
            unique_files.append(f)
        else:
            existing = seen_hashes[h]
            if f.stat().st_mtime < existing.stat().st_mtime:
                # f is older — replace the existing entry
                seen_hashes[h] = f
                unique_files[unique_files.index(existing)] = f
                source_dupes.append((existing, h))
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

    if args.dry_run:
        # Dry run: compute all targets and display grouped by directory
        grouped: dict[str, list[str]] = {}  # dirname -> [filenames]
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

        logger.info(f"\n[DRY RUN] Would import {len(to_import)} photo/video file(s).")
    else:
        # Normal import
        imported, updated = _execute_photo_video_import(
            to_import, metadata_map, args, geocoder, img_db, vid_db,
        )

        # Record source dupes
        for dup_path, dup_hash in source_dupes:
            is_video = classify(dup_path) is FileType.VIDEO
            db = vid_db if is_video else img_db
            db.record_import(str(dup_path), dup_hash)

        msg = f"\nImported {imported} photo/video file(s)."
        if updated:
            msg += f" Updated {updated} file(s)."
        logger.info(msg)

    img_db.close()
    vid_db.close()


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
    if not args.dry_run:
        args.audio_target.mkdir(parents=True, exist_ok=True)
    aud_db = HashDB(args.audio_target)

    # Phase 1: Deduplicate source files — keep oldest per hash, track dupes
    seen_hashes: dict[str, pathlib.Path] = {}  # hash -> oldest file
    unique_files: list[pathlib.Path] = []
    source_dupes: list[tuple[pathlib.Path, str]] = []
    for f in audio_files:
        h = hash_file(f)
        if h not in seen_hashes:
            seen_hashes[h] = f
            unique_files.append(f)
        else:
            existing = seen_hashes[h]
            if f.stat().st_mtime < existing.stat().st_mtime:
                seen_hashes[h] = f
                unique_files[unique_files.index(existing)] = f
                source_dupes.append((existing, h))
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

    if args.dry_run:
        # Dry run: compute all targets and display grouped
        grouped: dict[str, list[str]] = {}  # dirname -> [filenames]
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

        logger.info(f"\n[DRY RUN] Would import {len(to_import)} audio file(s).")
    else:
        imported = 0
        updated = 0
        for src_path, file_hash, old_hash, old_file_path in tqdm(to_import, desc="Importing audio"):
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

        # Record source dupes
        for dup_path, dup_hash in source_dupes:
            aud_db.record_import(str(dup_path), dup_hash)

        msg = f"\nImported {imported} audio file(s)."
        if updated:
            msg += f" Updated {updated} file(s)."
        logger.info(msg)

    aud_db.close()


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
