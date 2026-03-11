# Manual Test Suite

End-to-end tests that exercise undisorder against real (synthetic) media
files. Complements the unit tests in `tests/` which mock filesystem and
external tool interactions.

## Why both?

|                | Unit tests (`tests/`)              | Manual tests (`testing/`)                         |
| -------------- | ---------------------------------- | ------------------------------------------------- |
| Scope          | Individual functions, edge cases   | Full CLI workflows, cross-module integration      |
| Dependencies   | None (mocked)                      | ffmpeg, exiftool, real filesystem                 |
| Speed          | ~5 seconds                         | ~30 seconds                                       |
| Catches        | Logic regressions                  | Wiring bugs, CLI parsing, config, DB lifecycle    |

Unit tests verify that each component does the right thing in isolation.
Manual tests verify that the components work together: CLI parses flags,
config is loaded and merged, scanner classifies files, importer writes to
the correct targets, hash DB tracks imports, dedup skips known files.

## Prerequisites

- Python venv set up (`make install`)
- ffmpeg (with lavfi, libx264, aac)
- exiftool

## Usage

```bash
testing/setup.sh     # Generate test data in /tmp/undisorder-test/
testing/run.sh       # Execute all tests
testing/verify.sh    # Check results (exit code 0 = all passed)
```

For AcoustID tests: `ACOUSTID_API_KEY=... testing/run.sh`

## Isolation

All data lives under `/tmp/undisorder-test/`. The scripts use
`UNDISORDER_CONFIG_DIR` to redirect config and DB writes away from
`~/.config/undisorder/`. No files outside `/tmp` are read or written.

```
/tmp/undisorder-test/
├── source/           # Synthetic source files (photos, videos, audio)
├── photos/           # Import target (images)
├── videos/           # Import target (video)
├── musik/            # Import target (audio)
├── config/           # Config dir (config.toml, undisorder.db)
├── photos2/ ...      # Disposable targets for move/config tests
└── dupetest/         # Disposable dir for dupes --delete test
```

## Test data

Created by `setup.sh`:

| File                     | Type                              | Purpose                            |
| ------------------------ | --------------------------------- | ---------------------------------- |
| `vacation/photo1.jpg`    | JPEG, EXIF 2024-03-15             | Photo with date, meaningful dir    |
| `vacation/photo2.jpg`    | JPEG, EXIF 2024-06-20             | Different date, same source dir    |
| `backup/photo1_copy.jpg` | Byte-identical to photo1          | Duplicate detection                |
| `clips/video.mp4`        | H.264+AAC, 0.5s                   | Video import                       |
| `music/song1.mp3`        | MP3, 15s, ID3: Beatles/Come..     | Audio with tags                    |
| `music/song2.mp3`        | MP3, 15s, ID3: Beatles/Some..     | Audio with tags                    |
| `backup/song1_dup.mp3`   | Byte-identical to song1           | Audio duplicate                    |
| `DAW_Project/sample.wav` | Stub RIFF header                  | `--exclude-dir` target             |
| `junk.wav`               | Stub RIFF header (= sample.wav)   | `--exclude` target + wav dupe      |
| `.thumbs/thumb.jpg`      | Hidden dir copy of photo1         | Hidden file exclusion              |
| `.hidden_photo.jpg`      | Hidden file copy of photo1        | Hidden file exclusion              |
| `notes.txt`              | Plain text                        | Non-media exclusion                |

## Test cases

### Core workflow

| #   | Test             | Exercises                        | Assertions (verify.sh)                 |
| --- | ---------------- | -------------------------------- | -------------------------------------- |
| 1   | `dupes`          | Duplicate finder (size + SHA256) | Reports duplicate groups               |
| 2   | `import --dry`   | Dry-run prevents writes          | No files in targets                    |
| 3   | `import` (copy)  | Full pipeline: scan, classify,   | 2 photos YYYY/MM_topic, 1 video,       |
|     |                  | metadata, dedup, copy, DB insert | 3 audio Artist/Album, 6 DB records     |
| 4   | Re-import        | Hash DB dedup across runs        | All files skipped                      |
| 5   | `hashdb` rebuild | Incremental rebuild from disk    | Index updated without errors           |

### Filtering

| #   | Test               | Exercises                    | Assertions                             |
| --- | ------------------ | ---------------------------- | -------------------------------------- |
| 6   | `--exclude *.wav`  | File pattern exclusion       | wav files not imported                 |
| 7   | `--exclude-dir D*` | Directory pattern exclusion  | DAW_Project/ contents skipped          |

### Modes

| #   | Test             | Exercises                        | Assertions                             |
| --- | ---------------- | -------------------------------- | -------------------------------------- |
| 8   | `--move`         | Copy-then-delete, fresh DB       | Files in targets, source deleted       |
| 9   | `dupes --delete` | Delete dupes (keep oldest mtime) | 1 of 2 identical files remains         |

### CLI behavior

| #   | Test           | Exercises              | Assertions                             |
| --- | -------------- | ---------------------- | -------------------------------------- |
| 10  | `-v` (verbose) | Debug log level        | Extra output visible                   |
| 11  | `-q` (quiet)   | Warning-only log level | Minimal output                         |

### Error handling

| #   | Test            | Exercises                    | Assertions                             |
| --- | --------------- | ---------------------------- | -------------------------------------- |
| 12  | Schema mismatch | DB with future schema version| SystemExit, error message              |

### External services (optional)

| #   | Test         | Exercises                     | Assertions                             |
| --- | ------------ | ----------------------------- | -------------------------------------- |
| 13  | `--identify` | AcoustID + MusicBrainz lookup | Audio imported, cache populated        |

### Configuration

| #   | Test            | Exercises                       | Assertions                           |
| --- | --------------- | ------------------------------- | ------------------------------------ |
| 14  | `--configure`   | Interactive config creation     | config.toml written correctly        |
| 15  | Config settings | UNDISORDER_CONFIG_DIR, targets, | Files in config targets, excludes    |
|     |                 | exclude patterns from config    | applied, DB records match            |
| 16  | CLI overrides   | --images-target vs config       | CLI value takes precedence           |

## DB verification

`verify.sh` checks the SQLite database beyond just "it exists":

- Schema version (`PRAGMA user_version`) = 1
- Tables `files` and `acoustid_cache` exist
- Record count matches imported file count (per target_dir)
- `original_hash` = `current_hash` (no identify in copy test)
- All `file_path` values are relative
- All `import_date` values are non-empty
- No records for duplicate source filenames
- Every `file_path` entry resolves to an existing file on disk
