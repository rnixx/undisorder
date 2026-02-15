"""Tests for undisorder.importer — import photo/video/audio files."""

from undisorder.audio_metadata import AudioMetadata
from undisorder.importer import _group_by_source_dir
from undisorder.importer import _iter_batches
from undisorder.importer import _log_failure
from undisorder.importer import run_import
from unittest.mock import MagicMock
from unittest.mock import patch

import json
import logging
import os
import pathlib
import time


class TestGroupBySourceDir:
    """Test _group_by_source_dir helper."""

    def test_groups_by_parent_directory(self, tmp_path: pathlib.Path):
        """Files from 2 dirs grouped correctly."""
        source = tmp_path / "source"
        dir_a = source / "vacation"
        dir_b = source / "work"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        f1 = dir_a / "photo1.jpg"
        f2 = dir_a / "photo2.jpg"
        f3 = dir_b / "photo3.jpg"
        f1.touch()
        f2.touch()
        f3.touch()

        groups = _group_by_source_dir([f1, f2, f3], source)
        group_dict = dict(groups)

        assert pathlib.PurePosixPath("vacation") in group_dict
        assert pathlib.PurePosixPath("work") in group_dict
        assert set(group_dict[pathlib.PurePosixPath("vacation")]) == {f1, f2}
        assert group_dict[pathlib.PurePosixPath("work")] == [f3]

    def test_deepest_first(self, tmp_path: pathlib.Path):
        """Deepest directories come first: a/b/c/ before a/b/ before a/."""
        source = tmp_path / "source"
        d1 = source / "a"
        d2 = source / "a" / "b"
        d3 = source / "a" / "b" / "c"
        d1.mkdir(parents=True)
        d2.mkdir(parents=True)
        d3.mkdir(parents=True)
        f1 = d1 / "f1.jpg"
        f2 = d2 / "f2.jpg"
        f3 = d3 / "f3.jpg"
        f1.touch()
        f2.touch()
        f3.touch()

        groups = _group_by_source_dir([f1, f2, f3], source)
        dir_order = [d for d, _ in groups]

        assert dir_order == [
            pathlib.PurePosixPath("a/b/c"),
            pathlib.PurePosixPath("a/b"),
            pathlib.PurePosixPath("a"),
        ]

    def test_root_files(self, tmp_path: pathlib.Path):
        """Files in source root get PurePosixPath('.')."""
        source = tmp_path / "source"
        source.mkdir(parents=True)
        f = source / "photo.jpg"
        f.touch()

        groups = _group_by_source_dir([f], source)
        assert len(groups) == 1
        assert groups[0][0] == pathlib.PurePosixPath(".")
        assert groups[0][1] == [f]


class TestIterBatches:
    """Test _iter_batches helper."""

    def test_small_dir_passes_through(self):
        """Dir with 3 files, batch_size=100 → 1 batch."""
        files = [pathlib.Path(f"/src/dir/f{i}.jpg") for i in range(3)]
        groups = [(pathlib.PurePosixPath("dir"), files)]

        batches = list(_iter_batches(groups, batch_size=100))
        assert len(batches) == 1
        assert batches[0][0] == pathlib.PurePosixPath("dir")
        assert batches[0][1] == files

    def test_large_dir_sliced(self):
        """Dir with 250 files, batch_size=100 → 3 batches (100, 100, 50)."""
        files = [pathlib.Path(f"/src/dir/f{i}.jpg") for i in range(250)]
        groups = [(pathlib.PurePosixPath("dir"), files)]

        batches = list(_iter_batches(groups, batch_size=100))
        assert len(batches) == 3
        assert len(batches[0][1]) == 100
        assert len(batches[1][1]) == 100
        assert len(batches[2][1]) == 50
        # All share the same rel_dir
        assert all(d == pathlib.PurePosixPath("dir") for d, _ in batches)

    def test_preserves_dir_order(self):
        """Deepest-first order maintained after slicing."""
        files_deep = [pathlib.Path(f"/src/a/b/c/f{i}.jpg") for i in range(150)]
        files_shallow = [pathlib.Path(f"/src/a/f{i}.jpg") for i in range(50)]
        groups = [
            (pathlib.PurePosixPath("a/b/c"), files_deep),
            (pathlib.PurePosixPath("a"), files_shallow),
        ]

        batches = list(_iter_batches(groups, batch_size=100))
        dirs = [d for d, _ in batches]
        # Deep dir's 2 batches come before shallow dir's 1 batch
        assert dirs == [
            pathlib.PurePosixPath("a/b/c"),
            pathlib.PurePosixPath("a/b/c"),
            pathlib.PurePosixPath("a"),
        ]


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


