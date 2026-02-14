"""Configuration loading, merging, and interactive creation."""

from __future__ import annotations

import logging
import os
import pathlib
import tomllib


logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.toml"

_DEFAULTS: dict[str, object] = {
    "images_target": "~/Bilder/Fotos",
    "video_target": "~/Videos",
    "audio_target": "~/Musik",
    "geocoding": "off",
    "dry_run": False,
    "move": False,
    "update": False,
    "interactive": False,
    "identify": False,
    "select": False,
    "exclude": [],
    "exclude_dir": [],
    "acoustid_key": None,
}

_PATH_KEYS = {"images_target", "video_target", "audio_target"}
_BOOL_KEYS = {"dry_run", "move", "update", "interactive", "identify", "select"}
_LIST_KEYS = {"exclude", "exclude_dir"}
_VALID_GEOCODING = {"off", "offline", "online"}


def _config_dir() -> pathlib.Path:
    """Return the undisorder config directory."""
    base = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    d = base / "undisorder"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config(config_dir: pathlib.Path | None = None) -> dict:
    """Load config.toml and return its contents as a dict.

    Returns {} if no file exists or on parse error.
    """
    if config_dir is None:
        config_dir = _config_dir()
    path = config_dir / CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return {}


def merge_config_into_args(args, config: dict) -> None:
    """Three-layer merge: CLI > config > hardcoded defaults.

    Mutates *args* in place.
    """
    for key in _PATH_KEYS:
        cli_val = getattr(args, key, None)
        if cli_val is not None:
            continue
        cfg_val = config.get(key)
        if cfg_val is not None:
            setattr(args, key, pathlib.Path(cfg_val).expanduser())
        else:
            setattr(args, key, pathlib.Path(str(_DEFAULTS[key])).expanduser())

    for key in _BOOL_KEYS:
        cli_val = getattr(args, key, None)
        if cli_val is not None:
            continue
        cfg_val = config.get(key)
        if cfg_val is not None:
            setattr(args, key, bool(cfg_val))
        else:
            setattr(args, key, _DEFAULTS[key])

    # Geocoding — validate
    if getattr(args, "geocoding", None) is None:
        cfg_val = config.get("geocoding")
        if cfg_val in _VALID_GEOCODING:
            args.geocoding = cfg_val
        else:
            args.geocoding = _DEFAULTS["geocoding"]

    # List fields — merge CLI + config
    for key in _LIST_KEYS:
        cli_val = getattr(args, key, None) or []
        cfg_val = config.get(key) or []
        setattr(args, key, cli_val + [v for v in cfg_val if v not in cli_val])

    # acoustid_key — CLI > config
    if getattr(args, "acoustid_key", None) is None:
        args.acoustid_key = config.get("acoustid_key")


def create_config_interactive(
    config_dir: pathlib.Path | None = None,
    input_fn=input,
    print_fn=print,
) -> pathlib.Path:
    """Interactively create or update config.toml.

    Returns the path to the written config file.
    """
    if config_dir is None:
        config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    existing = load_config(config_dir)

    settings: list[tuple[str, str, str]] = [
        ("images_target", "Images target directory", str(_DEFAULTS["images_target"])),
        ("video_target", "Video target directory", str(_DEFAULTS["video_target"])),
        ("audio_target", "Audio target directory", str(_DEFAULTS["audio_target"])),
        ("geocoding", "Geocoding mode (off/offline/online)", str(_DEFAULTS["geocoding"])),
        ("dry_run", "Dry run (true/false)", str(_DEFAULTS["dry_run"]).lower()),
        ("move", "Move instead of copy (true/false)", str(_DEFAULTS["move"]).lower()),
        ("update", "Update changed files (true/false)", str(_DEFAULTS["update"]).lower()),
        ("interactive", "Interactive mode (true/false)", str(_DEFAULTS["interactive"]).lower()),
        ("identify", "AcoustID identification (true/false)", str(_DEFAULTS["identify"]).lower()),
        ("select", "Interactive directory selection (true/false)", str(_DEFAULTS["select"]).lower()),
    ]

    result: dict[str, object] = {}

    for key, label, hardcoded_default in settings:
        default = str(existing.get(key, hardcoded_default))
        value = input_fn(f"  {label} [{default}]: ").strip()
        if not value:
            value = default
        if key in _BOOL_KEYS:
            result[key] = value.lower() in ("true", "1", "yes")
        else:
            result[key] = value

    # acoustid_key — special handling: skip if empty
    acoustid_default = existing.get("acoustid_key", "")
    acoustid_prompt = f"  AcoustID API key [{acoustid_default}]: " if acoustid_default else "  AcoustID API key: "
    acoustid_val = input_fn(acoustid_prompt).strip()
    if not acoustid_val and acoustid_default:
        acoustid_val = acoustid_default
    if acoustid_val:
        result["acoustid_key"] = acoustid_val

    # Remove boolean defaults that are False to keep config clean
    for key in _BOOL_KEYS:
        if key in result and result[key] is False:
            del result[key]

    path = config_dir / CONFIG_FILENAME
    path.write_text(_to_toml(result))
    print_fn(f"Configuration saved to {path}")
    return path


def _to_toml(data: dict) -> str:
    """Serialize a flat dict to TOML format."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, list):
            items = ", ".join(f'"{v}"' for v in value)
            lines.append(f"{key} = [{items}]")
        elif isinstance(value, str):
            lines.append(f'{key} = "{value}"')
        elif value is None:
            continue
        else:
            lines.append(f"{key} = {value}")
    return "\n".join(lines) + "\n" if lines else ""
