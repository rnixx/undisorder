# undisorder

Photo/Video/Audio organization tool — deduplicates, sorts by date/topic/artist, and imports into a clean directory structure. Designed for bulk imports of scattered media collections, with ongoing ingestion support.

## Features

- **Smart deduplication**: 2-phase detection (file size grouping + SHA256) — fast even for large collections
- **Intelligent directory naming**: Uses EXIF dates, source folder names, keywords, GPS data to create meaningful folder structures like `2024/2024-03_Wien/`
- **Photo + Video support**: Handles all common formats (JPEG, PNG, HEIC, RAW, MP4, MOV, MKV, ...)
- **Audio support**: Organizes by Artist/Album using embedded tags (ID3, Vorbis, MP4 atoms) via mutagen
- **Audio identification**: AcoustID fingerprinting + MusicBrainz lookup for untagged audio files
- **GPS reverse geocoding**: Offline (bundled database) or online (OpenStreetMap/Nominatim)
- **SQLite hash index**: Tracks imported files to avoid re-importing duplicates across runs
- **Exclude patterns**: Filter out files or directories by glob pattern (e.g. DAW project folders, WAV samples)
- **Interactive selection**: Review and accept/skip directories before importing
- **Dry-run mode**: Preview what would happen before committing
- **Interactive mode**: Confirm/edit folder name suggestions
- **Copy or move**: Default is copy; use `--move` to relocate files

## Installation

### Prerequisites

- Python 3.11+
- `exiftool` (system package)
- `chromaprint` (system package, for AcoustID audio fingerprinting)

```bash
# Ubuntu/Debian
sudo apt install libimage-exiftool-perl libchromaprint-dev

# Arch
sudo pacman -S perl-image-exiftool chromaprint

# macOS
brew install exiftool chromaprint
```

### Install undisorder

```bash
git clone https://github.com/rnixx/undisorder.git
cd undisorder
python -m venv venv
source venv/bin/activate
pip install -e .
```

## Usage

### TL;DR — typical workflow

```bash
# 1. Pick source folders interactively, preview what would happen
undisorder import /mnt/backup --select --dry-run

# 2. Happy with the plan? Import for real, with all the bells and whistles
undisorder import /mnt/backup \
    --select \
    --geocoding=online \
    --identify \
    --interactive \
    --exclude '*.wav' --exclude-dir 'DAW*'
```

### Find duplicates in a directory

```bash
undisorder dupes /path/to/unsorted-media
```

Shows duplicate groups with file paths and sizes. Scans photos, videos, and audio files.

### Import files into your collection

```bash
# Simple import — photos, videos, and audio to default locations
undisorder import /path/to/unsorted-media

# Preview first (dry run)
undisorder import /path/to/unsorted-media --dry-run

# Custom targets
undisorder import /path/to/unsorted-media \
    --images-target ~/Bilder/Fotos \
    --video-target ~/Videos \
    --audio-target ~/Musik

# Move files instead of copying
undisorder import /path/to/unsorted-media --move

# Re-import files when source is newer than previous import
undisorder import /path/to/unsorted-media --update

# Full workflow: select folders, geocode, identify audio, confirm names
undisorder import /path/to/unsorted-media \
    --select \
    --geocoding=online \
    --identify \
    --interactive
```

### Filter what gets imported

When importing from deep backup folders, not everything should be imported — e.g. WAV samples inside DAW project folders are not music.

```bash
# Exclude WAV files and DAW project directories
undisorder import /mnt/backup \
    --exclude '*.wav' \
    --exclude-dir 'DAW*' --exclude-dir '.ableton'

# Interactively review each directory before importing
undisorder import /mnt/backup --select

# Combine: exclude by pattern, then pick from what remains
undisorder import /mnt/backup \
    --exclude '*.wav' --exclude-dir 'DAW*' \
    --select
```

Patterns are case-insensitive and use glob syntax. `--exclude` matches filenames, `--exclude-dir` matches any directory component in the path.

### Import audio with AcoustID identification

For audio files with missing or incomplete tags, use AcoustID to identify them:

```bash
undisorder import /path/to/music --identify
```

The AcoustID API key is resolved in this order:
1. `--acoustid-key=YOUR_KEY` CLI flag
2. `ACOUSTID_API_KEY` environment variable
3. `acoustid_key` in `config.toml` (see Configuration below)

Get a free AcoustID API key at https://acoustid.org/new-application.

### Check target for duplicates

```bash
undisorder check ~/Bilder/Fotos
```

### Rebuild hash index

```bash
undisorder hashdb ~/Bilder/Fotos
```

Useful after manually adding/removing files from the target.

### Verbosity

```bash
# Debug output
undisorder --verbose import /path/to/media

# Suppress informational output, only show warnings/errors
undisorder --quiet import /path/to/media
```

### Configuration

