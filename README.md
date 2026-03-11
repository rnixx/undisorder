# undisorder

Media organizer for photos, videos, and audio. Deduplicates via SHA256,
sorts by EXIF date and embedded audio tags, identifies unknown audio via
AcoustID/MusicBrainz, and imports into a clean directory structure.

## Motivation

Years of digital life leave behind a mess: phone backups scattered across
drives, camera dumps in nested DCIM folders, music libraries with broken
tags, duplicates everywhere. Existing tools either focus on one media type,
require a GUI, or want to manage your collection permanently.

undisorder is a one-shot import tool. Point it at a source, let it
deduplicate, sort, and copy. After import, the tool is done -- your files
live in a plain directory structure that works with any file manager, photo
organizer, or music player. No database lock-in, no daemon, no ongoing
dependency.

## Disclaimer

This tool copies and moves files. Use `--dry-run` to verify before
executing. The `dupes --delete` command permanently deletes files.
There is no undo.

The `--identify` option overwrites embedded audio tags in target files with
data from MusicBrainz. Original source files are not modified when using
`--move` (copy-then-delete).

AcoustID and MusicBrainz lookups depend on external services. Results may
be incomplete or incorrect.

No warranty. See LICENSE for details. If you encounter bugs or unexpected
behavior, please report them at
https://github.com/rnixx/undisorder/issues.

## Features

- **Deduplication** -- two-phase detection (file size grouping + SHA256
  hashing) finds byte-identical duplicates across directories. Import skips
  files already in the target via a central hash index.
- **Photo/video organization** -- extracts EXIF dates, creates
  `YYYY/YYYY-MM_Topic/` directory structures using meaningful source folder
  names. Supports JPEG, PNG, HEIC, RAW (CR2, CR3, NEF, ARW, DNG, ...),
  MP4, MOV, MKV, and more.
- **Audio organization** -- reads embedded tags (ID3, Vorbis, MP4 atoms) via
  mutagen, organizes into `Artist/Album/NN_Title.ext`.
- **Audio identification** -- AcoustID fingerprinting + MusicBrainz lookup
  overwrites missing/inaccurate tags and writes improved metadata into
  target files.
- **SQLite hash index** -- tracks `original_hash` and `current_hash` per
  file. Dedup works even after external metadata edits. Incremental rebuild
  via `hashdb` command.
- **Exclude patterns** -- glob-based file and directory filtering
  (case-insensitive).
- **Interactive selection** -- review and accept/skip source directories
  before import.
- **Batch processing** -- processes one source directory at a time (deepest
  first), 100 files per batch (photos/videos), 10 per batch (audio). One
  failed batch does not stop the rest.
- **Dry-run mode** -- preview all actions without executing.
- **Copy or move** -- default is copy. With `--move`, files are copied first,
  then source is deleted (safe for `--identify` workflows).

## Quickstart

### Prerequisites

Python 3.11+, exiftool, chromaprint:

```bash
# Ubuntu/Debian
sudo apt install libimage-exiftool-perl libchromaprint-dev

# Arch
sudo pacman -S perl-image-exiftool chromaprint

# macOS
brew install exiftool chromaprint
```

### Install

```bash
git clone https://github.com/rnixx/undisorder.git
cd undisorder
make install
source venv/bin/activate
```

### Typical workflow

```bash
# 1. Remove duplicates in source (keeps oldest by mtime)
undisorder dupes /mnt/backup --delete

# 2. Preview import
undisorder import /mnt/backup --select --dry-run

# 3. Import for real
undisorder import /mnt/backup \
    --select \
    --identify \
    --exclude '*.wav' --exclude-dir 'DAW*'
```

## Commands

### `undisorder dupes <source> [--delete]`

Find byte-identical duplicates in `<source>`. Groups files by size, then
hashes same-size files with SHA256. With `--delete`, keeps the oldest copy
(by mtime) and deletes the rest.

Does not detect acoustic duplicates (same song, different encoding).

### `undisorder import <source> [OPTIONS]`

Import photos, videos, and audio from `<source>` into organized target
directories.

### `undisorder hashdb <target>`

Incremental rebuild of the hash index for `<target>`. Updates hashes for
known files, adds new files, removes records for deleted files. Run this
after editing metadata on imported files.

### `undisorder --configure`

Interactive configuration wizard. Creates or updates
`~/.config/undisorder/config.toml`.

## Options

### Global

