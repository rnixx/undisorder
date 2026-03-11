#!/usr/bin/env bash
# Verify results of manual tests.
# Run after: testing/setup.sh && testing/run.sh
set -uo pipefail

BASE=/tmp/undisorder-test
DB="$BASE/config/undisorder/undisorder.db"
VENV="$(cd "$(dirname "$0")/.." && pwd)/venv/bin/python"
pass=0
fail=0

check() {
    local desc="$1"
    shift
    if eval "$@" > /dev/null 2>&1; then
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
    if ! eval "$@" > /dev/null 2>&1; then
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

# Helper: run a Python query against the DB, print result
db_query() {
    "$VENV" -c "
import sqlite3
conn = sqlite3.connect('$DB')
conn.row_factory = sqlite3.Row
result = conn.execute(\"\"\"$1\"\"\").fetchone()
print(result[0] if result else '')
conn.close()
" 2>/dev/null
}

echo ""
echo "================================================================"
echo "  VERIFY: Import results (copy mode)"
echo "================================================================"

# Photos imported (2 unique — photo1_copy is a dupe of photo1)
n=$(count_files "$BASE/photos")
check "Photos: 2 files imported (got $n)" '[ "$n" -eq 2 ]'

# Check date-based directory structure: YYYY/YYYY-MM_topic
# photo1 from vacation/ with EXIF 2024-03 → 2024/2024-03_vacation
# photo2 from vacation/ with EXIF 2024-06 → 2024/2024-06_vacation
check "Photos: 2024 year directory exists" 'test -d "$BASE/photos/2024"'
photo_subdirs=$(find "$BASE/photos/2024" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
check "Photos: 2 month directories under 2024 (got $photo_subdirs)" '[ "$photo_subdirs" -eq 2 ]'

# Videos imported (1 video)
n=$(count_files "$BASE/videos")
check "Videos: 1 file imported (got $n)" '[ "$n" -eq 1 ]'

# Audio imported (2 mp3 + 1 wav; the dupe wav and dupe mp3 are skipped)
n=$(count_files "$BASE/musik")
check "Audio: 3 files imported (got $n)" '[ "$n" -eq 3 ]'

# Audio directory structure (Artist/Album/)
check "Audio: Beatles directory exists" 'test -d "$BASE/musik/The Beatles"'
check "Audio: Abbey Road directory exists" 'test -d "$BASE/musik/The Beatles/Abbey Road"'

# Duplicates were skipped (photo1_copy, song1_dup, one wav dupe not imported)
# Total should be 2+1+3 = 6
total_photos=$(count_files "$BASE/photos")
total_videos=$(count_files "$BASE/videos")
total_audio=$(count_files "$BASE/musik")
total=$((total_photos + total_videos + total_audio))
check "Dedup: total 6 files imported (got $total)" '[ "$total" -eq 6 ]'

# Source files still exist (copy mode)
check "Copy mode: source photo1 still exists" 'test -f "$BASE/source/vacation/photo1.jpg"'
check "Copy mode: source song1 still exists" 'test -f "$BASE/source/music/song1.mp3"'

# Hidden files not imported
check_not "Hidden: .hidden_photo.jpg not imported" 'find "$BASE/photos" -name ".hidden_photo.jpg" -type f | grep -q .'
check_not "Hidden: thumb.jpg not imported" 'find "$BASE/photos" -name "thumb.jpg" -type f | grep -q .'

# Non-media not imported
check_not "Non-media: notes.txt not imported" 'find "$BASE/photos" "$BASE/videos" "$BASE/musik" -name "notes.txt" -type f | grep -q .'

echo ""
echo "================================================================"
echo "  VERIFY: Move mode results"
echo "================================================================"

# Move targets have files
n_photos=$(count_files "$BASE/photos2")
n_audio=$(count_files "$BASE/musik2")
check "Move: photos imported to photos2 (got $n_photos)" '[ "$n_photos" -ge 1 ]'
check "Move: audio imported to musik2 (got $n_audio)" '[ "$n_audio" -ge 1 ]'

# Source files removed after move (media files should be gone)
check_not "Move: source photos removed" 'test -f "$BASE/source_move/vacation/photo1.jpg"'
check_not "Move: source audio removed" 'test -f "$BASE/source_move/music/song1.mp3"'

echo ""
echo "================================================================"
echo "  VERIFY: Dupes --delete results"
echo "================================================================"

n=$(count_files "$BASE/dupetest")
check "Dupes delete: 1 file remaining (got $n)" '[ "$n" -eq 1 ]'

echo ""
echo "================================================================"
echo "  VERIFY: Hash DB structure"
echo "================================================================"

check "HashDB: undisorder.db exists" 'test -f "$DB"'

# Schema version
schema_version=$(db_query "SELECT * FROM pragma_user_version")
check "HashDB: schema version is 1 (got ${schema_version:-?})" '[ "${schema_version:-0}" -eq 1 ]'

# Tables exist
files_table=$(db_query "SELECT name FROM sqlite_master WHERE type='table' AND name='files'")
check "HashDB: files table exists" '[ "$files_table" = "files" ]'

cache_table=$(db_query "SELECT name FROM sqlite_master WHERE type='table' AND name='acoustid_cache'")
check "HashDB: acoustid_cache table exists" '[ "$cache_table" = "acoustid_cache" ]'

echo ""
echo "================================================================"
echo "  VERIFY: Hash DB content (import records)"
echo "================================================================"

# Total record count: 6 files imported in TEST 3 (2 photos + 1 video + 3 audio)
db_total=$(db_query "SELECT COUNT(*) FROM files")
check "HashDB: 6 records total (got ${db_total:-0})" '[ "${db_total:-0}" -eq 6 ]'

# Records per target_dir
photos_resolved=$(cd "$BASE/photos" && pwd)
videos_resolved=$(cd "$BASE/videos" && pwd)
musik_resolved=$(cd "$BASE/musik" && pwd)

db_photos=$(db_query "SELECT COUNT(*) FROM files WHERE target_dir = '$photos_resolved'")
check "HashDB: 2 photo records (got ${db_photos:-0})" '[ "${db_photos:-0}" -eq 2 ]'

db_videos=$(db_query "SELECT COUNT(*) FROM files WHERE target_dir = '$videos_resolved'")
check "HashDB: 1 video record (got ${db_videos:-0})" '[ "${db_videos:-0}" -eq 1 ]'

db_audio=$(db_query "SELECT COUNT(*) FROM files WHERE target_dir = '$musik_resolved'")
check "HashDB: 3 audio records (got ${db_audio:-0})" '[ "${db_audio:-0}" -eq 3 ]'

# All records have original_hash = current_hash (no --identify was used)
db_hash_mismatch=$(db_query "SELECT COUNT(*) FROM files WHERE original_hash != current_hash")
check "HashDB: all original_hash = current_hash (mismatches: ${db_hash_mismatch:-?})" '[ "${db_hash_mismatch:-1}" -eq 0 ]'

# file_path values are relative (no leading /)
db_abs_paths=$(db_query "SELECT COUNT(*) FROM files WHERE file_path LIKE '/%'")
check "HashDB: all file_path relative (absolute: ${db_abs_paths:-?})" '[ "${db_abs_paths:-1}" -eq 0 ]'

# All records have non-empty import_date
db_no_date=$(db_query "SELECT COUNT(*) FROM files WHERE import_date IS NULL OR import_date = ''")
check "HashDB: all records have import_date (missing: ${db_no_date:-?})" '[ "${db_no_date:-1}" -eq 0 ]'

# No records for duplicate files (photo1_copy, song1_dup should not appear)
db_dupes=$(db_query "SELECT COUNT(*) FROM files WHERE file_path LIKE '%copy%' OR file_path LIKE '%dup%'")
check "HashDB: no records for dupe source names (got ${db_dupes:-?})" '[ "${db_dupes:-1}" -eq 0 ]'

# Verify file_path entries point to files that actually exist on disk
bad_paths=$("$VENV" -c "
import sqlite3, pathlib
conn = sqlite3.connect('$DB')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT target_dir, file_path FROM files').fetchall()
bad = 0
for row in rows:
    full = pathlib.Path(row['target_dir']) / row['file_path']
    if not full.exists():
        bad += 1
conn.close()
print(bad)
" 2>/dev/null || echo -1)
check "HashDB: all file_path entries exist on disk (missing: ${bad_paths:-?})" '[ "${bad_paths:-1}" -eq 0 ]'

echo ""
echo "================================================================"
echo "  VERIFY: AcoustID --identify"
echo "================================================================"

if [ -d "$BASE/musik3" ]; then
    n=$(count_files "$BASE/musik3")
    check "Identify: audio files imported (got $n)" '[ "$n" -ge 1 ]'

    # For identify tests, the DB was replaced — check the identify DB
    identify_db="$DB"
    cache_count=$("$VENV" -c "
import sqlite3
conn = sqlite3.connect('$identify_db')
n = conn.execute('SELECT COUNT(*) FROM acoustid_cache').fetchone()[0]
print(n)
conn.close()
" 2>/dev/null || echo 0)
    check "Identify: acoustid_cache populated (got ${cache_count:-0})" '[ "${cache_count:-0}" -gt 0 ]'
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
