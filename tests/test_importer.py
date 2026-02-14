"""Tests for undisorder.importer — import photo/video/audio files."""

from undisorder.audio_metadata import AudioMetadata
from undisorder.importer import run_import
from unittest.mock import MagicMock
from unittest.mock import patch

import logging
import os
import pathlib
import time


class TestImportPhotoVideo:
    """Test photo/video import functionality."""

    def test_dry_run_does_not_copy(self, tmp_path: pathlib.Path, caplog):
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

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "dry run" in caplog.text.lower() or "DRY RUN" in caplog.text
        # File should NOT be copied
        jpg_found = any(
            f.endswith(".jpg") for dirpath, _, files in os.walk(target_img) for f in files
        )
        assert not jpg_found

    def test_import_copies_file(self, tmp_path: pathlib.Path):
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

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            run_import(args)

        # File should be copied
        found_files = []
        for dirpath, _, files in os.walk(target_img):
            for f in files:
                found_files.append(os.path.join(dirpath, f))
        assert any(f.endswith("photo.jpg") for f in found_files)
        # Original should still exist (copy mode)
        assert (source / "photo.jpg").exists()

    def test_import_move_removes_source(self, tmp_path: pathlib.Path):
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

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 5, 20),
                )
            }
            run_import(args)

        # Original should be removed (move mode)
        assert not (source / "photo.jpg").exists()

    def test_import_skips_duplicates(self, tmp_path: pathlib.Path, caplog):
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

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 1, 1),
                )
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "skip" in caplog.text.lower() or "already" in caplog.text.lower()


    def test_source_dupes_keeps_oldest_mtime(self, tmp_path: pathlib.Path):
        """When source contains duplicates, the file with the oldest mtime is imported."""
        source = tmp_path / "source"
        source.mkdir()
        target_img = tmp_path / "photos"
        target_vid = tmp_path / "videos"
        target_img.mkdir()
        target_vid.mkdir()

        content = b"\xff\xd8\xff\xd9duplicate across systems"
        newer = source / "newer.jpg"
        older = source / "older.jpg"

        newer.write_bytes(content)
        older.write_bytes(content)

        # Set older.jpg to an earlier mtime
        old_time = time.time() - 86400 * 365  # 1 year ago
        os.utime(older, (old_time, old_time))

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

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                newer: Metadata(source_path=newer, date_taken=datetime.datetime(2024, 3, 15)),
                older: Metadata(source_path=older, date_taken=datetime.datetime(2024, 3, 15)),
            }
            run_import(args)

        # Find the imported file in target
        imported_files = [
            pathlib.Path(dirpath) / f
            for dirpath, _, files in os.walk(target_img)
            for f in files if not f.endswith(".db")
        ]
        assert len(imported_files) == 1
        # The imported file should have the older mtime (copy2 preserves it)
        imported_mtime = imported_files[0].stat().st_mtime
        assert abs(imported_mtime - old_time) < 2