class TestBatchImport:
    """Test per-directory batch import processing."""

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

    def test_batch_import_processes_per_directory(self, tmp_path: pathlib.Path):
        """Files from 2 dirs are each imported independently."""
        source = tmp_path / "source"
        dir_a = source / "vacation"
        dir_b = source / "work"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        (dir_a / "photo1.jpg").write_bytes(b"\xff\xd8\xff\xd9vacation1")
        (dir_b / "photo2.jpg").write_bytes(b"\xff\xd8\xff\xd9workphoto")

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                dir_a / "photo1.jpg": Metadata(
                    source_path=dir_a / "photo1.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
                dir_b / "photo2.jpg": Metadata(
                    source_path=dir_b / "photo2.jpg",
                    date_taken=datetime.datetime(2024, 6, 20),
                ),
            }
            run_import(args)

        # Both files should be imported
        found_files = [
            f for dirpath, _, files in os.walk(tmp_path / "photos")
            for f in files if not f.endswith(".db")
        ]
        assert len(found_files) == 2

    def test_error_in_one_dir_continues_others(self, tmp_path: pathlib.Path, caplog):
        """If one directory batch fails, the other directory still gets imported."""
        source = tmp_path / "source"
        dir_a = source / "aaa"
        dir_b = source / "bbb"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        (dir_a / "bad.jpg").write_bytes(b"\xff\xd8\xff\xd9bad")
        (dir_b / "good.jpg").write_bytes(b"\xff\xd8\xff\xd9good")

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                dir_a / "bad.jpg": Metadata(
                    source_path=dir_a / "bad.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
                dir_b / "good.jpg": Metadata(
                    source_path=dir_b / "good.jpg",
                    date_taken=datetime.datetime(2024, 6, 20),
                ),
            }
            # Make hash_file fail for files in dir_a
            original_hash = __import__("undisorder.hasher", fromlist=["hash_file"]).hash_file
            def failing_hash(path):
                if "aaa" in str(path):
                    raise OSError("disk error")
                return original_hash(path)
            with patch("undisorder.importer.hash_file", side_effect=failing_hash):
                with caplog.at_level(logging.INFO, logger="undisorder"):
                    run_import(args)

        # Error should be logged
        assert "error" in caplog.text.lower()
        # good.jpg from dir_b should still be imported
        found_files = [
            f for dirpath, _, files in os.walk(tmp_path / "photos")
            for f in files if not f.endswith(".db")
        ]
        assert len(found_files) == 1
        assert "good.jpg" in found_files[0]

    def test_cross_dir_dedup_via_hashdb(self, tmp_path: pathlib.Path):
        """Same hash in 2 dirs — only first is imported (second caught by hashdb)."""
        source = tmp_path / "source"
        dir_a = source / "aaa"
        dir_b = source / "bbb"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        content = b"\xff\xd8\xff\xd9same content"
        (dir_a / "photo.jpg").write_bytes(content)
        (dir_b / "photo.jpg").write_bytes(content)

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                dir_a / "photo.jpg": Metadata(
                    source_path=dir_a / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
                dir_b / "photo.jpg": Metadata(
                    source_path=dir_b / "photo.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
            }
            run_import(args)

        # Only one file should be imported (second is a hash duplicate)
        found_files = [
            f for dirpath, _, files in os.walk(tmp_path / "photos")
            for f in files if not f.endswith(".db")
        ]
        assert len(found_files) == 1

    def test_dry_run_batch_shows_per_dir_output(self, tmp_path: pathlib.Path, caplog):
        """Dry run logs grouped by source dir."""
        source = tmp_path / "source"
        dir_a = source / "vacation"
        dir_b = source / "work"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        (dir_a / "photo1.jpg").write_bytes(b"\xff\xd8\xff\xd9vacation1")
        (dir_b / "photo2.jpg").write_bytes(b"\xff\xd8\xff\xd9workphoto")

        args = self._make_args(tmp_path, dry_run=True)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                dir_a / "photo1.jpg": Metadata(
                    source_path=dir_a / "photo1.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
                dir_b / "photo2.jpg": Metadata(
                    source_path=dir_b / "photo2.jpg",
                    date_taken=datetime.datetime(2024, 6, 20),
                ),
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "DRY RUN" in caplog.text
        assert "photo1.jpg" in caplog.text
        assert "photo2.jpg" in caplog.text


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

    def test_identify_calls_per_batch(self, tmp_path: pathlib.Path, caplog):
        """With --identify, AcoustID is called per file inside batch processing."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00identifiable")

        args = self._make_args(tmp_path, identify=True, acoustid_key="test-key")

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist=None,
            album=None,
            title=None,
        )
        identified_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist="Identified Artist",
            album="Identified Album",
            title="Identified Title",
            track_number=1,
        )
        with (
            patch("undisorder.importer.extract_audio_batch", return_value={
                source / "song.mp3": audio_meta,
            }),
            patch("undisorder.importer.identify_audio", return_value=identified_meta) as mock_identify,
        ):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        # identify_audio should have been called with db and file_hash
        mock_identify.assert_called_once()
        call_kwargs = mock_identify.call_args
        assert call_kwargs.kwargs.get("api_key") == "test-key"
        assert call_kwargs.kwargs.get("file_hash") is not None
        assert call_kwargs.kwargs.get("db") is not None

    def test_identify_uses_cache(self, tmp_path: pathlib.Path, caplog):
        """With --identify and a cached entry, no API calls are made."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00cached audio")

        args = self._make_args(tmp_path, identify=True, acoustid_key="test-key")

        # Pre-populate cache
        from undisorder.hashdb import HashDB
        from undisorder.hasher import hash_file
        aud_db = HashDB(tmp_path / "musik")
        h = hash_file(source / "song.mp3")
        aud_db.store_acoustid_cache(
            file_hash=h,
            fingerprint="FP...",
            duration=180.0,
            recording_id="rec-cached",
            metadata={"artist": "Cached Artist", "album": "Cached Album", "title": "Cached Title"},
        )
        aud_db.close()

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist=None,
            album=None,
            title=None,
        )
        with (
            patch("undisorder.importer.extract_audio_batch", return_value={
                source / "song.mp3": audio_meta,
            }),
            patch("undisorder.importer.identify_audio", wraps=__import__("undisorder.musicbrainz", fromlist=["identify_audio"]).identify_audio),
            patch("undisorder.musicbrainz.fingerprint_audio") as mock_fp,
        ):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        # fingerprint should NOT have been called (cache hit)
        mock_fp.assert_not_called()
        assert "cached" in caplog.text.lower()


