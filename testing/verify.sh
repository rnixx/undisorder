#!/usr/bin/env bash
# Verify results of manual tests.
# Run after: testing/setup.sh && testing/run.sh
set -uo pipefail

BASE=/tmp/undisorder-test
pass=0
fail=0

check() {
    local desc="$1"
    shift
    if "$@" > /dev/null 2>&1; then
        echo "  PASS: $desc"
        ((pass++))
    else
        echo "  FAIL: $desc"
        ((fail++))
    fi
}

check_not() {
    local desc="$1"
    shift
    if ! "$@" > /dev/null 2>&1; then
        echo "  PASS: $desc"
        ((pass++))
    else
        echo "  FAIL: $desc"
        ((fail++))
    fi
}

count_files() {
    find "$1" -type f ! -name "*.db" 2>/dev/null | wc -l
}

echo ""
echo "================================================================"
echo "  VERIFY: Import results (copy mode)"
echo "================================================================"

# Photos imported
n=$(count_files "$BASE/photos")
check "Photos: 2 files imported (got $n)" [ "$n" -eq 2 ]

# Check date-based directory structure
check "Photos: 2024-03 directory exists" test -d "$BASE/photos/2024-03"* || test -d "$BASE/photos"/*2024-03*
photo_dirs=$(find "$BASE/photos" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
check "Photos: 2 date directories (got $photo_dirs)" [ "$photo_dirs" -eq 2 ]

# Videos imported
n=$(count_files "$BASE/videos")
check "Videos: 1 file imported (got $n)" [ "$n" -eq 1 ]

# Audio imported
n=$(count_files "$BASE/musik")
check "Audio: 2 files imported (got $n)" [ "$n" -eq 2 ]

# Audio directory structure (Artist/Album/)
check "Audio: Beatles directory exists" test -d "$BASE/musik/The Beatles"
check "Audio: Abbey Road directory exists" test -d "$BASE/musik/The Beatles/Abbey Road"

# Duplicates were skipped (photo1_copy and song1_dup not imported separately)
# Total should be 2+1+2 = 5, not 7
total=$(count_files "$BASE/photos" && count_files "$BASE/videos" && count_files "$BASE/musik")
total_photos=$(count_files "$BASE/photos")
total_videos=$(count_files "$BASE/videos")
total_audio=$(count_files "$BASE/musik")
total=$((total_photos + total_videos + total_audio))
check "Dedup: total 5 files imported (got $total)" [ "$total" -eq 5 ]

# Source files still exist (copy mode)
check "Copy mode: source photo1 still exists" test -f "$BASE/source/vacation/photo1.jpg"
check "Copy mode: source song1 still exists" test -f "$BASE/source/music/song1.mp3"

# Hidden files not imported
check_not "Hidden: .hidden_photo.jpg not imported" find "$BASE/photos" -name ".hidden_photo.jpg" -type f | grep -q .
check_not "Hidden: thumb.jpg not imported" find "$BASE/photos" -name "thumb.jpg" -type f | grep -q .

# Non-media not imported
check_not "Non-media: notes.txt not imported" find "$BASE/photos" "$BASE/videos" "$BASE/musik" -name "notes.txt" -type f | grep -q .

echo ""
echo "================================================================"
echo "  VERIFY: Move mode results"
echo "================================================================"

# Move targets have files
n_photos=$(count_files "$BASE/photos2")
n_audio=$(count_files "$BASE/musik2")
check "Move: photos imported to photos2 (got $n_photos)" [ "$n_photos" -ge 1 ]
check "Move: audio imported to musik2 (got $n_audio)" [ "$n_audio" -ge 1 ]

# Source files removed after move
check_not "Move: source photos removed" test -f "$BASE/source_move/vacation/photo1.jpg"
check_not "Move: source audio removed" test -f "$BASE/source_move/music/song1.mp3"

echo ""
echo "================================================================"
echo "  VERIFY: Dupes --delete results"
echo "================================================================"

n=$(count_files "$BASE/dupetest")
check "Dupes delete: 1 file remaining (got $n)" [ "$n" -eq 1 ]

echo ""
echo "================================================================"
echo "  VERIFY: Hash DB"
echo "================================================================"

VENV="$(cd "$(dirname "$0")/.." && pwd)/venv/bin/python"
check "HashDB: undisorder.db exists" test -f "$BASE/config/undisorder/undisorder.db"

db_count=$("$VENV" -c "
import sqlite3
conn = sqlite3.connect('$BASE/config/undisorder/undisorder.db')
n = conn.execute('SELECT COUNT(*) FROM files').fetchone()[0]
print(n)
conn.close()
" 2>/dev/null)
check "HashDB: records in DB (got ${db_count:-0})" [ "${db_count:-0}" -gt 0 ]

echo ""
echo "================================================================"
echo "  VERIFY: AcoustID --identify"
echo "================================================================"

if [ -d "$BASE/musik3" ]; then
    n=$(count_files "$BASE/musik3")
    check "Identify: audio files imported (got $n)" [ "$n" -ge 1 ]

    cache_count=$("$VENV" -c "
import sqlite3
conn = sqlite3.connect('$BASE/config/undisorder/undisorder.db')
n = conn.execute('SELECT COUNT(*) FROM acoustid_cache').fetchone()[0]
print(n)
conn.close()
" 2>/dev/null)
    check "Identify: acoustid_cache populated (got ${cache_count:-0})" [ "${cache_count:-0}" -gt 0 ]
else
    echo "  SKIP: --identify not tested (no ACOUSTID_API_KEY)"
fi

# ======================================================================
# Summary
# ======================================================================
echo ""
echo "================================================================"
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
    echo "  ALL $total CHECKS PASSED"
else
    echo "  $pass/$total PASSED, $fail FAILED"
fi
echo "================================================================"
echo ""

exit "$fail"
