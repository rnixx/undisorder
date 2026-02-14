"""Tests for undisorder.cli — CLI argument parsing and subcommands."""

from undisorder.audio_metadata import AudioMetadata
from undisorder.cli import _resolve_acoustid_key
from undisorder.cli import build_parser
from undisorder.cli import cmd_check
from undisorder.cli import cmd_dupes
from undisorder.cli import cmd_hashdb
from undisorder.cli import cmd_import
from unittest.mock import MagicMock
from unittest.mock import patch

import os
import pathlib
import pytest
import time


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
        assert args.images_target == pathlib.Path("~/Bilder/Fotos").expanduser()
        assert args.video_target == pathlib.Path("~/Videos").expanduser()
        assert args.audio_target == pathlib.Path("~/Musik").expanduser()
        assert args.dry_run is False
        assert args.move is False
        assert args.geocoding == "off"
        assert args.interactive is False
        assert args.identify is False
        assert args.acoustid_key is None
        assert args.exclude == []
        assert args.exclude_dir == []
        assert args.select is False
        assert args.update is False

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


class TestCmdDupes:
    """Test the dupes subcommand."""

    def test_finds_duplicates(self, tmp_path: pathlib.Path, capsys):
        content = b"duplicate jpeg content here"
        (tmp_path / "a.jpg").write_bytes(content)
        (tmp_path / "b.jpg").write_bytes(content)
        (tmp_path / "unique.jpg").write_bytes(b"unique content")

        args = MagicMock()
        args.source = tmp_path
        cmd_dupes(args)

        captured = capsys.readouterr()
        assert "1 duplicate group" in captured.out
        assert "a.jpg" in captured.out
        assert "b.jpg" in captured.out

    def test_no_duplicates(self, tmp_path: pathlib.Path, capsys):
        (tmp_path / "a.jpg").write_bytes(b"unique 1")
        (tmp_path / "b.jpg").write_bytes(b"unique 2222")

        args = MagicMock()
        args.source = tmp_path
        cmd_dupes(args)

        captured = capsys.readouterr()
        assert "No duplicates" in captured.out


class TestCmdCheck:
    """Test the check subcommand."""

    def test_check_finds_dupes_in_target(self, tmp_path: pathlib.Path, capsys):
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
        cmd_check(args)

        captured = capsys.readouterr()
        assert "duplicate" in captured.out.lower()

    def test_check_clean_target(self, tmp_path: pathlib.Path, capsys):
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
        cmd_check(args)

        captured = capsys.readouterr()
        assert "No duplicates" in captured.out


class TestCmdHashdb:
    """Test the hashdb subcommand."""

    def test_rebuild_hashdb(self, tmp_path: pathlib.Path, capsys):
        target = tmp_path / "target"
        target.mkdir()
        (target / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9")

        args = MagicMock()
        args.target = target
        cmd_hashdb(args)

        captured = capsys.readouterr()
        assert "1 file" in captured.out


class TestCmdImport:
    """Test the import subcommand."""

    def test_dry_run_does_not_copy(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        target_img = tmp_path / "photos"
        target_vid = tmp_path / "videos"
        target_img.mkdir()
        target_vid.mkdir()

        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9small jpg")

        args = MagicMock()
        args.source = source
        args.images_target = target_img
        args.video_target = target_vid
        args.dry_run = True
        args.move = False
        args.geocoding = "off"
        args.interactive = False
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False

        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            cmd_import(args)

        captured = capsys.readouterr()
        assert "dry run" in captured.out.lower() or "DRY RUN" in captured.out
        # File should NOT be copied
        import os
        jpg_found = any(
            f.endswith(".jpg") for dirpath, _, files in os.walk(target_img) for f in files
        )
        assert not jpg_found

    def test_import_copies_file(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        target_img = tmp_path / "photos"
        target_vid = tmp_path / "videos"
        target_img.mkdir()
        target_vid.mkdir()

        photo_content = b"\xff\xd8\xff\xd9a real jpeg here"
        (source / "photo.jpg").write_bytes(photo_content)

        args = MagicMock()
        args.source = source
        args.images_target = target_img
        args.video_target = target_vid
        args.dry_run = False
        args.move = False
        args.geocoding = "off"
        args.interactive = False
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False

        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            cmd_import(args)

        # File should be copied
        import os
        found_files = []
        for dirpath, _, files in os.walk(target_img):
            for f in files:
                found_files.append(os.path.join(dirpath, f))
        assert any(f.endswith("photo.jpg") for f in found_files)
        # Original should still exist (copy mode)
        assert (source / "photo.jpg").exists()

    def test_import_move_removes_source(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        target_img = tmp_path / "photos"
        target_vid = tmp_path / "videos"
        target_img.mkdir()
        target_vid.mkdir()

        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9move me")

        args = MagicMock()
        args.source = source
        args.images_target = target_img
        args.video_target = target_vid
        args.dry_run = False
        args.move = True
        args.geocoding = "off"
        args.interactive = False
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False

        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 5, 20),
                )
            }
            cmd_import(args)

        # Original should be removed (move mode)
        assert not (source / "photo.jpg").exists()

    def test_import_skips_duplicates(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        target_img = tmp_path / "photos"
        target_vid = tmp_path / "videos"
        target_img.mkdir()
        target_vid.mkdir()

        content = b"\xff\xd8\xff\xd9duplicate content"
        (source / "photo.jpg").write_bytes(content)

        # Pre-populate the hash DB with the same hash
        from undisorder.hashdb import HashDB
        from undisorder.hasher import hash_file
        db = HashDB(target_img)
        h = hash_file(source / "photo.jpg")
        db.insert(hash=h, file_size=len(content), file_path="existing/photo.jpg")
        db.close()

        args = MagicMock()
        args.source = source
        args.images_target = target_img
        args.video_target = target_vid
        args.dry_run = False
        args.move = False
        args.geocoding = "off"
        args.interactive = False
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False

        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 1, 1),
                )
            }
            cmd_import(args)

        captured = capsys.readouterr()
        assert "skip" in captured.out.lower() or "already" in captured.out.lower()