class TestProgressLogging:
    """Test progress logging in batch loops."""

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

    def test_audio_progress_logging(self, tmp_path, caplog):
        """Audio batch loop logs 'Processing audio 1/N: dir/ (M file(s))'."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00audio1xx")

        args = self._make_args(tmp_path)

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist="Artist", album="Album", title="Song", track_number=1,
        )
        with patch("undisorder.importer.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "Processing audio 1/1" in caplog.text
        assert "(1 file)" in caplog.text

    def test_audio_progress_multiple_batches(self, tmp_path, caplog):
        """Multiple audio batches log incrementing progress."""
        source = tmp_path / "source"
        dir_a = source / "aaa"
        dir_b = source / "bbb"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)
        (dir_a / "s1.mp3").write_bytes(b"\xff\xfb\x90\x00audio1xx")
        (dir_b / "s2.mp3").write_bytes(b"\xff\xfb\x90\x00audio2xx")

        args = self._make_args(tmp_path)

        audio_meta1 = AudioMetadata(
            source_path=dir_a / "s1.mp3",
            artist="Artist", album="Album1", title="Song1", track_number=1,
        )
        audio_meta2 = AudioMetadata(
            source_path=dir_b / "s2.mp3",
            artist="Artist", album="Album2", title="Song2", track_number=1,
        )
        with patch("undisorder.importer.extract_audio_batch", return_value={
            dir_a / "s1.mp3": audio_meta1,
            dir_b / "s2.mp3": audio_meta2,
        }):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "Processing audio 1/2" in caplog.text
        assert "Processing audio 2/2" in caplog.text

    def test_photo_video_progress_logging(self, tmp_path, caplog):
        """Photo/video batch loop logs 'Processing photo/video 1/N'."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")

        args = self._make_args(tmp_path)

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

        assert "Processing photo/video 1/1" in caplog.text
        assert "(1 file)" in caplog.text

    def test_acoustid_per_file_logging(self, tmp_path, caplog):
        """Per-file AcoustID logs 'Identifying song.mp3 via AcoustID ...'."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00identifiable")

        args = self._make_args(tmp_path, identify=True, acoustid_key="test-key")

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist=None,
        )
        with (
            patch("undisorder.importer.extract_audio_batch", return_value={
                source / "song.mp3": audio_meta,
            }),
            patch("undisorder.importer.identify_audio", return_value=audio_meta),
        ):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "Identifying song.mp3 via AcoustID" in caplog.text


class TestDryRunGrouped:
    """Test that dry-run output is grouped by target directory."""

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

    def test_dry_run_groups_by_target_directory(self, tmp_path, caplog):
        """3 files same month → grouped as '(3 files)' in output."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        for name in ["a.jpg", "b.jpg", "c.jpg"]:
            (source / name).write_bytes(b"\xff\xd8\xff\xd9" + name.encode())

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / name: Metadata(
                    source_path=source / name,
                    date_taken=datetime.datetime(2024, 3, 15),
                )
                for name in ["a.jpg", "b.jpg", "c.jpg"]
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "(3 files)" in caplog.text
        assert "a.jpg" in caplog.text
        assert "b.jpg" in caplog.text
        assert "c.jpg" in caplog.text

    def test_dry_run_multiple_groups(self, tmp_path, caplog):
        """2 different months → two separate groups."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "march.jpg").write_bytes(b"\xff\xd8\xff\xd9march")
        (source / "june.jpg").write_bytes(b"\xff\xd8\xff\xd9junexx")

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "march.jpg": Metadata(
                    source_path=source / "march.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
                source / "june.jpg": Metadata(
                    source_path=source / "june.jpg",
                    date_taken=datetime.datetime(2024, 6, 20),
                ),
            }
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "2024-03" in caplog.text
        assert "2024-06" in caplog.text

    def test_audio_dry_run_grouped(self, tmp_path, caplog):
        """2 songs same artist/album → grouped."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "song1.mp3").write_bytes(b"\xff\xfb\x90\x00audio1xx")
        (source / "song2.mp3").write_bytes(b"\xff\xfb\x90\x00audio2xx")

        args = self._make_args(tmp_path)

        audio_meta1 = AudioMetadata(
            source_path=source / "song1.mp3",
            artist="Artist", album="Album", title="Song1", track_number=1,
        )
        audio_meta2 = AudioMetadata(
            source_path=source / "song2.mp3",
            artist="Artist", album="Album", title="Song2", track_number=2,
        )
        with patch("undisorder.importer.extract_audio_batch", return_value={
            source / "song1.mp3": audio_meta1,
            source / "song2.mp3": audio_meta2,
        }):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "(2 files)" in caplog.text
        assert "Artist" in caplog.text

    def test_dry_run_single_file_singular(self, tmp_path, caplog):
        """1 file → '(1 file)' (singular)."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9single")

        args = self._make_args(tmp_path)

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

        assert "(1 file)" in caplog.text


class TestInteractiveBatch:
    """Test batch interactive confirmation grouped by dirname."""

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
        args.interactive = True
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

    def test_interactive_groups_by_dirname(self, tmp_path):
        """2 files same dirname, Enter → both imported."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9aaa")
        (source / "b.jpg").write_bytes(b"\xff\xd8\xff\xd9bbb")

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
                    date_taken=datetime.datetime(2024, 3, 20),
                ),
            }
            with patch("builtins.input", return_value=""):
                run_import(args)

        found_files = [
            f for dirpath, _, files in os.walk(tmp_path / "photos")
            for f in files if not f.endswith(".db")
        ]
        assert len(found_files) == 2

    def test_interactive_rename_group(self, tmp_path):
        """User types new name → all files in group use it."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9aaa")
        (source / "b.jpg").write_bytes(b"\xff\xd8\xff\xd9bbb")

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
                    date_taken=datetime.datetime(2024, 3, 20),
                ),
            }
            with patch("builtins.input", return_value="MyTrip"):
                run_import(args)

        # Both files should be under MyTrip/
        found_files = []
        for dirpath, _, files in os.walk(tmp_path / "photos"):
            for f in files:
                if not f.endswith(".db"):
                    found_files.append(os.path.join(dirpath, f))
        assert len(found_files) == 2
        assert all("MyTrip" in f for f in found_files)

    def test_interactive_skip_group(self, tmp_path):
        """User types 's' → nothing imported."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9aaa")

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "a.jpg": Metadata(
                    source_path=source / "a.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
            }
            with patch("builtins.input", return_value="s"):
                run_import(args)

        found_files = [
            f for dirpath, _, files in os.walk(tmp_path / "photos")
            for f in files if not f.endswith(".db")
        ]
        assert len(found_files) == 0

    def test_interactive_multiple_groups(self, tmp_path):
        """2 groups, different decisions: accept one, skip another."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "march.jpg").write_bytes(b"\xff\xd8\xff\xd9march")
        (source / "june.jpg").write_bytes(b"\xff\xd8\xff\xd9junexx")

        args = self._make_args(tmp_path)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                source / "march.jpg": Metadata(
                    source_path=source / "march.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
                source / "june.jpg": Metadata(
                    source_path=source / "june.jpg",
                    date_taken=datetime.datetime(2024, 6, 20),
                ),
            }
            # Accept first group, skip second
            with patch("builtins.input", side_effect=["", "s"]):
                run_import(args)

        found_files = [
            f for dirpath, _, files in os.walk(tmp_path / "photos")
            for f in files if not f.endswith(".db")
        ]
        assert len(found_files) == 1

    def test_interactive_prompt_shows_file_count(self, tmp_path, caplog):
        """Prompt contains file count."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9aaa")
        (source / "b.jpg").write_bytes(b"\xff\xd8\xff\xd9bbb")

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
                    date_taken=datetime.datetime(2024, 3, 20),
                ),
            }
            with patch("builtins.input", return_value="") as mock_input:
                run_import(args)

            # The prompt should mention the file count
            prompt = mock_input.call_args[0][0]
            assert "2 files" in prompt


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