class TestImportAudio:
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

    def test_audio_dry_run(self, tmp_path: pathlib.Path, caplog):
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
        with patch("undisorder.importer.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "DRY RUN" in caplog.text
        # File should NOT be copied
        mp3_found = any(
            f.endswith(".mp3") for dirpath, _, files in os.walk(tmp_path / "musik") for f in files
        )
        assert not mp3_found

    def test_audio_import_copies_file(self, tmp_path: pathlib.Path):
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
        with patch("undisorder.importer.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            run_import(args)

        # File should be copied to Artist/Album/01_Title.mp3
        found_files = []
        for dirpath, _, files in os.walk(tmp_path / "musik"):
            for f in files:
                if not f.endswith(".db"):
                    found_files.append(os.path.join(dirpath, f))
        assert any("01_Come Together.mp3" in f for f in found_files)
        # Original should still exist (copy mode)
        assert (source / "song.mp3").exists()

    def test_audio_import_move(self, tmp_path: pathlib.Path):
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
        with patch("undisorder.importer.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            run_import(args)

        # Original should be removed
        assert not (source / "song.mp3").exists()

    def test_audio_import_skips_duplicates(self, tmp_path: pathlib.Path, caplog):
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
        with patch("undisorder.importer.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "skip" in caplog.text.lower() or "already" in caplog.text.lower()

    def test_audio_source_dupes_keeps_oldest_mtime(self, tmp_path: pathlib.Path):
        """When audio source contains duplicates, the file with the oldest mtime is imported."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)

        content = b"\xff\xfb\x90\x00duplicate audio across systems"
        newer = source / "newer.mp3"
        older = source / "older.mp3"

        newer.write_bytes(content)
        older.write_bytes(content)

        old_time = time.time() - 86400 * 365
        os.utime(older, (old_time, old_time))

        args = self._make_args(tmp_path)

        audio_meta_newer = AudioMetadata(
            source_path=newer, artist="Artist", album="Album",
            title="Song", track_number=1,
        )
        audio_meta_older = AudioMetadata(
            source_path=older, artist="Artist", album="Album",
            title="Song", track_number=1,
        )
        with patch("undisorder.importer.extract_audio_batch", return_value={
            newer: audio_meta_newer,
            older: audio_meta_older,
        }):
            run_import(args)

        imported_files = [
            pathlib.Path(dirpath) / f
            for dirpath, _, files in os.walk(tmp_path / "musik")
            for f in files if not f.endswith(".db")
        ]
        assert len(imported_files) == 1
        imported_mtime = imported_files[0].stat().st_mtime
        assert abs(imported_mtime - old_time) < 2

    def test_dupes_includes_audio(self, tmp_path: pathlib.Path, caplog):
        """The dupes command should find duplicates across audio files."""
        from undisorder.cli import cmd_dupes
        content = b"\xff\xfb\x90\x00duplicate audio"
        (tmp_path / "a.mp3").write_bytes(content)
        (tmp_path / "b.mp3").write_bytes(content)

        args = MagicMock()
        args.source = tmp_path
        with caplog.at_level(logging.INFO, logger="undisorder"):
            cmd_dupes(args)

        assert "1 duplicate group" in caplog.text
        assert "audio" in caplog.text.lower()


class TestImportExclude:
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

    def test_exclude_filters_files_before_import(self, tmp_path: pathlib.Path, caplog):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")
        (source / "track.wav").write_bytes(b"wav data here")

        args = self._make_args(tmp_path, exclude=["*.wav"])

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "Excluded 1 file(s) by pattern." in caplog.text
        # wav should not appear in the dry run output
        assert "track.wav" not in caplog.text

    def test_exclude_dir_filters_directories(self, tmp_path: pathlib.Path, caplog):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        daw = source / "DAW_Session"
        daw.mkdir()
        (daw / "sample.wav").write_bytes(b"wav data")
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")

        args = self._make_args(tmp_path, exclude_dir=["DAW*"])

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "photo.jpg": Metadata(
                    source_path=source / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "Excluded 1 file(s) by pattern." in caplog.text

    def test_select_with_mocked_interactive(self, tmp_path: pathlib.Path, caplog):
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
            patch("undisorder.importer.interactive_select", return_value=accepted_dirs) as mock_select,
            patch("undisorder.importer.extract_batch") as mock_extract,
        ):
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                vacation / "photo.jpg": Metadata(
                    source_path=vacation / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                )
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        mock_select.assert_called_once()
        assert "Selected 1 file(s) for import." in caplog.text

    def test_select_no_files_returns_early(self, tmp_path: pathlib.Path, caplog):
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        # Empty source directory

        args = self._make_args(tmp_path, select=True)
        with caplog.at_level(logging.INFO, logger="undisorder"):
            run_import(args)

        assert "No files to select from." in caplog.text


class TestImportSourcePath:
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

    def test_import_skips_when_source_path_already_imported(self, tmp_path, caplog):
        """File whose source_path is in imports table should be skipped even if hash changed."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        photo = source / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original content")

        args = self._make_args(tmp_path)

        # First import
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            run_import(args)

        # Simulate metadata edit — content changes, hash changes
        photo.write_bytes(b"\xff\xd8\xff\xd9modified content after tagging")

        # Second import — should skip because source_path is known
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "skip" in caplog.text.lower() or "Nothing to import" in caplog.text

    def test_source_dupes_recorded_in_imports(self, tmp_path):
        """Two files with same content — both source_paths should be in imports."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        content = b"\xff\xd8\xff\xd9same content"
        (source / "a.jpg").write_bytes(content)
        (source / "b.jpg").write_bytes(content)

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
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
            run_import(args)

        # Both source paths should be recorded in imports
        from undisorder.hashdb import HashDB
        img_db = HashDB(tmp_path / "photos")
        assert img_db.source_path_imported(str(source / "a.jpg"))
        assert img_db.source_path_imported(str(source / "b.jpg"))
        img_db.close()

    def test_import_updates_when_source_newer(self, tmp_path, caplog):
        """With --update, source newer than target triggers re-import."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        photo = source / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original")

        args = self._make_args(tmp_path)

        # First import
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            run_import(args)

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
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args2)

        # File should be updated in place
        assert old_target.exists()
        assert old_target.read_bytes() != old_content
        assert "updated" in caplog.text.lower() or "import" in caplog.text.lower()

    def test_import_skips_when_source_not_newer(self, tmp_path, caplog):
        """With --update, source NOT newer than target should be skipped."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        photo = source / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original")

        args = self._make_args(tmp_path)

        # First import
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            run_import(args)

        # Do NOT modify source — source is same age or older since copy2 preserves mtime

        # Second import with --update — should skip (source not newer)
        args2 = self._make_args(tmp_path, update=True)
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args2)

        assert "skip" in caplog.text.lower() or "Nothing to import" in caplog.text

    def test_audio_skips_when_source_path_already_imported(self, tmp_path, caplog):
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
        with patch("undisorder.importer.extract_audio_batch", return_value={song: audio_meta}):
            run_import(args)

        # Modify content (simulating tag edit)
        song.write_bytes(b"\xff\xfb\x90\x00modified audio content after tagging")

        # Second import — should skip
        with patch("undisorder.importer.extract_audio_batch", return_value={song: audio_meta}):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "skip" in caplog.text.lower() or "No audio files to import" in caplog.text
