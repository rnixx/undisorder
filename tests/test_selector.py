"""Tests for undisorder.selector — file filtering and interactive selection."""

from __future__ import annotations

from undisorder.scanner import ScanResult
from undisorder.selector import apply_exclude_patterns
from undisorder.selector import DirectoryGroup
from undisorder.selector import filter_scan_result
from undisorder.selector import format_group_summary
from undisorder.selector import format_size
from undisorder.selector import group_by_directory
from undisorder.selector import interactive_select

import pathlib
import pytest


class TestApplyExcludePatterns:
    """Test file/directory exclusion by glob patterns."""

    def test_exclude_by_extension(self, tmp_path: pathlib.Path):
        wav = tmp_path / "song.wav"
        jpg = tmp_path / "photo.jpg"
        wav.write_bytes(b"audio")
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg], audios=[wav])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=["*.wav"], exclude_dir=[],
        )
        assert filtered.audios == []
        assert filtered.photos == [jpg]

    def test_exclude_by_dir_name(self, tmp_path: pathlib.Path):
        daw = tmp_path / "DAW_Project"
        daw.mkdir()
        wav = daw / "sample.wav"
        wav.write_bytes(b"audio")
        jpg = tmp_path / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg], audios=[wav])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=[], exclude_dir=["DAW*"],
        )
        assert filtered.audios == []
        assert filtered.photos == [jpg]

    def test_exclude_nested_dir(self, tmp_path: pathlib.Path):
        nested = tmp_path / "music" / "DAW_Session"
        nested.mkdir(parents=True)
        wav = nested / "track.wav"
        wav.write_bytes(b"audio")

        result = ScanResult(audios=[wav])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=[], exclude_dir=["DAW*"],
        )
        assert filtered.audios == []

    def test_multiple_patterns(self, tmp_path: pathlib.Path):
        wav = tmp_path / "song.wav"
        aiff = tmp_path / "song.aiff"
        mp3 = tmp_path / "song.mp3"
        wav.write_bytes(b"w")
        aiff.write_bytes(b"a")
        mp3.write_bytes(b"m")

        result = ScanResult(audios=[wav, aiff, mp3])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=["*.wav", "*.aiff"], exclude_dir=[],
        )
        assert filtered.audios == [mp3]

    def test_case_insensitive(self, tmp_path: pathlib.Path):
        wav_upper = tmp_path / "song.WAV"
        wav_upper.write_bytes(b"audio")

        result = ScanResult(audios=[wav_upper])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=["*.wav"], exclude_dir=[],
        )
        assert filtered.audios == []

    def test_case_insensitive_dir(self, tmp_path: pathlib.Path):
        daw = tmp_path / "daw_project"
        daw.mkdir()
        wav = daw / "sample.wav"
        wav.write_bytes(b"audio")

        result = ScanResult(audios=[wav])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=[], exclude_dir=["DAW*"],
        )
        assert filtered.audios == []

    def test_no_patterns_is_noop(self, tmp_path: pathlib.Path):
        jpg = tmp_path / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=[], exclude_dir=[],
        )
        assert filtered.photos == [jpg]

    def test_filters_all_lists(self, tmp_path: pathlib.Path):
        daw = tmp_path / "DAW"
        daw.mkdir()
        photo = daw / "cover.jpg"
        video = daw / "clip.mp4"
        audio = daw / "track.mp3"
        unknown = daw / "notes.txt"
        for f in [photo, video, audio, unknown]:
            f.write_bytes(b"data")

        result = ScanResult(
            photos=[photo], videos=[video], audios=[audio], unknown=[unknown],
        )
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=[], exclude_dir=["DAW"],
        )
        assert filtered.photos == []
        assert filtered.videos == []
        assert filtered.audios == []
        assert filtered.unknown == []

    def test_returns_new_scan_result(self, tmp_path: pathlib.Path):
        jpg = tmp_path / "photo.jpg"
        jpg.write_bytes(b"image")
        result = ScanResult(photos=[jpg])
        filtered = apply_exclude_patterns(
            result, tmp_path, exclude_file=[], exclude_dir=[],
        )
        assert filtered is not result


