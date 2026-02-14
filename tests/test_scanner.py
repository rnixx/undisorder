"""Tests for undisorder.scanner — file discovery and classification."""

import pathlib

from undisorder.scanner import AUDIO_EXTENSIONS, FileType, classify, scan


class TestClassify:
    """Test file type classification by extension."""

    def test_jpg_is_photo(self):
        assert classify(pathlib.Path("img.jpg")) is FileType.PHOTO

    def test_jpeg_is_photo(self):
        assert classify(pathlib.Path("img.jpeg")) is FileType.PHOTO

    def test_png_is_photo(self):
        assert classify(pathlib.Path("img.png")) is FileType.PHOTO

    def test_tiff_is_photo(self):
        assert classify(pathlib.Path("img.tiff")) is FileType.PHOTO

    def test_heic_is_photo(self):
        assert classify(pathlib.Path("img.heic")) is FileType.PHOTO

    def test_cr2_raw_is_photo(self):
        assert classify(pathlib.Path("img.cr2")) is FileType.PHOTO

    def test_nef_raw_is_photo(self):
        assert classify(pathlib.Path("img.nef")) is FileType.PHOTO

    def test_arw_raw_is_photo(self):
        assert classify(pathlib.Path("img.arw")) is FileType.PHOTO

    def test_dng_raw_is_photo(self):
        assert classify(pathlib.Path("img.dng")) is FileType.PHOTO

    def test_mp4_is_video(self):
        assert classify(pathlib.Path("clip.mp4")) is FileType.VIDEO

    def test_mov_is_video(self):
        assert classify(pathlib.Path("clip.mov")) is FileType.VIDEO

    def test_avi_is_video(self):
        assert classify(pathlib.Path("clip.avi")) is FileType.VIDEO

    def test_mkv_is_video(self):
        assert classify(pathlib.Path("clip.mkv")) is FileType.VIDEO

    def test_mts_is_video(self):
        assert classify(pathlib.Path("clip.mts")) is FileType.VIDEO

    def test_txt_is_unknown(self):
        assert classify(pathlib.Path("notes.txt")) is FileType.UNKNOWN

    def test_no_extension_is_unknown(self):
        assert classify(pathlib.Path("README")) is FileType.UNKNOWN

    def test_mp3_is_audio(self):
        assert classify(pathlib.Path("song.mp3")) is FileType.AUDIO

    def test_flac_is_audio(self):
        assert classify(pathlib.Path("track.flac")) is FileType.AUDIO

    def test_ogg_is_audio(self):
        assert classify(pathlib.Path("track.ogg")) is FileType.AUDIO

    def test_opus_is_audio(self):
        assert classify(pathlib.Path("track.opus")) is FileType.AUDIO

    def test_m4a_is_audio(self):
        assert classify(pathlib.Path("song.m4a")) is FileType.AUDIO

    def test_aac_is_audio(self):
        assert classify(pathlib.Path("song.aac")) is FileType.AUDIO

    def test_wma_is_audio(self):
        assert classify(pathlib.Path("song.wma")) is FileType.AUDIO

    def test_wav_is_audio(self):
        assert classify(pathlib.Path("sound.wav")) is FileType.AUDIO

    def test_aiff_is_audio(self):
        assert classify(pathlib.Path("track.aiff")) is FileType.AUDIO

    def test_ape_is_audio(self):
        assert classify(pathlib.Path("track.ape")) is FileType.AUDIO

    def test_mpc_is_audio(self):
        assert classify(pathlib.Path("track.mpc")) is FileType.AUDIO

    def test_wv_is_audio(self):
        assert classify(pathlib.Path("track.wv")) is FileType.AUDIO

    def test_tta_is_audio(self):
        assert classify(pathlib.Path("track.tta")) is FileType.AUDIO

    def test_audio_case_insensitive(self):
        assert classify(pathlib.Path("SONG.MP3")) is FileType.AUDIO
        assert classify(pathlib.Path("Track.FLAC")) is FileType.AUDIO

    def test_all_audio_extensions_covered(self):
        """Every extension in AUDIO_EXTENSIONS should classify as AUDIO."""
        for ext in AUDIO_EXTENSIONS:
            assert classify(pathlib.Path(f"file{ext}")) is FileType.AUDIO

    def test_case_insensitive(self):
        assert classify(pathlib.Path("IMG.JPG")) is FileType.PHOTO
        assert classify(pathlib.Path("Video.MP4")) is FileType.VIDEO


