"""Tests for undisorder.cli — CLI argument parsing and subcommands."""

from undisorder.cli import build_parser
from undisorder.cli import cmd_check
from undisorder.cli import cmd_dupes
from undisorder.cli import cmd_hashdb
from unittest.mock import MagicMock

import logging
import pathlib
import pytest


class TestBuildParser:
    """Test argparse parser construction."""

    def test_dupes_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["dupes", "/tmp/source"])
        assert args.command == "dupes"
        assert args.source == pathlib.Path("/tmp/source")

    def test_import_subcommand_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["import", "/tmp/source"])
        assert args.command == "import"
        assert args.source == pathlib.Path("/tmp/source")
        assert args.images_target is None
        assert args.video_target is None
        assert args.audio_target is None
        assert args.dry_run is None
        assert args.move is None
        assert args.geocoding is None
        assert args.interactive is None
        assert args.identify is None
        assert args.acoustid_key is None
        assert args.exclude is None
        assert args.exclude_dir is None
        assert args.select is None
        assert args.update is None

    def test_import_subcommand_all_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "import", "/tmp/source",
            "--images-target", "/custom/photos",
            "--video-target", "/custom/videos",
            "--audio-target", "/custom/music",
            "--dry-run",
            "--move",
            "--geocoding", "offline",
            "--interactive",
            "--identify",
            "--acoustid-key", "test-key-123",
            "--exclude", "*.wav",
            "--exclude", "*.aiff",
            "--exclude-dir", "DAW*",
            "--exclude-dir", ".ableton",
            "--select",
            "--update",
        ])
        assert args.images_target == pathlib.Path("/custom/photos")
        assert args.video_target == pathlib.Path("/custom/videos")
        assert args.audio_target == pathlib.Path("/custom/music")
        assert args.dry_run is True
        assert args.move is True
        assert args.geocoding == "offline"
        assert args.interactive is True
        assert args.identify is True
        assert args.acoustid_key == "test-key-123"
        assert args.exclude == ["*.wav", "*.aiff"]
        assert args.exclude_dir == ["DAW*", ".ableton"]
        assert args.select is True
        assert args.update is True

    def test_check_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["check", "/tmp/target"])
        assert args.command == "check"
        assert args.target == pathlib.Path("/tmp/target")

    def test_hashdb_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["hashdb", "/tmp/target"])
        assert args.command == "hashdb"
        assert args.target == pathlib.Path("/tmp/target")

    def test_geocoding_choices(self):
        parser = build_parser()
        for mode in ("off", "offline", "online"):
            args = parser.parse_args(["import", "/tmp/s", "--geocoding", mode])
            assert args.geocoding == mode

    def test_invalid_geocoding_rejected(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["import", "/tmp/s", "--geocoding", "invalid"])

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--verbose", "dupes", "/tmp/s"])
        assert args.verbose is True

    def test_quiet_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--quiet", "dupes", "/tmp/s"])
        assert args.quiet is True

    def test_verbose_and_quiet_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--verbose", "--quiet", "dupes", "/tmp/s"])


class TestCmdDupes:
    """Test the dupes subcommand."""

    def test_finds_duplicates(self, tmp_path: pathlib.Path, caplog):
        content = b"duplicate jpeg content here"
        (tmp_path / "a.jpg").write_bytes(content)
        (tmp_path / "b.jpg").write_bytes(content)
        (tmp_path / "unique.jpg").write_bytes(b"unique content")

        args = MagicMock()
        args.source = tmp_path
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)

        assert "1 duplicate group" in caplog.text
        assert "a.jpg" in caplog.text
        assert "b.jpg" in caplog.text

    def test_no_duplicates(self, tmp_path: pathlib.Path, caplog):
        (tmp_path / "a.jpg").write_bytes(b"unique 1")
        (tmp_path / "b.jpg").write_bytes(b"unique 2222")

        args = MagicMock()
        args.source = tmp_path
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)

        assert "No duplicates" in caplog.text


class TestCmdCheck:
    """Test the check subcommand."""

    def test_check_finds_dupes_in_target(self, tmp_path: pathlib.Path, caplog):
        target = tmp_path / "target"
        target.mkdir()
        content = b"same content in target"
        (target / "a.jpg").write_bytes(content)
        (target / "b.jpg").write_bytes(content)

        # Build the hash DB first
        from undisorder.hashdb import HashDB
        db = HashDB(target)
        db.rebuild(target)
        db.close()

        args = MagicMock()
        args.target = target
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_check(args)

        assert "duplicate" in caplog.text.lower()

    def test_check_clean_target(self, tmp_path: pathlib.Path, caplog):
        target = tmp_path / "target"
        target.mkdir()
        (target / "a.jpg").write_bytes(b"unique 1")
        (target / "b.jpg").write_bytes(b"unique 2222")

        from undisorder.hashdb import HashDB
        db = HashDB(target)
        db.rebuild(target)
        db.close()

        args = MagicMock()
        args.target = target
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_check(args)

        assert "No duplicates" in caplog.text


class TestCmdHashdb:
    """Test the hashdb subcommand."""

    def test_rebuild_hashdb(self, tmp_path: pathlib.Path, caplog):
        target = tmp_path / "target"
        target.mkdir()
        (target / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        args = MagicMock()
        args.target = target
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_hashdb(args)

        assert "1 file" in caplog.text


class TestLoggingSetup:
    """Test logging configuration."""

    def test_default_level_is_info(self):
        from undisorder.logging import configure_logging
        configure_logging()
        logger = logging.getLogger("undisorder")
        assert logger.level == logging.INFO

    def test_verbose_sets_debug(self):
        from undisorder.logging import configure_logging
        configure_logging(verbose=True)
        logger = logging.getLogger("undisorder")
        assert logger.level == logging.DEBUG

    def test_quiet_sets_warning(self):
        from undisorder.logging import configure_logging
        configure_logging(quiet=True)
        logger = logging.getLogger("undisorder")
        assert logger.level == logging.WARNING