| Option              | Description                                      |
| ------------------- | ------------------------------------------------ |
| `--verbose`, `-v`   | Debug output                                     |
| `--quiet`, `-q`     | Suppress informational output, warnings/errors   |
| `--configure`       | Interactive configuration setup                  |

### `import`

| Option                         | Default          | Description                           |
| ------------------------------ | ---------------- | ------------------------------------- |
| `--dry-run`                    | off              | Preview changes without executing     |
| `--move`                       | off              | Move files instead of copying         |
| `--images-target PATH`         | `~/Bilder/Fotos` | Target directory for photos           |
| `--video-target PATH`          | `~/Videos`       | Target directory for videos           |
| `--audio-target PATH`          | `~/Musik`        | Target directory for audio            |
| `--identify` / `--no-identify` | off              | AcoustID + MusicBrainz identification |
| `--acoustid-key KEY`           | --               | AcoustID API key (overrides env/cfg)  |
| `--exclude PATTERN`            | --               | Exclude files by glob (repeatable)    |
| `--exclude-dir PATTERN`        | --               | Exclude dirs by glob (repeatable)     |
| `--select`                     | off              | Interactive directory selection       |

### `dupes`

| Option     | Description                                      |
| ---------- | ------------------------------------------------ |
| `--delete` | Delete newer duplicates, keep oldest by mtime    |

### AcoustID API key

Resolved in order:

1. `--acoustid-key` CLI flag
2. `ACOUSTID_API_KEY` environment variable
3. `acoustid_key` in config.toml

Get a free key at https://acoustid.org/new-application.

## Configuration

`~/.config/undisorder/config.toml` (override with `$UNDISORDER_CONFIG_DIR`
or `$XDG_CONFIG_HOME`):

```toml
images_target = "~/Bilder/Fotos"
video_target = "~/Videos"
audio_target = "~/Musik"
identify = true
acoustid_key = "your-api-key"
exclude = ["*.wav", "*.aiff"]
exclude_dir = ["DAW*"]
```

CLI flags override config values. List fields (`exclude`, `exclude_dir`)
are merged from CLI and config.

## Directory structures

### Photos and videos

```
~/Bilder/Fotos/
├── 2023/
│   ├── 2023-08_Urlaub-Kroatien/
│   └── 2023-12/
└── 2024/
    └── 2024-07_Geburtstag/
```

Date from EXIF (DateTimeOriginal, CreateDate, QuickTime, XMP), fallback to
file mtime. Directory name from source folder if meaningful, otherwise plain
`YYYY-MM`. Generic names (DCIM, Camera, downloads, ...) and camera folder
patterns (100APPLE, 101_PANA, ...) are ignored.

### Audio

```
~/Musik/
├── The Beatles/
│   └── Abbey Road/
│       ├── 01_Come Together.mp3
│       └── 02_Something.mp3
└── Unknown Artist/
    └── Unknown Album/
        └── untitled_track.mp3
```

Path: `{target}/{Artist}/{Album}/{NN_Title}{ext}`. Falls back to
`Unknown Artist` / `Unknown Album` for missing tags.

## Development

### Setup

```bash
git clone https://github.com/rnixx/undisorder.git
cd undisorder
make install
```

### QA

```bash
make test        # Run tests
make check       # Linting (ruff + isort)
make typecheck   # Type checking (mypy)
make format      # Auto-fix lint issues
```

CI runs all checks via GitHub Actions on push and pull request
(Python 3.11, 3.12, 3.13).

### Manual testing

The `testing/` directory contains scripts for end-to-end testing with
real media files.

#### Additional system dependencies

The test setup script (`testing/setup.sh`) generates synthetic media
files and requires these tools in addition to the runtime prerequisites:

- **ffmpeg** -- with `lavfi` input support, `libx264` video codec, and
  `aac` audio codec (standard in most distribution packages)
- **exiftool** -- already required at runtime, also used to stamp EXIF
  dates on generated test images

```bash
# Ubuntu/Debian
sudo apt install ffmpeg libimage-exiftool-perl

# Arch
sudo pacman -S ffmpeg perl-image-exiftool

# macOS
brew install ffmpeg exiftool
```

#### Running

```bash
testing/setup.sh     # Create test data in /tmp/undisorder-test/
testing/run.sh       # Run all manual tests
testing/verify.sh    # Verify results
```

For AcoustID identification tests, set `ACOUSTID_API_KEY` before running.

## Author

Robert Niederreiter <rnix@squarewave.at>

## License

GPL-2.0-only