class TestGroupByDirectory:
    """Test grouping files by parent directory."""

    def test_single_dir(self, tmp_path: pathlib.Path):
        sub = tmp_path / "vacation"
        sub.mkdir()
        jpg = sub / "photo.jpg"
        jpg.write_bytes(b"image data here")

        result = ScanResult(photos=[jpg])
        groups = group_by_directory(result, tmp_path)
        assert len(groups) == 1
        assert groups[0].rel_path == pathlib.PurePosixPath("vacation")
        assert groups[0].files == [jpg]
        assert groups[0].photo_count == 1

    def test_multiple_dirs(self, tmp_path: pathlib.Path):
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        f1 = d1 / "photo.jpg"
        f2 = d2 / "video.mp4"
        f1.write_bytes(b"img")
        f2.write_bytes(b"vid")

        result = ScanResult(photos=[f1], videos=[f2])
        groups = group_by_directory(result, tmp_path)
        assert len(groups) == 2
        assert groups[0].rel_path == pathlib.PurePosixPath("a")
        assert groups[1].rel_path == pathlib.PurePosixPath("b")

    def test_nested_dir(self, tmp_path: pathlib.Path):
        nested = tmp_path / "photos" / "vacation"
        nested.mkdir(parents=True)
        jpg = nested / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg])
        groups = group_by_directory(result, tmp_path)
        assert len(groups) == 1
        assert groups[0].rel_path == pathlib.PurePosixPath("photos/vacation")

    def test_root_files(self, tmp_path: pathlib.Path):
        jpg = tmp_path / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg])
        groups = group_by_directory(result, tmp_path)
        assert len(groups) == 1
        assert groups[0].rel_path == pathlib.PurePosixPath(".")

    def test_counts_by_type(self, tmp_path: pathlib.Path):
        sub = tmp_path / "mixed"
        sub.mkdir()
        jpg = sub / "photo.jpg"
        mp4 = sub / "video.mp4"
        mp3 = sub / "song.mp3"
        txt = sub / "notes.txt"
        for f in [jpg, mp4, mp3, txt]:
            f.write_bytes(b"data")

        result = ScanResult(photos=[jpg], videos=[mp4], audios=[mp3], unknown=[txt])
        groups = group_by_directory(result, tmp_path)
        assert len(groups) == 1
        g = groups[0]
        assert g.photo_count == 1
        assert g.video_count == 1
        assert g.audio_count == 1
        assert g.unknown_count == 1

    def test_total_size(self, tmp_path: pathlib.Path):
        sub = tmp_path / "dir"
        sub.mkdir()
        f1 = sub / "a.jpg"
        f2 = sub / "b.jpg"
        f1.write_bytes(b"x" * 100)
        f2.write_bytes(b"y" * 200)

        result = ScanResult(photos=[f1, f2])
        groups = group_by_directory(result, tmp_path)
        assert groups[0].total_size == 300

    def test_sorted_by_path(self, tmp_path: pathlib.Path):
        for name in ["zebra", "alpha", "middle"]:
            d = tmp_path / name
            d.mkdir()
            (d / "photo.jpg").write_bytes(b"data")

        result = ScanResult(photos=[
            tmp_path / "zebra" / "photo.jpg",
            tmp_path / "alpha" / "photo.jpg",
            tmp_path / "middle" / "photo.jpg",
        ])
        groups = group_by_directory(result, tmp_path)
        paths = [g.rel_path for g in groups]
        assert paths == [
            pathlib.PurePosixPath("alpha"),
            pathlib.PurePosixPath("middle"),
            pathlib.PurePosixPath("zebra"),
        ]

    def test_empty(self, tmp_path: pathlib.Path):
        result = ScanResult()
        groups = group_by_directory(result, tmp_path)
        assert groups == []


class TestInteractiveSelect:
    """Test interactive directory selection."""

    def _make_group(self, rel_path: str, *, photo_count=1, total_size=1000) -> DirectoryGroup:
        return DirectoryGroup(
            rel_path=pathlib.PurePosixPath(rel_path),
            files=[pathlib.Path(f"/fake/{rel_path}/photo.jpg")],
            photo_count=photo_count,
            video_count=0,
            audio_count=0,
            unknown_count=0,
            total_size=total_size,
        )

    def test_accept(self):
        groups = [self._make_group("vacation")]
        inputs = iter(["y"])
        output = []
        accepted = interactive_select(
            groups, pathlib.Path("/root"),
            input_fn=lambda _: next(inputs), print_fn=output.append,
        )
        assert pathlib.PurePosixPath("vacation") in accepted

    def test_skip(self):
        groups = [self._make_group("junk")]
        inputs = iter(["n"])
        output = []
        accepted = interactive_select(
            groups, pathlib.Path("/root"),
            input_fn=lambda _: next(inputs), print_fn=output.append,
        )
        assert accepted == set()

    def test_accept_all(self):
        groups = [self._make_group("a"), self._make_group("b"), self._make_group("c")]
        inputs = iter(["a"])
        output = []
        accepted = interactive_select(
            groups, pathlib.Path("/root"),
            input_fn=lambda _: next(inputs), print_fn=output.append,
        )
        assert accepted == {
            pathlib.PurePosixPath("a"),
            pathlib.PurePosixPath("b"),
            pathlib.PurePosixPath("c"),
        }

    def test_quit_raises_keyboard_interrupt(self):
        groups = [self._make_group("a"), self._make_group("b")]
        inputs = iter(["q"])
        output = []
        with pytest.raises(KeyboardInterrupt):
            interactive_select(
                groups, pathlib.Path("/root"),
                input_fn=lambda _: next(inputs), print_fn=output.append,
            )

    def test_list_then_accept(self):
        groups = [self._make_group("vacation")]
        inputs = iter(["l", "y"])
        output = []
        accepted = interactive_select(
            groups, pathlib.Path("/root"),
            input_fn=lambda _: next(inputs), print_fn=output.append,
        )
        assert pathlib.PurePosixPath("vacation") in accepted
        # Should have printed file listing
        assert any("photo.jpg" in line for line in output)

    def test_invalid_input_reprompts(self):
        groups = [self._make_group("vacation")]
        inputs = iter(["x", "z", "y"])
        output = []
        accepted = interactive_select(
            groups, pathlib.Path("/root"),
            input_fn=lambda _: next(inputs), print_fn=output.append,
        )
        assert pathlib.PurePosixPath("vacation") in accepted

    def test_mixed_accept_skip(self):
        groups = [self._make_group("keep"), self._make_group("skip"), self._make_group("also_keep")]
        inputs = iter(["y", "n", "y"])
        output = []
        accepted = interactive_select(
            groups, pathlib.Path("/root"),
            input_fn=lambda _: next(inputs), print_fn=output.append,
        )
        assert accepted == {
            pathlib.PurePosixPath("keep"),
            pathlib.PurePosixPath("also_keep"),
        }


