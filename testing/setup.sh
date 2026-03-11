#!/usr/bin/env bash
# Create test data for manual undisorder testing.
# All data is created under /tmp/undisorder-test/.
set -euo pipefail

BASE=/tmp/undisorder-test
VENV="$(cd "$(dirname "$0")/.." && pwd)/venv/bin/python"

echo "=== Cleaning up previous test data ==="
rm -rf "$BASE"
mkdir -p "$BASE"/{source,photos,videos,musik}

# -----------------------------------------------------------------------
# Photos
# -----------------------------------------------------------------------
echo "=== Creating photos ==="
mkdir -p "$BASE"/source/{vacation,backup}

# photo1: EXIF date 2024-03-15
ffmpeg -f lavfi -i "color=c=red:s=100x100:d=0.04" -frames:v 1 \
    "$BASE/source/vacation/photo1.jpg" -y -loglevel error
exiftool -overwrite_original -DateTimeOriginal="2024:03:15 10:00:00" \
    "$BASE/source/vacation/photo1.jpg"

# photo2: different content, EXIF date 2024-06-20
ffmpeg -f lavfi -i "color=c=blue:s=100x100:d=0.04" -frames:v 1 \
    "$BASE/source/vacation/photo2.jpg" -y -loglevel error
exiftool -overwrite_original -DateTimeOriginal="2024:06:20 14:30:00" \
    "$BASE/source/vacation/photo2.jpg"

# photo duplicate (identical to photo1)
cp "$BASE/source/vacation/photo1.jpg" "$BASE/source/backup/photo1_copy.jpg"

# -----------------------------------------------------------------------
# Video
# -----------------------------------------------------------------------
echo "=== Creating video ==="
mkdir -p "$BASE/source/clips"
ffmpeg -f lavfi -i "color=c=green:s=64x64:d=0.5" -f lavfi -i "sine=f=440:d=0.5" \
    -c:v libx264 -preset ultrafast -c:a aac -shortest \
    "$BASE/source/clips/video.mp4" -y -loglevel error

# -----------------------------------------------------------------------
# Audio
# -----------------------------------------------------------------------
echo "=== Creating audio ==="
mkdir -p "$BASE/source/music"

# Use 15-second audio for AcoustID compatibility (chromaprint needs ~10s+)
ffmpeg -f lavfi -i "sine=frequency=440:duration=15" -q:a 9 \
    "$BASE/source/music/song1.mp3" -y -loglevel error
ffmpeg -f lavfi -i "sine=frequency=880:duration=15" -q:a 9 \
    "$BASE/source/music/song2.mp3" -y -loglevel error

# Write tags via mutagen (always available in venv)
"$VENV" -c "
import mutagen.id3
for path, tags in [
    ('$BASE/source/music/song1.mp3', {
        'TPE1': 'The Beatles', 'TALB': 'Abbey Road',
        'TIT2': 'Come Together', 'TRCK': '1',
    }),
    ('$BASE/source/music/song2.mp3', {
        'TPE1': 'The Beatles', 'TALB': 'Abbey Road',
        'TIT2': 'Something', 'TRCK': '2',
    }),
]:
    f = mutagen.id3.ID3(path)
    for tag, val in tags.items():
        cls = getattr(mutagen.id3, tag)
        f.add(cls(encoding=3, text=[val]))
    f.save()
print('Audio tags written.')
"

# Audio duplicate (identical to song1)
cp "$BASE/source/music/song1.mp3" "$BASE/source/backup/song1_dup.mp3"

# -----------------------------------------------------------------------
# Exclude test data
# -----------------------------------------------------------------------
echo "=== Creating exclude test data ==="
mkdir -p "$BASE/source/DAW_Project"
printf 'RIFF\x00\x00\x00\x00WAVEfmt ' > "$BASE/source/DAW_Project/sample.wav"
printf 'RIFF\x00\x00\x00\x00WAVEfmt ' > "$BASE/source/junk.wav"

# -----------------------------------------------------------------------
# Hidden files (should be ignored by scanner)
# -----------------------------------------------------------------------
echo "=== Creating hidden files ==="
mkdir -p "$BASE/source/.thumbs"
cp "$BASE/source/vacation/photo1.jpg" "$BASE/source/.thumbs/thumb.jpg"
cp "$BASE/source/vacation/photo1.jpg" "$BASE/source/.hidden_photo.jpg"

# -----------------------------------------------------------------------
# Non-media file
# -----------------------------------------------------------------------
echo "notes" > "$BASE/source/notes.txt"

# -----------------------------------------------------------------------
# Config (XDG_CONFIG_HOME override)
# -----------------------------------------------------------------------
echo "=== Creating test config ==="
mkdir -p "$BASE/config/undisorder"
cat > "$BASE/config/undisorder/config.toml" <<EOF
images_target = "$BASE/photos"
video_target = "$BASE/videos"
audio_target = "$BASE/musik"
EOF

# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------
echo ""
echo "=== Test data created ==="
echo ""
find "$BASE/source" -type f | sort | sed "s|$BASE/||"
echo ""
echo "Base dir:   $BASE"
echo "Config:     XDG_CONFIG_HOME=$BASE/config"
echo ""
echo "Run tests:  testing/run.sh"