class TestCmdImportAudio:
    """Test audio import functionality."""

    def _make_args(self, tmp_path, **overrides):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        args = MagicMock()
        args.source = source
        args.images_target = tmp_path / "photos"
        args.video_target = tmp_path / "videos"
        args.audio_target = tmp_path / "musik"
        args.dry_run = False
        args.move = False
        args.geocoding = "off"
        args.interactive = False
        args.identify = False
        args.acoustid_key = None
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False
        for k, v in overrides.items():
            setattr(args, k, v)
        (tmp_path / "photos").mkdir(exist_ok=True)
        (tmp_path / "videos").mkdir(exist_ok=True)
        (tmp_path / "musik").mkdir(exist_ok=True)
        return args

    def test_audio_dry_run(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00audio content")

        args = self._make_args(tmp_path, dry_run=True)

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist="Artist",
            album="Album",
            title="Song",
            track_number=1,
        )
        with patch("undisorder.cli.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            cmd_import(args)

        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out
        # File should NOT be copied
        mp3_found = any(
            f.endswith(".mp3") for dirpath, _, files in os.walk(tmp_path / "musik") for f in files
        )
        assert not mp3_found

    def test_audio_import_copies_file(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00a real mp3 here")

        args = self._make_args(tmp_path)

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist="The Beatles",
            album="Abbey Road",
            title="Come Together",
            track_number=1,
        )
        with patch("undisorder.cli.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            cmd_import(args)

        # File should be copied to Artist/Album/01_Title.mp3
        found_files = []
        for dirpath, _, files in os.walk(tmp_path / "musik"):
            for f in files:
                if not f.endswith(".db"):
                    found_files.append(os.path.join(dirpath, f))
        assert any("01_Come Together.mp3" in f for f in found_files)
        # Original should still exist (copy mode)
        assert (source / "song.mp3").exists()

    def test_audio_import_move(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00move me")

        args = self._make_args(tmp_path, move=True)

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist="Artist",
            album="Album",
            title="Song",
            track_number=1,
        )
        with patch("undisorder.cli.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            cmd_import(args)

        # Original should be removed
        assert not (source / "song.mp3").exists()

    def test_audio_import_skips_duplicates(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir()
        content = b"\xff\xfb\x90\x00duplicate audio"
        (source / "song.mp3").write_bytes(content)

        args = self._make_args(tmp_path)

        # Pre-populate hash DB
        from undisorder.hashdb import HashDB
        from undisorder.hasher import hash_file
        db = HashDB(tmp_path / "musik")
        h = hash_file(source / "song.mp3")
        db.insert(hash=h, file_size=len(content), file_path="Artist/Album/song.mp3")
        db.close()

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist="Artist",
            album="Album",
            title="Song",
            track_number=1,
        )
        with patch("undisorder.cli.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            cmd_import(args)

        captured = capsys.readouterr()
        assert "skip" in captured.out.lower() or "already" in captured.out.lower()

    def test_dupes_includes_audio(self, tmp_path: pathlib.Path, capsys):
        """The dupes command should find duplicates across audio files."""
        content = b"\xff\xfb\x90\x00duplicate audio"
        (tmp_path / "a.mp3").write_bytes(content)
        (tmp_path / "b.mp3").write_bytes(content)

        args = MagicMock()
        args.source = tmp_path
        cmd_dupes(args)

        captured = capsys.readouterr()
        assert "1 duplicate group" in captured.out
        assert "audio" in captured.out.lower()


class TestCmdImportExclude:
    """Test --exclude and --exclude-dir filtering in import."""

    def _make_args(self, tmp_path, **overrides):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        args = MagicMock()
        args.source = source
        args.images_target = tmp_path / "photos"
        args.video_target = tmp_path / "videos"
        args.audio_target = tmp_path / "musik"
        args.dry_run = True
        args.move = False
        args.geocoding = "off"
        args.interactive = False
        args.identify = False
        args.acoustid_key = None
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False
        for k, v in overrides.items():
            setattr(args, k, v)
        (tmp_path / "photos").mkdir(exist_ok=True)
        (tmp_path / "videos").mkdir(exist_ok=True)
        (tmp_path / "musik").mkdir(exist_ok=True)
        return args

    def test_exclude_filters_files_before_import(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")
        (source / "track.wav").write_bytes(b"wav data here")

        args = self._make_args(tmp_path, exclude=["*.wav"])

        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            cmd_import(args)

        captured = capsys.readouterr()
        assert "Excluded 1 file(s) by pattern." in captured.out
        # wav should not appear in the dry run output
        assert "track.wav" not in captured.out

    def test_exclude_dir_filters_directories(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        daw = source / "DAW_Session"
        daw.mkdir()
        (daw / "sample.wav").write_bytes(b"wav data")
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")

        args = self._make_args(tmp_path, exclude_dir=["DAW*"])

        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            cmd_import(args)

        captured = capsys.readouterr()
        assert "Excluded 1 file(s) by pattern." in captured.out

    def test_select_with_mocked_interactive(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        vacation = source / "vacation"
        vacation.mkdir()
        (vacation / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")
        junk = source / "junk"
        junk.mkdir()
        (junk / "other.jpg").write_bytes(b"\xff\xd8\xff\xd9junk")

        args = self._make_args(tmp_path, select=True)

        accepted_dirs = {pathlib.PurePosixPath("vacation")}
        with (
            patch("undisorder.cli.interactive_select", return_value=accepted_dirs) as mock_select,
            patch("undisorder.cli.extract_batch") as mock_extract,
        ):
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                vacation / "photo.jpg": Metadata(
                    source_path=vacation / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            cmd_import(args)

        mock_select.assert_called_once()
        captured = capsys.readouterr()
        assert "Selected 1 file(s) for import." in captured.out

    def test_select_no_files_returns_early(self, tmp_path: pathlib.Path, capsys):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        # Empty source directory

        args = self._make_args(tmp_path, select=True)
        cmd_import(args)

        captured = capsys.readouterr()
        assert "No files to select from." in captured.out


class TestCmdImportSourcePath:
    """Test source-path-based re-import protection."""

    def _make_args(self, tmp_path, **overrides):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        args = MagicMock()
        args.source = source
        args.images_target = tmp_path / "photos"
        args.video_target = tmp_path / "videos"
        args.audio_target = tmp_path / "musik"
        args.dry_run = False
        args.move = False
        args.geocoding = "off"
        args.interactive = False
        args.identify = False
        args.acoustid_key = None
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False
        for k, v in overrides.items():
            setattr(args, k, v)
        (tmp_path / "photos").mkdir(exist_ok=True)
        (tmp_path / "videos").mkdir(exist_ok=True)
        (tmp_path / "musik").mkdir(exist_ok=True)
        return args

    def test_import_skips_when_source_path_already_imported(self, tmp_path, capsys):
        """File whose source_path is in imports table should be skipped even if hash changed."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        photo = source / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original content")

        args = self._make_args(tmp_path)

        # First import
        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            cmd_import(args)

        # Simulate metadata edit — content changes, hash changes
        photo.write_bytes(b"\xff\xd8\xff\xd9modified content after tagging")

        # Second import — should skip because source_path is known
        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            cmd_import(args)

        captured = capsys.readouterr()
        assert "skip" in captured.out.lower() or "Nothing to import" in captured.out

    def test_source_dupes_recorded_in_imports(self, tmp_path, capsys):
        """Two files with same content — both source_paths should be in imports."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        content = b"\xff\xd8\xff\xd9same content"
        (source / "a.jpg").write_bytes(content)
        (source / "b.jpg").write_bytes(content)

        args = self._make_args(tmp_path)

        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "a.jpg": Metadata(
                    source_path=source / "a.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
                source / "b.jpg": Metadata(
                    source_path=source / "b.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
            }
            cmd_import(args)

        # Both source paths should be recorded in imports
        from undisorder.hashdb import HashDB
        img_db = HashDB(tmp_path / "photos")
        assert img_db.source_path_imported(str(source / "a.jpg"))
        assert img_db.source_path_imported(str(source / "b.jpg"))
        img_db.close()

    def test_import_updates_when_source_newer(self, tmp_path, capsys):
        """With --update, source newer than target triggers re-import."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        photo = source / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original")

        args = self._make_args(tmp_path)

        # First import
        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            cmd_import(args)

        # Find where the file was imported to
        from undisorder.hashdb import HashDB
        img_db = HashDB(tmp_path / "photos")
        imp = img_db.get_import(str(photo))
        assert imp is not None
        old_target = tmp_path / "photos" / imp["file_path"]
        assert old_target.exists()
        old_content = old_target.read_bytes()
        img_db.close()

        # Make source newer by rewriting with new content
        time.sleep(0.05)
        photo.write_bytes(b"\xff\xd8\xff\xd9updated after tagging")

        # Second import with --update
        args2 = self._make_args(tmp_path, update=True)
        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            cmd_import(args2)

        captured = capsys.readouterr()
        # File should be updated in place
        assert old_target.exists()
        assert old_target.read_bytes() != old_content
        assert "updated" in captured.out.lower() or "import" in captured.out.lower()

    def test_import_skips_when_source_not_newer(self, tmp_path, capsys):
        """With --update, source NOT newer than target should be skipped."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        photo = source / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original")

        args = self._make_args(tmp_path)

        # First import
        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            cmd_import(args)

        # Do NOT modify source — source is same age or older since copy2 preserves mtime

        # Second import with --update — should skip (source not newer)
        args2 = self._make_args(tmp_path, update=True)
        with patch("undisorder.cli.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            cmd_import(args2)

        captured = capsys.readouterr()
        assert "skip" in captured.out.lower() or "Nothing to import" in captured.out

    def test_audio_skips_when_source_path_already_imported(self, tmp_path, capsys):
        """Audio files should also be skipped when source_path is in imports."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        song = source / "song.mp3"
        song.write_bytes(b"\xff\xfb\x90\x00audio content")

        args = self._make_args(tmp_path)

        audio_meta = AudioMetadata(
            source_path=song, artist="Artist", album="Album",
            title="Song", track_number=1,
        )

        # First import
        with patch("undisorder.cli.extract_audio_batch", return_value={song: audio_meta}):
            cmd_import(args)

        # Modify content (simulating tag edit)
        song.write_bytes(b"\xff\xfb\x90\x00modified audio content after tagging")

        # Second import — should skip
        with patch("undisorder.cli.extract_audio_batch", return_value={song: audio_meta}):
            cmd_import(args)

        captured = capsys.readouterr()
        assert "skip" in captured.out.lower() or "No audio files to import" in captured.out


class TestResolveAcoustidKey:
    """Test AcoustID API key resolution."""

    def test_cli_flag_takes_precedence(self):
        args = MagicMock()
        args.acoustid_key = "from-cli"
        assert _resolve_acoustid_key(args) == "from-cli"

    def test_env_var_fallback(self, monkeypatch):
        args = MagicMock()
        args.acoustid_key = None
        monkeypatch.setenv("ACOUSTID_API_KEY", "from-env")
        assert _resolve_acoustid_key(args) == "from-env"

    def test_saved_file_fallback(self, tmp_path, monkeypatch):
        args = MagicMock()
        args.acoustid_key = None
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "acoustid.key").write_text("from-file\n")
        with patch("undisorder.cli._config_dir", return_value=config_dir):
            assert _resolve_acoustid_key(args) == "from-file"

    def test_interactive_prompt_and_persist(self, tmp_path, monkeypatch):
        args = MagicMock()
        args.acoustid_key = None
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        with (
            patch("undisorder.cli._config_dir", return_value=config_dir),
            patch("builtins.input", return_value="typed-key"),
        ):
            result = _resolve_acoustid_key(args)
        assert result == "typed-key"
        assert (config_dir / "acoustid.key").read_text().strip() == "typed-key"

    def test_interactive_prompt_skip(self, tmp_path, monkeypatch):
        args = MagicMock()
        args.acoustid_key = None
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        with (
            patch("undisorder.cli._config_dir", return_value=config_dir),
            patch("builtins.input", return_value=""),
        ):
            result = _resolve_acoustid_key(args)
        assert result is None
        assert not (config_dir / "acoustid.key").exists()
