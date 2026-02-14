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

### Find duplicates in a directory

```bash
undisorder dupes /path/to/unsorted-media
```

Shows duplicate groups with file paths and sizes. Scans photos, videos, and audio files.

### Import files into your collection

```bash
# Preview (dry run)
undisorder import /path/to/unsorted-media --dry-run

# Import photos, videos, and audio to default locations
undisorder import /path/to/unsorted-media

# Custom targets
undisorder import /path/to/unsorted-media \
    --images-target ~/Bilder/Fotos \
    --video-target ~/Videos \
    --audio-target ~/Musik

# With GPS reverse geocoding (offline, no internet needed)
undisorder import /path/to/unsorted-media --geocoding=offline

# Interactive mode — confirm each folder name
undisorder import /path/to/unsorted-media --interactive

# Move files instead of copying
undisorder import /path/to/unsorted-media --move
```

### Filter what gets imported

When importing from deep backup folders, not everything should be imported — e.g. WAV samples inside DAW project folders are not music.

```bash
# Exclude WAV files and DAW project directories
undisorder import /mnt/backup \
    --exclude '*.wav' \
    --exclude-dir 'DAW*' --exclude-dir '.ableton' \
    --dry-run

# Interactively review each directory before importing
undisorder import /mnt/backup --select --dry-run

# Combine: exclude by pattern, then pick from what remains
undisorder import /mnt/backup \
    --exclude '*.wav' --exclude-dir 'DAW*' \
    --select --dry-run
```

Patterns are case-insensitive and use glob syntax. `--exclude` matches filenames, `--exclude-dir` matches any directory component in the path.

### Import audio with AcoustID identification

For audio files with missing or incomplete tags, use AcoustID to identify them:

```bash
# Identify untagged audio files via AcoustID + MusicBrainz
undisorder import /path/to/music --identify --acoustid-key=YOUR_KEY

# Or set the key via environment variable
export ACOUSTID_API_KEY=YOUR_KEY
undisorder import /path/to/music --identify
```

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
└── .undisorder.db
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
└── .undisorder.db
```

### Directory name priority (photos/videos)

1. **Source directory name** — if meaningful (not "DCIM", "Camera", etc.)
2. **EXIF keywords/subject** — from photo metadata
3. **GPS place name** — via reverse geocoding (when enabled)
4. **Description** — from EXIF ImageDescription
5. **Fallback** — plain `YYYY/YYYY-MM/`

## How It Works

### Photos and videos

1. **Scan**: Recursively find all photos and videos, classify by extension
2. **Filter**: Apply `--exclude` / `--exclude-dir` patterns, then `--select` for interactive review
3. **Metadata**: Extract EXIF dates, GPS, keywords via `exiftool`
4. **Deduplicate source**: Group by file size, then SHA256 hash
5. **Check target**: Compare hashes against SQLite index (`.undisorder.db`)
6. **Organize**: Determine target path using metadata + intelligent naming
7. **Execute**: Copy/move files, update hash index

### Audio files

1. **Scan**: Identify audio files by extension (MP3, FLAC, OGG, M4A, WAV, ...)
2. **Filter**: Same exclude/select filtering as photos/videos
3. **Tags**: Read embedded tags (artist, album, title, track number) via mutagen
4. **Identify** (optional): For files with missing tags, fingerprint via AcoustID and look up metadata on MusicBrainz
5. **Deduplicate**: SHA256-based deduplication, same as photos/videos
6. **Organize**: Place in `Artist/Album/NN_Title.ext` structure
7. **Execute**: Copy/move files, update hash index

## Hash Database and Metadata Editing

undisorder tracks imported files via SHA256 content hashes in a SQLite database (`.undisorder.db`) inside each target directory. This is how it knows which files have already been imported and avoids duplicates across runs.

**Important:** The hashes are computed over the entire file content. If you later edit metadata on imported files — e.g. tagging photos in Digikam, editing ID3 tags in an audio player, or writing EXIF data with exiftool — the file content changes and the stored hash no longer matches the file on disk. This means:

- `undisorder check` may report false duplicates or miss real ones
- `undisorder hashdb` (rebuild) will recompute correct hashes from the current file content
- Re-importing the same source files is safe as long as the source hasn't changed, because the DB also stores source paths

If you routinely edit metadata on imported files, run `undisorder hashdb <target>` afterwards to keep the index in sync.

## Development

```bash
# Run tests
pytest

# Run tests with verbose output
pytest -v
```

## License

MIT