class TestImportEdgeCases:
    """Test edge cases and less common import paths."""

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

    def test_empty_source_no_media(self, tmp_path, caplog):
        """Empty source directory — no media files found."""
        args = self._make_args(tmp_path)
        with caplog.at_level(logging.INFO, logger="undisorder"):
            run_import(args)
        assert "No media files found" in caplog.text

    def test_audio_only_no_photos(self, tmp_path, caplog):
        """Source with only audio — photo/video import is skipped."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "song.mp3").write_bytes(b"\xff\xfb\x90\x00only audio here")

        args = self._make_args(tmp_path)

        audio_meta = AudioMetadata(
            source_path=source / "song.mp3",
            artist="Artist", album="Album", title="Song", track_number=1,
        )
        with patch("undisorder.importer.extract_audio_batch", return_value={
            source / "song.mp3": audio_meta,
        }):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "audio" in caplog.text.lower()
        # No photo/video import messages
        assert "photo/video" not in caplog.text.lower()

    def test_photo_update_move_mode(self, tmp_path):
        """Update with --move removes source and overwrites target."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        photo = source / "photo.jpg"
        photo.write_bytes(b"\xff\xd8\xff\xd9original")

        args = self._make_args(tmp_path)

        # First import (copy)
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            run_import(args)

        from undisorder.hashdb import HashDB
        img_db = HashDB(tmp_path / "photos")
        imp = img_db.get_import(str(photo))
        assert imp is not None
        old_target = tmp_path / "photos" / imp["file_path"]
        assert old_target.exists()
        img_db.close()

        # Make source newer with new content
        time.sleep(0.05)
        photo.write_bytes(b"\xff\xd8\xff\xd9updated content")

        # Second import with --update --move
        args2 = self._make_args(tmp_path, update=True, move=True)
        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                photo: Metadata(source_path=photo, date_taken=datetime.datetime(2024, 3, 15))
            }
            run_import(args2)

        # Source should be gone (move mode)
        assert not photo.exists()
        # Target should have updated content
        assert old_target.read_bytes() == b"\xff\xd8\xff\xd9updated content"

    def test_audio_update_when_source_newer(self, tmp_path, caplog):
        """Audio with --update, source newer than target triggers re-import."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        song = source / "song.mp3"
        song.write_bytes(b"\xff\xfb\x90\x00original audio")

        args = self._make_args(tmp_path)

        audio_meta = AudioMetadata(
            source_path=song, artist="Artist", album="Album",
            title="Song", track_number=1,
        )

        # First import
        with patch("undisorder.importer.extract_audio_batch", return_value={song: audio_meta}):
            run_import(args)

        from undisorder.hashdb import HashDB
        aud_db = HashDB(tmp_path / "musik")
        imp = aud_db.get_import(str(song))
        assert imp is not None
        old_target = tmp_path / "musik" / imp["file_path"]
        assert old_target.exists()
        old_content = old_target.read_bytes()
        aud_db.close()

        # Make source newer
        time.sleep(0.05)
        song.write_bytes(b"\xff\xfb\x90\x00updated audio after tagging")

        # Second import with --update
        args2 = self._make_args(tmp_path, update=True)
        with patch("undisorder.importer.extract_audio_batch", return_value={song: audio_meta}):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args2)

        assert old_target.read_bytes() != old_content
        assert "updated" in caplog.text.lower() or "import" in caplog.text.lower()

    def test_select_keyboard_interrupt(self, tmp_path, caplog):
        """KeyboardInterrupt during interactive select aborts gracefully."""
        source = tmp_path / "source"
        source.mkdir(exist_ok=True)
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")

        args = self._make_args(tmp_path, select=True)

        with patch("undisorder.importer.interactive_select", side_effect=KeyboardInterrupt):
            with caplog.at_level(logging.INFO, logger="undisorder"):
                run_import(args)

        assert "Aborted" in caplog.text

    def test_dry_run_does_not_create_target_dirs(self, tmp_path):
        """Dry run should not create target directories."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "photo.jpg").write_bytes(b"\xff\xd8\xff\xd9image")

        target_img = tmp_path / "new_photos"
        target_vid = tmp_path / "new_videos"
        target_aud = tmp_path / "new_musik"

        args = MagicMock()
        args.source = source
        args.images_target = target_img
        args.video_target = target_vid
        args.audio_target = target_aud
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
            run_import(args)

        assert not target_img.exists()
        assert not target_vid.exists()
        assert not target_aud.exists()


