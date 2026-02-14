"""Tests for undisorder.config — configuration loading, merging, and interactive creation."""

from __future__ import annotations

from undisorder.config import CONFIG_FILENAME
from undisorder.config import create_config_interactive
from undisorder.config import load_config
from undisorder.config import merge_config_into_args

import argparse
import pathlib


class TestLoadConfig:
    """Test loading config.toml."""

    def test_returns_empty_dict_when_no_file(self, tmp_path):
        assert load_config(tmp_path) == {}

    def test_loads_valid_toml(self, tmp_path):
        (tmp_path / CONFIG_FILENAME).write_text(
            'images_target = "~/Photos"\ndry_run = true\n'
        )
        cfg = load_config(tmp_path)
        assert cfg["images_target"] == "~/Photos"
        assert cfg["dry_run"] is True

    def test_all_supported_keys(self, tmp_path):
        toml = "\n".join([
            'images_target = "/img"',
            'video_target = "/vid"',
            'audio_target = "/aud"',
            'geocoding = "offline"',
            "dry_run = true",
            "move = true",
            "update = true",
            "interactive = true",
            "identify = true",
            "select = true",
            'exclude = ["*.wav", "*.aiff"]',
            'exclude_dir = ["DAW*"]',
            'acoustid_key = "my-key"',
        ])
        (tmp_path / CONFIG_FILENAME).write_text(toml)
        cfg = load_config(tmp_path)
        assert len(cfg) == 13

    def test_ignores_unknown_keys(self, tmp_path):
        (tmp_path / CONFIG_FILENAME).write_text('unknown_key = "value"\n')
        cfg = load_config(tmp_path)
        assert "unknown_key" in cfg  # loaded without error

    def test_returns_empty_dict_on_parse_error(self, tmp_path):
        (tmp_path / CONFIG_FILENAME).write_text("this is not valid toml [[[")
        assert load_config(tmp_path) == {}

    def test_list_values_for_exclude(self, tmp_path):
        (tmp_path / CONFIG_FILENAME).write_text('exclude = ["*.wav", "*.aiff"]\n')
        cfg = load_config(tmp_path)
        assert cfg["exclude"] == ["*.wav", "*.aiff"]

    def test_boolean_values(self, tmp_path):
        (tmp_path / CONFIG_FILENAME).write_text("dry_run = true\nmove = false\n")
        cfg = load_config(tmp_path)
        assert cfg["dry_run"] is True
        assert cfg["move"] is False

    def test_uses_default_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        config_dir = tmp_path / "undisorder"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / CONFIG_FILENAME).write_text('dry_run = true\n')
        cfg = load_config()
        assert cfg["dry_run"] is True


class TestMergeConfigIntoArgs:
    """Test merging config into argparse Namespace."""

    def _make_args(self, **kwargs):
        defaults = dict(
            images_target=None, video_target=None, audio_target=None,
            dry_run=None, move=None, geocoding=None,
            interactive=None, identify=None, select=None, update=None,
            exclude=None, exclude_dir=None, acoustid_key=None,
        )
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_config_sets_unset_path_args(self):
        args = self._make_args()
        merge_config_into_args(args, {"images_target": "~/Photos"})
        assert args.images_target == pathlib.Path("~/Photos").expanduser()

    def test_cli_arg_overrides_config(self):
        args = self._make_args(images_target=pathlib.Path("/cli/path"))
        merge_config_into_args(args, {"images_target": "~/Photos"})
        assert args.images_target == pathlib.Path("/cli/path")

    def test_boolean_from_config(self):
        args = self._make_args()
        merge_config_into_args(args, {"dry_run": True})
        assert args.dry_run is True

    def test_cli_boolean_overrides_config(self):
        args = self._make_args(dry_run=True)
        merge_config_into_args(args, {"dry_run": False})
        assert args.dry_run is True

    def test_defaults_when_neither_cli_nor_config(self):
        args = self._make_args()
        merge_config_into_args(args, {})
        assert args.images_target == pathlib.Path("~/Bilder/Fotos").expanduser()
        assert args.video_target == pathlib.Path("~/Videos").expanduser()
        assert args.audio_target == pathlib.Path("~/Musik").expanduser()
        assert args.dry_run is False
        assert args.move is False
        assert args.geocoding == "off"
        assert args.interactive is False
        assert args.identify is False
        assert args.select is False
        assert args.update is False
        assert args.exclude == []
        assert args.exclude_dir == []
        assert args.acoustid_key is None

    def test_exclude_lists_merged(self):
        args = self._make_args(exclude=["*.wav"])
        merge_config_into_args(args, {"exclude": ["*.aiff"]})
        assert "*.wav" in args.exclude
        assert "*.aiff" in args.exclude

    def test_exclude_empty_cli_uses_config(self):
        args = self._make_args()
        merge_config_into_args(args, {"exclude": ["*.aiff", "*.wav"]})
        assert args.exclude == ["*.aiff", "*.wav"]

    def test_geocoding_invalid_in_config_uses_default(self):
        args = self._make_args()
        merge_config_into_args(args, {"geocoding": "invalid"})
        assert args.geocoding == "off"