class TestFilterScanResult:
    """Test filtering ScanResult by accepted directories."""

    def test_accepts_matching(self, tmp_path: pathlib.Path):
        sub = tmp_path / "vacation"
        sub.mkdir()
        jpg = sub / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg])
        filtered = filter_scan_result(
            result, tmp_path, {pathlib.PurePosixPath("vacation")},
        )
        assert filtered.photos == [jpg]

    def test_rejects_non_matching(self, tmp_path: pathlib.Path):
        sub = tmp_path / "junk"
        sub.mkdir()
        jpg = sub / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg])
        filtered = filter_scan_result(
            result, tmp_path, {pathlib.PurePosixPath("vacation")},
        )
        assert filtered.photos == []

    def test_root_dir(self, tmp_path: pathlib.Path):
        jpg = tmp_path / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg])
        filtered = filter_scan_result(
            result, tmp_path, {pathlib.PurePosixPath(".")},
        )
        assert filtered.photos == [jpg]

    def test_empty_accepted_gives_empty_result(self, tmp_path: pathlib.Path):
        sub = tmp_path / "dir"
        sub.mkdir()
        jpg = sub / "photo.jpg"
        jpg.write_bytes(b"image")

        result = ScanResult(photos=[jpg])
        filtered = filter_scan_result(result, tmp_path, set())
        assert filtered.photos == []
        assert filtered.total == 0


class TestFormatSize:
    """Test human-readable size formatting."""

    def test_bytes(self):
        assert format_size(500) == "500 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"

    def test_kilobytes_fractional(self):
        assert format_size(340 * 1024) == "340.0 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024) == "1.0 MB"

    def test_megabytes_fractional(self):
        assert format_size(int(1.2 * 1024 * 1024)) == "1.2 MB"

    def test_gigabytes(self):
        assert format_size(1024 ** 3) == "1.0 GB"

    def test_zero(self):
        assert format_size(0) == "0 B"


class TestFormatGroupSummary:
    """Test directory group summary formatting."""

    def test_single_type(self):
        group = DirectoryGroup(
            rel_path=pathlib.PurePosixPath("vacation"),
            files=[],
            photo_count=3,
            video_count=0,
            audio_count=0,
            unknown_count=0,
            total_size=1024 * 1024,
        )
        summary = format_group_summary(group)
        assert "vacation/" in summary
        assert "3 photos" in summary
        assert "1.0 MB" in summary
        assert "video" not in summary

    def test_multiple_types(self):
        group = DirectoryGroup(
            rel_path=pathlib.PurePosixPath("photos/vacation"),
            files=[],
            photo_count=3,
            video_count=2,
            audio_count=0,
            unknown_count=0,
            total_size=int(1.2 * 1024 * 1024),
        )
        summary = format_group_summary(group)
        assert "photos/vacation/" in summary
        assert "3 photos" in summary
        assert "2 videos" in summary
        assert "1.2 MB" in summary

    def test_skips_zero_counts(self):
        group = DirectoryGroup(
            rel_path=pathlib.PurePosixPath("music"),
            files=[],
            photo_count=0,
            video_count=0,
            audio_count=12,
            unknown_count=0,
            total_size=45 * 1024 * 1024,
        )
        summary = format_group_summary(group)
        assert "12 audio" in summary
        assert "photo" not in summary
        assert "video" not in summary
        assert "unknown" not in summary