class TestFailureLogging:
    """Test structured JSON failure logging."""

    def test_failure_logged_to_jsonl(self, tmp_path, monkeypatch):
        """A batch failure writes a valid JSONL entry with expected fields."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setattr("undisorder.importer._config_dir", lambda: config_dir)

        rel_dir = pathlib.PurePosixPath("vacation")
        batch = [pathlib.Path("/src/vacation/photo1.jpg")]
        try:
            raise OSError("disk read error")
        except OSError as exc:
            _log_failure(rel_dir, "photo_video", batch, exc)

        log_path = config_dir / "import_failures.jsonl"
        assert log_path.exists()

        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["source_dir"] == "vacation"
        assert entry["media_type"] == "photo_video"
        assert entry["files"] == ["/src/vacation/photo1.jpg"]
        assert entry["error_type"] == "OSError"
        assert entry["error_message"] == "disk read error"
        assert "timestamp" in entry

    def test_failure_log_appends(self, tmp_path, monkeypatch):
        """Multiple failures append separate entries to the same file."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setattr("undisorder.importer._config_dir", lambda: config_dir)

        for i in range(2):
            try:
                raise ValueError(f"error {i}")
            except ValueError as exc:
                _log_failure(
                    pathlib.PurePosixPath(f"dir{i}"), "audio",
                    [pathlib.Path(f"/src/dir{i}/file.mp3")], exc,
                )

        log_path = config_dir / "import_failures.jsonl"
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) == 2

        entries = [json.loads(line) for line in lines]
        assert entries[0]["error_message"] == "error 0"
        assert entries[1]["error_message"] == "error 1"

    def test_failure_contains_traceback(self, tmp_path, monkeypatch):
        """The traceback field is non-empty and contains the exception message."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setattr("undisorder.importer._config_dir", lambda: config_dir)

        try:
            raise RuntimeError("something broke")
        except RuntimeError as exc:
            _log_failure(
                pathlib.PurePosixPath("."), "photo_video",
                [pathlib.Path("/src/photo.jpg")], exc,
            )

        log_path = config_dir / "import_failures.jsonl"
        entry = json.loads(log_path.read_text().strip())
        assert entry["traceback"]
        assert "something broke" in entry["traceback"]

    def test_failure_logged_during_import(self, tmp_path, monkeypatch, caplog):
        """End-to-end: a batch error during import writes to the JSONL log."""
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        monkeypatch.setattr("undisorder.importer._config_dir", lambda: config_dir)

        source = tmp_path / "source"
        dir_a = source / "aaa"
        dir_a.mkdir(parents=True)
        (dir_a / "bad.jpg").write_bytes(b"\xff\xd8\xff\xd9bad")

        args = MagicMock()
        args.source = source
        args.images_target = tmp_path / "photos"
        args.video_target = tmp_path / "videos"
        args.audio_target = tmp_path / "musik"
        args.dry_run = False
        args.move = False
        args.geocoding = "off"
        args.interactive = False
        args.exclude = []
        args.exclude_dir = []
        args.select = False
        args.update = False
        (tmp_path / "photos").mkdir(exist_ok=True)
        (tmp_path / "videos").mkdir(exist_ok=True)
        (tmp_path / "musik").mkdir(exist_ok=True)

        with patch("undisorder.importer.extract_batch") as mock_extract:
            from undisorder.metadata import Metadata

            import datetime
            mock_extract.return_value = {
                dir_a / "bad.jpg": Metadata(
                    source_path=dir_a / "bad.jpg",
                    date_taken=datetime.datetime(2024, 3, 15),
                ),
            }
            # Make hash_file raise for all files
            with patch("undisorder.importer.hash_file", side_effect=OSError("disk error")):
                with caplog.at_level(logging.WARNING, logger="undisorder"):
                    run_import(args)

        # Failure log should exist with the error
        log_path = config_dir / "import_failures.jsonl"
        assert log_path.exists()
        entry = json.loads(log_path.read_text().strip().splitlines()[0])
        assert entry["error_type"] == "OSError"
        assert entry["media_type"] == "photo_video"

        # Summary warning should mention the log path
        assert "batch(es) failed" in caplog.text
        assert str(log_path) in caplog.text