Settings can be persisted in `~/.config/undisorder/config.toml` (or `$XDG_CONFIG_HOME/undisorder/config.toml`). Create or update it interactively:

```bash
undisorder --configure
```

This walks through all settings and writes `config.toml`. Existing values are shown as defaults when updating.

Example `config.toml`:

```toml
images_target = "~/Bilder/Fotos"
video_target = "~/Videos"
audio_target = "~/Musik"
geocoding = "offline"
identify = true
acoustid_key = "your-api-key"
exclude = ["*.wav", "*.aiff"]
exclude_dir = ["DAW*"]
```

CLI flags always override config file values. For list fields (`exclude`, `exclude_dir`), CLI and config values are merged.

## Directory Structure

### Photos and videos

undisorder creates a `YYYY/YYYY-MM` directory structure with intelligent naming:

```
~/Bilder/Fotos/
├── 2023/
│   ├── 2023-08_Urlaub-Kroatien/
│   │   ├── DSC_0001.jpg
│   │   └── DSC_0002.jpg
│   └── 2023-12/
│       └── IMG_4567.jpg
├── 2024/
│   ├── 2024-03_Wien/
│   │   └── photo.jpg
│   └── 2024-07_Geburtstag-Oma/
│       ├── IMG_1234.jpg
│       └── IMG_1235.jpg
```

### Audio files

Audio files are organized by Artist/Album:

```
~/Musik/
├── The Beatles/
│   └── Abbey Road/
│       ├── 01_Come Together.mp3
│       ├── 02_Something.mp3
│       └── ...
├── Pink Floyd/
│   └── The Dark Side of the Moon/
│       ├── 01_Speak to Me.flac
│       └── ...
├── Unknown Artist/
│   └── Unknown Album/
│       └── untitled_track.mp3
```

### Directory name priority (photos/videos)

1. **Source directory name** — if meaningful (not "DCIM", "Camera", etc.)
2. **EXIF keywords/subject** — from photo metadata
3. **GPS place name** — via reverse geocoding (when enabled)
4. **Description** — from EXIF ImageDescription
5. **User comment** — from EXIF UserComment
6. **Fallback** — plain `YYYY/YYYY-MM/`

## How It Works

### Photos and videos

1. **Scan**: Recursively find all photos and videos, classify by extension
2. **Filter**: Apply `--exclude` / `--exclude-dir` patterns, then `--select` for interactive review
3. **Metadata**: Extract EXIF dates, GPS, keywords via `exiftool`
4. **Deduplicate source**: Group by file size, then SHA256 hash — when duplicates are found, the copy with the oldest modification time is kept
5. **Check target**: Compare hashes against central SQLite index
6. **Organize**: Determine target path using metadata + intelligent naming
7. **Execute**: Copy/move files, update hash index

### Audio files

1. **Scan**: Identify audio files by extension (MP3, FLAC, OGG, M4A, WAV, ...)
2. **Filter**: Same exclude/select filtering as photos/videos
3. **Tags**: Read embedded tags (artist, album, title, track number) via mutagen
4. **Identify** (optional): For files with missing tags, fingerprint via AcoustID and look up metadata on MusicBrainz
5. **Deduplicate**: SHA256-based deduplication, same as photos/videos — oldest copy wins
6. **Organize**: Place in `Artist/Album/NN_Title.ext` structure
7. **Execute**: Copy/move files, update hash index

## Hash Database and Metadata Editing

undisorder tracks imported files via SHA256 content hashes in a central SQLite database at `~/.config/undisorder/undisorder.db` (or `$XDG_CONFIG_HOME/undisorder/undisorder.db`). Each target directory's data is stored separately within the same database. This is how it knows which files have already been imported and avoids duplicates across runs.

**Important:** The hashes are computed over the entire file content. If you later edit metadata on imported files — e.g. tagging photos in Digikam, editing ID3 tags in an audio player, or writing EXIF data with exiftool — the file content changes and the stored hash no longer matches the file on disk. This means:

- `undisorder check` may report false duplicates or miss real ones
- `undisorder hashdb` (rebuild) will recompute correct hashes from the current file content
- Re-importing the same source files is safe as long as the source hasn't changed, because the DB also stores source paths

If you routinely edit metadata on imported files, run `undisorder hashdb <target>` afterwards to keep the index in sync.

## Contributing

### Setup

```bash
git clone https://github.com/rnixx/undisorder.git
cd undisorder
python -m venv venv
source venv/bin/activate
pip install -e .[dev]
```

### QA checks

All checks must pass before merging. Run them locally:

```bash
# Tests
pytest -v

# Linting
ruff check src/ tests/

# Import sorting (Plone profile)
isort --check src/ tests/

# Type checking
ty check src/ tests/
```

Fix auto-fixable issues:

```bash
ruff check --fix src/ tests/
isort src/ tests/
```

These same checks run in CI via GitHub Actions on every push and pull request.

## License

GPL-2.0-only
