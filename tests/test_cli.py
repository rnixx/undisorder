"""Tests for undisorder.cli — CLI argument parsing and subcommands."""

from undisorder.cli import build_parser
from undisorder.cli import cmd_dupes
from undisorder.cli import cmd_hashdb
from unittest.mock import MagicMock

import logging
import os
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

    def test_dupes_delete_flag(self):
        parser = build_parser()
        args = parser.parse_args(["dupes", "--delete", "/tmp/source"])
        assert args.command == "dupes"
        assert args.delete is True

    def test_dupes_delete_flag_default(self):
        parser = build_parser()
        args = parser.parse_args(["dupes", "/tmp/source"])
        assert args.delete is False

    def test_verbose_and_quiet_mutually_exclusive(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--verbose", "--quiet", "dupes", "/tmp/s"])


class TestMain:
    """Test main() entry point dispatch."""

    def test_configure_flag(self, tmp_path, monkeypatch):
        from undisorder.cli import main
        from unittest.mock import patch
        monkeypatch.setattr(
            "sys.argv", ["undisorder", "--configure"],
        )
        with patch("undisorder.cli.create_config_interactive") as mock_configure:
            main()
        mock_configure.assert_called_once()

    def test_no_command_prints_help(self, capsys, monkeypatch):
        from undisorder.cli import main
        monkeypatch.setattr("sys.argv", ["undisorder"])
        main()
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower()

    def test_import_dispatches(self, tmp_path, monkeypatch, caplog):
        from undisorder.cli import main
        source = tmp_path / "source"
        source.mkdir()
        monkeypatch.setattr(
            "sys.argv",
            ["undisorder", "import", str(source), "--dry-run"],
        )
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        with caplog.at_level(logging.INFO, logger="undisorder"):
            main()
        assert "Scanning" in caplog.text


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

    def test_empty_directory(self, tmp_path: pathlib.Path, caplog):
        args = MagicMock()
        args.source = tmp_path
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)
        assert "No media files found" in caplog.text

    def test_no_duplicates(self, tmp_path: pathlib.Path, caplog):
        (tmp_path / "a.jpg").write_bytes(b"unique 1")
        (tmp_path / "b.jpg").write_bytes(b"unique 2222")

        args = MagicMock()
        args.source = tmp_path
        args.delete = False
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)

        assert "No duplicates" in caplog.text

    def test_delete_removes_newer_duplicates(self, tmp_path: pathlib.Path, caplog):
        content = b"duplicate jpeg content here"
        oldest = tmp_path / "oldest.jpg"
        middle = tmp_path / "middle.jpg"
        newest = tmp_path / "newest.jpg"
        for f in (oldest, middle, newest):
            f.write_bytes(content)

        # Set distinct mtimes: oldest=1000, middle=2000, newest=3000
        os.utime(oldest, (1000, 1000))
        os.utime(middle, (2000, 2000))
        os.utime(newest, (3000, 3000))

        args = MagicMock()
        args.source = tmp_path
        args.delete = True
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)

        assert oldest.exists(), "oldest file should be kept"
        assert not middle.exists(), "middle file should be deleted"
        assert not newest.exists(), "newest file should be deleted"

    def test_delete_logs_kept_and_removed(self, tmp_path: pathlib.Path, caplog):
        content = b"duplicate jpeg content here"
        kept = tmp_path / "kept.jpg"
        removed = tmp_path / "removed.jpg"
        kept.write_bytes(content)
        removed.write_bytes(content)

        os.utime(kept, (1000, 1000))
        os.utime(removed, (2000, 2000))

        args = MagicMock()
        args.source = tmp_path
        args.delete = True
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)

        assert "Keeping" in caplog.text
        assert "Deleted" in caplog.text
        assert str(kept) in caplog.text
        assert str(removed) in caplog.text

    def test_without_delete_does_not_remove(self, tmp_path: pathlib.Path, caplog):
        content = b"duplicate jpeg content here"
        a = tmp_path / "a.jpg"
        b = tmp_path / "b.jpg"
        a.write_bytes(content)
        b.write_bytes(content)

        args = MagicMock()
        args.source = tmp_path
        args.delete = False
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)

        assert a.exists(), "file should not be removed without --delete"
        assert b.exists(), "file should not be removed without --delete"


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
