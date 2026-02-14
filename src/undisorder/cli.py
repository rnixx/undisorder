"""CLI argument parsing and subcommand dispatch."""

from __future__ import annotations

from undisorder.config import create_config_interactive
from undisorder.config import load_config
from undisorder.config import merge_config_into_args
from undisorder.hashdb import HashDB
from undisorder.hasher import find_duplicates
from undisorder.importer import run_import
from undisorder.logging import configure_logging
from undisorder.scanner import scan

import argparse
import logging
import pathlib


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="undisorder",
        description="Photo/Video/Audio organization tool — deduplicates, sorts, and imports into a clean directory structure.",
    )
    parser.add_argument(
        "--configure", action="store_true", default=False,
        help="Create or update configuration file interactively",
    )

    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("--verbose", "-v", action="store_true", default=False,
                           help="Enable verbose (debug) output")
    verbosity.add_argument("--quiet", "-q", action="store_true", default=False,
                           help="Suppress informational output")

    sub = parser.add_subparsers(dest="command", required=False)

    # --- dupes ---
    p_dupes = sub.add_parser("dupes", help="Find duplicates in source directory")
    p_dupes.add_argument("source", type=pathlib.Path, help="Source directory to scan")

    # --- import ---
    p_import = sub.add_parser("import", help="Import files into collection")
    p_import.add_argument("source", type=pathlib.Path, help="Source directory to import from")
    p_import.add_argument(
        "--images-target",
        type=pathlib.Path,
        default=None,
        help="Target directory for photos (default: ~/Bilder/Fotos)",
    )
    p_import.add_argument(
        "--video-target",
        type=pathlib.Path,
        default=None,
        help="Target directory for videos (default: ~/Videos)",
    )
    p_import.add_argument(
        "--audio-target",
        type=pathlib.Path,
        default=None,
        help="Target directory for audio (default: ~/Musik)",
    )
    p_import.add_argument("--dry-run", action="store_true", default=None, help="Show plan without executing")
    p_import.add_argument("--move", action="store_true", default=None, help="Move instead of copy")
    p_import.add_argument(
        "--geocoding",
        choices=["off", "offline", "online"],
        default=None,
        help="GPS reverse geocoding mode (default: off)",
    )
    p_import.add_argument("--interactive", action="store_true", default=None, help="Confirm folder name suggestions")
    p_import.add_argument(
        "--identify",
        action="store_true",
        default=None,
        help="Enable AcoustID lookup for audio files with missing/incomplete tags",
    )
    p_import.add_argument(
        "--acoustid-key",
        type=str,
        default=None,
        help="AcoustID API key (or set ACOUSTID_API_KEY env var)",
    )
    p_import.add_argument(
        "--exclude", action="append", default=None, metavar="PATTERN",
        help="Glob pattern to exclude files (e.g., '*.wav'). Repeatable.",
    )
    p_import.add_argument(
        "--exclude-dir", action="append", default=None, metavar="PATTERN",
        help="Glob pattern to exclude directories (e.g., 'DAW*'). Repeatable.",
    )
    p_import.add_argument(
        "--select", action="store_true", default=None,
        help="Interactively select which directories to import",
    )
    p_import.add_argument(
        "--update", action="store_true", default=None,
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
    logger.info(f"Scanning {args.source} ...")
    result = scan(args.source)
    all_files = result.all_files
    logger.info(
        f"Found {len(all_files)} files "
        f"({len(result.photos)} photos, {len(result.videos)} videos, {len(result.audios)} audio)"
    )

    if not all_files:
        logger.info("No files found.")
        return

    groups = find_duplicates(all_files)

    if not groups:
        logger.info("No duplicates found.")
        return

    logger.info(f"\nFound {len(groups)} duplicate group(s):\n")
    for i, group in enumerate(groups, 1):
        logger.info(f"  Group {i} ({len(group.paths)} files, {group.file_size} bytes):")
        for p in group.paths:
            logger.info(f"    {p}")
        logger.info("")


def cmd_check(args: argparse.Namespace) -> None:
    """Check a target directory for duplicates using the hash DB."""
    db = HashDB(args.target)
    dupes = db.find_duplicates()
    db.close()

    if not dupes:
        logger.info("No duplicates found in target.")
        return

    logger.info(f"Found {len(dupes)} hash(es) with duplicate files:")
    for d in dupes:
        hash_str = str(d["hash"])
        logger.info(f"  Hash {hash_str[:12]}... appears {d['count']} times")


def cmd_hashdb(args: argparse.Namespace) -> None:
    """Rebuild the hash DB for a target directory."""
    logger.info(f"Rebuilding hash index for {args.target} ...")
    db = HashDB(args.target)
    count = db.rebuild(args.target)
    db.close()
    logger.info(f"Indexed {count} file(s).")


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose, args.quiet)

    if args.configure:
        create_config_interactive()
        return

    if not args.command:
        parser.print_help()
        return

    if args.command == "import":
        config = load_config()
        merge_config_into_args(args, config)

    commands = {
        "dupes": cmd_dupes,
        "import": run_import,
        "check": cmd_check,
        "hashdb": cmd_hashdb,
    }

    cmd_func = commands.get(args.command)
    if cmd_func:
        cmd_func(args)
    else:
        parser.print_help()
