"""CLI argument parsing and subcommand dispatch."""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys

from tqdm import tqdm

from undisorder.audio_metadata import AudioMetadata, extract_audio, extract_audio_batch
from undisorder.geocoder import GeocodingMode, Geocoder
from undisorder.hashdb import HashDB
from undisorder.hasher import find_duplicates, hash_file
from undisorder.metadata import Metadata, extract_batch
from undisorder.musicbrainz import identify_audio
from undisorder.organizer import (
    determine_audio_target_path,
    determine_target_path,
    resolve_collision,
    suggest_dirname,
)
from undisorder.scanner import FileType, classify, scan
from undisorder.selector import (
    apply_exclude_patterns,
    filter_scan_result,
    group_by_directory,
    interactive_select,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="undisorder",
        description="Photo/Video/Audio organization tool — deduplicates, sorts, and imports into a clean directory structure.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- dupes ---
    p_dupes = sub.add_parser("dupes", help="Find duplicates in source directory")
    p_dupes.add_argument("source", type=pathlib.Path, help="Source directory to scan")

    # --- import ---
    p_import = sub.add_parser("import", help="Import files into collection")
    p_import.add_argument("source", type=pathlib.Path, help="Source directory to import from")
    p_import.add_argument(
        "--images-target",
        type=pathlib.Path,
        default=pathlib.Path("~/Bilder/Fotos").expanduser(),
        help="Target directory for photos (default: ~/Bilder/Fotos)",
    )
    p_import.add_argument(
        "--video-target",
        type=pathlib.Path,
        default=pathlib.Path("~/Videos").expanduser(),
        help="Target directory for videos (default: ~/Videos)",
    )
    p_import.add_argument(
        "--audio-target",
        type=pathlib.Path,
        default=pathlib.Path("~/Musik").expanduser(),
        help="Target directory for audio (default: ~/Musik)",
    )
    p_import.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    p_import.add_argument("--move", action="store_true", help="Move instead of copy")
    p_import.add_argument(
        "--geocoding",
        choices=["off", "offline", "online"],
        default="off",
        help="GPS reverse geocoding mode (default: off)",
    )
    p_import.add_argument("--interactive", action="store_true", help="Confirm folder name suggestions")
    p_import.add_argument(
        "--identify",
        action="store_true",
        help="Enable AcoustID lookup for audio files with missing/incomplete tags",
    )
    p_import.add_argument(
        "--acoustid-key",
        type=str,
        default=None,
        help="AcoustID API key (or set ACOUSTID_API_KEY env var)",
    )
    p_import.add_argument(
        "--exclude", action="append", default=[], metavar="PATTERN",
        help="Glob pattern to exclude files (e.g., '*.wav'). Repeatable.",
    )
    p_import.add_argument(
        "--exclude-dir", action="append", default=[], metavar="PATTERN",
        help="Glob pattern to exclude directories (e.g., 'DAW*'). Repeatable.",
    )
    p_import.add_argument(
        "--select", action="store_true",
        help="Interactively select which directories to import",
    )
    p_import.add_argument(
        "--update", action="store_true",
        help="Re-import files when source is newer than previous import",
    )

    # --- check ---
    p_check = sub.add_parser("check", help="Check target for duplicates")
    p_check.add_argument("target", type=pathlib.Path, help="Target directory to check")

    # --- hashdb ---
    p_hashdb = sub.add_parser("hashdb", help="Rebuild hash index for target")
    p_hashdb.add_argument("target", type=pathlib.Path, help="Target directory to index")

    return parser


def cmd_dupes(args: argparse.Namespace) -> None:
    """Find duplicates in a source directory."""
    print(f"Scanning {args.source} ...")
    result = scan(args.source)
    all_files = result.all_files
    print(
        f"Found {len(all_files)} files "
        f"({len(result.photos)} photos, {len(result.videos)} videos, {len(result.audios)} audio)"
    )

    if not all_files:
        print("No files found.")
        return

    groups = find_duplicates(all_files)

    if not groups:
        print("No duplicates found.")
        return

    print(f"\nFound {len(groups)} duplicate group(s):\n")
    for i, group in enumerate(groups, 1):
        print(f"  Group {i} ({len(group.paths)} files, {group.file_size} bytes):")
        for p in group.paths:
            print(f"    {p}")
        print()


def cmd_check(args: argparse.Namespace) -> None:
    """Check a target directory for duplicates using the hash DB."""
    db = HashDB(args.target)
    dupes = db.find_duplicates()
    db.close()

    if not dupes:
        print("No duplicates found in target.")
        return

    print(f"Found {len(dupes)} hash(es) with duplicate files:")
    for d in dupes:
        print(f"  Hash {d['hash'][:12]}... appears {d['count']} times")


def cmd_hashdb(args: argparse.Namespace) -> None:
    """Rebuild the hash DB for a target directory."""
    print(f"Rebuilding hash index for {args.target} ...")
    db = HashDB(args.target)
    count = db.rebuild(args.target)
    db.close()
    print(f"Indexed {count} file(s).")


def _source_is_newer(source_path: pathlib.Path, target_path: pathlib.Path) -> bool:
    """Check if source file mtime is strictly newer than target file mtime."""
    return source_path.stat().st_mtime > target_path.stat().st_mtime


def _import_photo_video(args: argparse.Namespace, result) -> None:
    """Import photo/video files from source into the organized collection."""
    media_files = result.photos + result.videos
    if not media_files:
        return

    print(f"Found {len(media_files)} photo/video files ({len(result.photos)} photos, {len(result.videos)} videos)")

    # Extract metadata
    print("Extracting metadata ...")
    metadata_map = extract_batch(media_files)

    # Find duplicates in source
    source_dupes_groups = find_duplicates(media_files)
    if source_dupes_groups:
        print(f"\nFound {len(source_dupes_groups)} duplicate group(s) in source:")
        for group in source_dupes_groups:
            print(f"  {len(group.paths)} copies: {group.paths[0].name}")

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
        print(f"\nSkipping {skipped} file(s) already present in target.")

    if not to_import:
        print("Nothing to import.")
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
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Importing {len(to_import)} photo/video file(s) ...\n")

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
                    print(f"  [UPDATE] {src_path} -> {old_target}")
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
        if meta.has_gps:
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
            print(f"  {src_path} -> {target_path}")
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
        print(f"\n[DRY RUN] Would import {len(to_import)} photo/video file(s).")
    else:
        msg = f"\nImported {imported} photo/video file(s)."
        if updated:
            msg += f" Updated {updated} file(s)."
        print(msg)


def _import_audio(args: argparse.Namespace, result) -> None:
    """Import audio files from source into the organized collection."""
    audio_files = result.audios
    if not audio_files:
        return

    print(f"\nFound {len(audio_files)} audio file(s)")

    # Extract audio metadata
    print("Extracting audio tags ...")
    audio_meta_map = extract_audio_batch(audio_files)

    # Optionally identify via AcoustID
    acoustid_key = args.acoustid_key or os.environ.get("ACOUSTID_API_KEY")
    if args.identify and acoustid_key:
        print("Identifying audio via AcoustID ...")
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
        print(f"\nSkipping {skipped} audio file(s) already present in target.")

    if not to_import:
        print("No audio files to import.")
        if not args.dry_run:
            for dup_path, dup_hash in source_dupes:
                aud_db.record_import(str(dup_path), dup_hash)
        aud_db.close()
        return

    # Phase 3: Import + record
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Importing {len(to_import)} audio file(s) ...\n")

    imported = 0
    updated = 0
    for src_path, file_hash, old_hash, old_file_path in tqdm(to_import, desc="Importing audio", disable=args.dry_run):
        meta = audio_meta_map.get(src_path, AudioMetadata(source_path=src_path))

        # Update: overwrite old target if it exists
        if old_file_path is not None:
            old_target = args.audio_target / old_file_path
            if old_target.exists():
                if args.dry_run:
                    print(f"  [UPDATE] {src_path} -> {old_target}")
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
            print(f"  {src_path} -> {target_path}")
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
        print(f"\n[DRY RUN] Would import {len(to_import)} audio file(s).")
    else:
        msg = f"\nImported {imported} audio file(s)."
        if updated:
            msg += f" Updated {updated} file(s)."
        print(msg)


def cmd_import(args: argparse.Namespace) -> None:
    """Import files from source into the organized collection."""
    print(f"Scanning {args.source} ...")
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
            print(f"Excluded {excluded} file(s) by pattern.")

    # Interactive selection
    if args.select:
        groups = group_by_directory(result, args.source)
        if not groups:
            print("No files to select from.")
            return
        print(f"\nFound files in {len(groups)} director{'y' if len(groups) == 1 else 'ies'}:\n")
        try:
            accepted = interactive_select(groups, args.source)
        except KeyboardInterrupt:
            print("\nAborted.")
            return
        result = filter_scan_result(result, args.source, accepted)
        print(f"\nSelected {result.total} file(s) for import.\n")

    has_media = result.photos or result.videos
    has_audio = bool(result.audios)

    if not has_media and not has_audio:
        print("No media files found.")
        return

    if has_media:
        _import_photo_video(args, result)
    if has_audio:
        _import_audio(args, result)


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    commands = {
        "dupes": cmd_dupes,
        "import": cmd_import,
        "check": cmd_check,
        "hashdb": cmd_hashdb,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