class TestScan:
    """Test recursive file discovery."""

    def test_empty_directory(self, tmp_source: pathlib.Path):
        result = scan(tmp_source)
        assert result.photos == []
        assert result.videos == []
        assert result.unknown == []

    def test_finds_photo(self, sample_jpg: pathlib.Path, tmp_source: pathlib.Path):
        result = scan(tmp_source)
        assert sample_jpg in result.photos
        assert result.videos == []

    def test_finds_video(self, sample_mp4: pathlib.Path, tmp_source: pathlib.Path):
        result = scan(tmp_source)
        assert sample_mp4 in result.videos
        assert result.photos == []

    def test_ignores_unknown(
        self, sample_txt: pathlib.Path, tmp_source: pathlib.Path
    ):
        result = scan(tmp_source)
        assert result.photos == []
        assert result.videos == []
        assert sample_txt in result.unknown

    def test_finds_files_in_subdirectories(self, tmp_source: pathlib.Path):
        sub = tmp_source / "sub" / "deep"
        sub.mkdir(parents=True)
        img = sub / "deep_photo.jpg"
        img.write_bytes(b"\xff\xd8\xff\xd9")
        result = scan(tmp_source)
        assert img in result.photos

    def test_mixed_files(self, tmp_source: pathlib.Path):
        (tmp_source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (tmp_source / "b.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
        (tmp_source / "c.txt").write_text("nope")
        result = scan(tmp_source)
        assert len(result.photos) == 1
        assert len(result.videos) == 1
        assert len(result.unknown) == 1

    def test_skips_hidden_directories(self, tmp_source: pathlib.Path):
        hidden = tmp_source / ".hidden"
        hidden.mkdir()
        (hidden / "secret.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        result = scan(tmp_source)
        assert result.photos == []

    def test_skips_hidden_files(self, tmp_source: pathlib.Path):
        (tmp_source / ".hidden.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        result = scan(tmp_source)
        assert result.photos == []

    def test_nonexistent_directory_raises(self):
        with __import__("pytest").raises(FileNotFoundError):
            scan(pathlib.Path("/nonexistent/path"))

    def test_finds_audio(self, tmp_source: pathlib.Path):
        mp3 = tmp_source / "song.mp3"
        mp3.write_bytes(b"\xff\xfb\x90\x00")
        result = scan(tmp_source)
        assert mp3 in result.audios
        assert result.photos == []
        assert result.videos == []

    def test_mixed_media_with_audio(self, tmp_source: pathlib.Path):
        (tmp_source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (tmp_source / "b.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
        (tmp_source / "c.mp3").write_bytes(b"\xff\xfb\x90\x00")
        (tmp_source / "d.txt").write_text("nope")
        result = scan(tmp_source)
        assert len(result.photos) == 1
        assert len(result.videos) == 1
        assert len(result.audios) == 1
        assert len(result.unknown) == 1

    def test_total_count_includes_audio(self, tmp_source: pathlib.Path):
        (tmp_source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (tmp_source / "b.mp4").write_bytes(b"\x00")
        (tmp_source / "c.mp3").write_bytes(b"\xff\xfb")
        (tmp_source / "d.txt").write_text("x")
        result = scan(tmp_source)
        assert result.total == 4

    def test_total_count(self, tmp_source: pathlib.Path):
        (tmp_source / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
        (tmp_source / "b.mp4").write_bytes(b"\x00")
        (tmp_source / "c.txt").write_text("x")
        result = scan(tmp_source)
        assert result.total == 3