class TestCreateConfigInteractive:
    """Test interactive config creation."""

    def test_creates_config_file(self, tmp_path):
        # Accept all defaults by pressing Enter
        inputs = iter([""] * 20)
        create_config_interactive(
            config_dir=tmp_path, input_fn=lambda _: next(inputs), print_fn=lambda *a: None,
        )
        assert (tmp_path / CONFIG_FILENAME).exists()

    def test_custom_values_written(self, tmp_path):
        responses = {
            "images_target": "/my/photos",
            "video_target": "/my/videos",
            "audio_target": "/my/music",
            "geocoding": "offline",
            "acoustid_key": "my-api-key",
        }

        def fake_input(prompt):
            for key, val in responses.items():
                if key.split("_")[0] in prompt.lower():
                    return val
            return ""

        create_config_interactive(
            config_dir=tmp_path, input_fn=fake_input, print_fn=lambda *a: None,
        )
        cfg = load_config(tmp_path)
        assert cfg["images_target"] == "/my/photos"
        assert cfg["video_target"] == "/my/videos"
        assert cfg["audio_target"] == "/my/music"
        assert cfg["geocoding"] == "offline"
        assert cfg["acoustid_key"] == "my-api-key"

    def test_skip_empty_input_uses_default(self, tmp_path):
        inputs = iter([""] * 20)
        create_config_interactive(
            config_dir=tmp_path, input_fn=lambda _: next(inputs), print_fn=lambda *a: None,
        )
        cfg = load_config(tmp_path)
        assert cfg["images_target"] == "~/Bilder/Fotos"

    def test_acoustid_key_saved(self, tmp_path):
        def fake_input(prompt):
            if "acoustid" in prompt.lower():
                return "test-key-123"
            return ""

        create_config_interactive(
            config_dir=tmp_path, input_fn=fake_input, print_fn=lambda *a: None,
        )
        cfg = load_config(tmp_path)
        assert cfg["acoustid_key"] == "test-key-123"

    def test_acoustid_key_skip(self, tmp_path):
        inputs = iter([""] * 20)
        create_config_interactive(
            config_dir=tmp_path, input_fn=lambda _: next(inputs), print_fn=lambda *a: None,
        )
        cfg = load_config(tmp_path)
        assert "acoustid_key" not in cfg

    def test_existing_config_loaded_as_defaults(self, tmp_path):
        (tmp_path / CONFIG_FILENAME).write_text(
            'images_target = "/existing/photos"\nacoustid_key = "old-key"\n'
        )
        prompts_seen = []

        def fake_input(prompt):
            prompts_seen.append(prompt)
            return ""

        create_config_interactive(
            config_dir=tmp_path, input_fn=fake_input, print_fn=lambda *a: None,
        )
        # Defaults from existing config should appear in prompts
        matching = [p for p in prompts_seen if "/existing/photos" in p]
        assert len(matching) > 0
        # And the existing values should be preserved when Enter is pressed
        cfg = load_config(tmp_path)
        assert cfg["images_target"] == "/existing/photos"
        assert cfg["acoustid_key"] == "old-key"
