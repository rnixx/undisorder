# undisorder

Photo/Video/Audio organization tool — deduplicates, sorts by date/topic/artist, and imports into a clean directory structure. Designed for bulk imports of scattered media collections, with ongoing ingestion support.

## Features

- **Smart deduplication**: `dupes --delete` removes cross-directory duplicates before import (file size grouping + SHA256); import skips files already in target via hash index
- **Per-directory batch processing**: Processes one source directory at a time (deepest first) — low memory, resilient to errors, natural progress feedback
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
# 1. Remove cross-directory duplicates in source (keeps oldest by mtime)
undisorder dupes /mnt/backup --delete

# 2. Pick source folders interactively, preview what would happen
undisorder import /mnt/backup --select --dry-run

# 3. Happy with the plan? Import for real, with all the bells and whistles
undisorder import /mnt/backup \
    --select \
    --geocoding=online \
    --identify \
    --interactive \
    --exclude '*.wav' --exclude-dir 'DAW*'
```

### Find and remove duplicates in a directory

```bash
# Show duplicate groups (no changes)
undisorder dupes /path/to/unsorted-media

# Remove duplicates, keeping the oldest by modification time
undisorder dupes /path/to/unsorted-media --delete
```

Shows duplicate groups with file paths and sizes. Scans photos, videos, and audio files. With `--delete`, removes newer copies and keeps the file with the oldest modification time from each duplicate group. Run this before `import` to clean up cross-directory duplicates in your source.

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

### Pre-import: remove source duplicates

Run `undisorder dupes --delete <source>` before importing. This finds files with identical content across directories (via file size grouping + SHA256), keeps the copy with the oldest modification time from each duplicate group, and deletes the rest. This ensures no cross-directory duplicates enter the import pipeline.

### Photos and videos

Import processes files **one source directory at a time** (deepest first), in batches of up to 100 files. Each batch is a self-contained unit — if one directory fails, the rest still succeed.

1. **Scan**: Recursively find all photos and videos, classify by extension
2. **Filter**: Apply `--exclude` / `--exclude-dir` patterns, then `--select` for interactive review
3. **Per-directory batch**:
   - **Metadata**: Extract EXIF dates, GPS, keywords via `exiftool`
   - **Hash**: SHA256 hash each file
   - **Check target**: Compare hashes against central SQLite index — skip already-imported files
   - **Organize**: Determine target path using metadata + intelligent naming
   - **Execute**: Copy/move files, update hash index

### Audio files

Same per-directory processing, in batches of up to 10 files (smaller batches due to potential AcoustID web requests).

1. **Scan**: Identify audio files by extension (MP3, FLAC, OGG, M4A, WAV, ...)
2. **Filter**: Same exclude/select filtering as photos/videos
3. **Tags**: Read embedded tags (artist, album, title, track number) via mutagen
4. **Identify** (optional): For files with missing tags, fingerprint via AcoustID and look up metadata on MusicBrainz
5. **Per-directory batch**:
   - **Hash**: SHA256 hash each file
   - **Check target**: Skip already-imported files
   - **Organize**: Place in `Artist/Album/NN_Title.ext` structure
   - **Execute**: Copy/move files, update hash index

## Database Architecture (HashDB)

Central SQLite database at `~/.config/undisorder/undisorder.db` (or `$XDG_CONFIG_HOME/undisorder/undisorder.db`).
Each `HashDB` instance stores a `target_dir` (resolved path) — it is passed as an informational column on `insert` and `record_import`.
A SHA256 hash uniquely identifies a file globally (collisions at typical collection sizes are practically impossible at ~10^-68).

### Tables

#### `files` — What is in the target?

```sql
CREATE TABLE files (
    hash        TEXT PRIMARY KEY,   -- SHA256 of file content
    target_dir  TEXT NOT NULL,      -- informational
    file_size   INTEGER NOT NULL,
    file_path   TEXT NOT NULL,      -- relative path within target_dir
    date_taken  TEXT,
    import_date TEXT NOT NULL,
    source_path TEXT
);
CREATE INDEX idx_target ON files(target_dir);
```

- PK: `hash` alone — byte-identical files are stored only once.
- `target_dir` is informational (which target the file belongs to).
- `source_path` is optional — absent during `rebuild`.

#### `imports` — What has already been imported?

```sql
CREATE TABLE imports (
    source_path TEXT PRIMARY KEY,   -- absolute path of the source file
    target_dir  TEXT NOT NULL,      -- informational
    hash        TEXT NOT NULL,      -- SHA256 at time of import
    file_path   TEXT                -- relative target path (may be NULL)
);
```

- PK: `source_path` alone — a source path is imported only once.
- Protects against re-import after metadata edits (EXIF tagging etc.),
  where the hash changes but the source path stays the same.
- `hash` is updated on `--update` (`update_import`).

#### `acoustid_cache` — AcoustID results

```sql
CREATE TABLE acoustid_cache (
    file_hash    TEXT PRIMARY KEY,  -- SHA256, not target_dir-scoped
    fingerprint  TEXT,
    duration     REAL,
    recording_id TEXT,              -- MusicBrainz recording ID
    artist TEXT, album TEXT, title TEXT,
    track_number INTEGER, disc_number INTEGER, year INTEGER,
    lookup_date  TEXT NOT NULL
);
```

- 1:1 mapping hash -> lookup result.
- Saves repeated API calls (fpcalc + AcoustID + MusicBrainz).
- Not target_dir-scoped — applies globally.

### SHA256 Collisions

Practically impossible. 256-bit output space (2^256), no known collision
attack. Can be treated as unique for deduplication purposes.

### Dedup Queries During Import

Two-stage check per file, in this order:

**Stage 1 — Hash check** (`hash_exists`):
```sql
SELECT 1 FROM files WHERE hash = ?
```
Identical file content already in target -> skip.

**Stage 2 — Source path check** (`get_import`):
```sql
SELECT * FROM imports WHERE source_path = ?
```
Source path already imported -> skip. Exception: `--update` and source mtime
newer than target mtime -> file is overwritten.

### Write Timing

| Event | Table | Method |
|-------|-------|--------|
| After copy/move of a new file | `files` | `insert()` |
| Immediately after | `imports` | `record_import()` |
| On update (source newer) | `files` | `delete_by_hash()` + `insert()` |
| Immediately after | `imports` | `update_import()` |
| After AcoustID lookup | `acoustid_cache` | `store_acoustid_cache()` (via `identify_audio`) |

Every write commits immediately — no batch commits.

### Source Tree Duplicate Search (`dupes`)

Works **without the DB** — purely via file content using `hasher.find_duplicates()`:

1. **Phase 1** — Group by `file_size` (cheap, filters out unique sizes)
2. **Phase 2** — SHA256 hash only for files of equal size

No AcoustID, no fingerprinting. Two different encodings of the same
song (MP3 vs FLAC, 128kbps vs 320kbps) are **not** detected as duplicates
— only byte-identical files.

With `--delete`, files are sorted by mtime, the oldest copy is kept, the rest is deleted.

### AcoustID and Dedup

AcoustID runs during import **before** the hash dedup check, but serves a
different purpose: it **identifies** untagged audio files (artist/album/title
via fingerprint matching). It does not replace hash-based dedup.

Acoustic duplicates (same song, different encoding) could be detected via
the `recording_id` from the AcoustID cache — this is not done during
import or `dupes`.

### Metadata Editing

**Important:** Hashes are computed over the entire file content. If you later edit metadata on imported files — e.g. tagging photos in Digikam, editing ID3 tags in an audio player, or writing EXIF data with exiftool — the file content changes and the stored hash no longer matches the file on disk. This means:

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
