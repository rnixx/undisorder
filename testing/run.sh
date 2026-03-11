#!/usr/bin/env bash
# Run all manual tests sequentially.
# Expects: testing/setup.sh was run first.
# Optional: ACOUSTID_API_KEY in environment for identify tests.
set -euo pipefail

BASE=/tmp/undisorder-test
export UNDISORDER_CONFIG_DIR="$BASE/config"
UNDISORDER="$(cd "$(dirname "$0")/.." && pwd)/venv/bin/python -m undisorder"
DB="$BASE/config/undisorder.db"

pass=0
fail=0

run_test() {
    local num="$1" name="$2"
    shift 2
    echo ""
    echo "================================================================"
    echo "  TEST $num: $name"
    echo "================================================================"
    echo "  \$ $*"
    echo ""
}

# ======================================================================
# TEST 1: dupes
# ======================================================================
run_test 1 "Find duplicates" $UNDISORDER dupes "$BASE/source"
$UNDISORDER dupes "$BASE/source"

# ======================================================================
# TEST 2: dry-run import
# ======================================================================
run_test 2 "Dry-run import" $UNDISORDER import "$BASE/source" --dry-run
$UNDISORDER import "$BASE/source" --dry-run

# ======================================================================
# TEST 3: import (copy mode)
# ======================================================================
run_test 3 "Import (copy)" $UNDISORDER import "$BASE/source"
$UNDISORDER import "$BASE/source"

# ======================================================================
# TEST 4: re-import = all skipped
# ======================================================================
run_test 4 "Re-import (expect all skipped)" $UNDISORDER import "$BASE/source"
$UNDISORDER import "$BASE/source"

# ======================================================================
# TEST 5: hashdb rebuild
# ======================================================================
run_test 5 "Hashdb rebuild" $UNDISORDER hashdb "$BASE/photos"
$UNDISORDER hashdb "$BASE/photos"

# ======================================================================
# TEST 6: exclude file pattern
# ======================================================================
run_test 6 "Exclude *.wav" $UNDISORDER import "$BASE/source" --exclude "*.wav" --dry-run
$UNDISORDER import "$BASE/source" --exclude "*.wav" --dry-run

# ======================================================================
# TEST 7: exclude directory pattern
# ======================================================================
run_test 7 "Exclude DAW*" $UNDISORDER import "$BASE/source" --exclude-dir "DAW*" --dry-run
$UNDISORDER import "$BASE/source" --exclude-dir "DAW*" --dry-run

# ======================================================================
# TEST 8: import with --move (fresh DB + fresh targets)
# ======================================================================
run_test 8 "Import with --move (fresh targets)"

# Fresh source for move test (don't destroy original source)
rm -rf "$BASE"/{photos2,videos2,musik2,source_move}
mkdir -p "$BASE"/{photos2,videos2,musik2}
cp -r "$BASE/source" "$BASE/source_move"

# Back up the import DB and delete it so dedup does not skip files
cp "$DB" "$DB.import_bak" 2>/dev/null || true
rm -f "$DB"

# Override config for this test
cat > "$BASE/config/config.toml" <<EOF
images_target = "$BASE/photos2"
video_target = "$BASE/videos2"
audio_target = "$BASE/musik2"
EOF

echo "  \$ $UNDISORDER import $BASE/source_move --move"
echo ""
$UNDISORDER import "$BASE/source_move" --move

# Restore import DB and config
rm -f "$DB"
mv "$DB.import_bak" "$DB" 2>/dev/null || true
cat > "$BASE/config/config.toml" <<EOF
images_target = "$BASE/photos"
video_target = "$BASE/videos"
audio_target = "$BASE/musik"
EOF

# ======================================================================
# TEST 9: dupes --delete
# ======================================================================
run_test 9 "Dupes --delete"
rm -rf "$BASE/dupetest"
mkdir -p "$BASE/dupetest"
cp "$BASE/source/music/song1.mp3" "$BASE/dupetest/a.mp3"
sleep 1
cp "$BASE/dupetest/a.mp3" "$BASE/dupetest/b.mp3"
echo "  \$ $UNDISORDER dupes $BASE/dupetest --delete"
echo ""
$UNDISORDER dupes "$BASE/dupetest" --delete

# ======================================================================
# TEST 10: verbose output
# ======================================================================
run_test 10 "Verbose output" $UNDISORDER -v dupes "$BASE/source"
$UNDISORDER -v dupes "$BASE/source" 2>&1 | head -20
echo "  ... (truncated)"

# ======================================================================
# TEST 11: quiet output
# ======================================================================
run_test 11 "Quiet output" $UNDISORDER -q dupes "$BASE/source"
$UNDISORDER -q dupes "$BASE/source"

# ======================================================================
# TEST 12: schema mismatch
# ======================================================================
run_test 12 "Schema version mismatch"
VENV="$(cd "$(dirname "$0")/.." && pwd)/venv/bin/python"

# Save current DB and create one with wrong schema version
cp "$DB" "$DB.bak" 2>/dev/null || true
"$VENV" -c "
import sqlite3, pathlib
db_path = pathlib.Path('$DB')
db_path.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(db_path)
conn.execute('PRAGMA user_version = 99')
conn.commit()
conn.close()
print(f'Set schema version to 99 in {db_path}')
"
echo "  \$ $UNDISORDER import $BASE/source --dry-run"
echo ""
if $UNDISORDER import "$BASE/source" --dry-run 2>&1; then
    echo "  UNEXPECTED: should have exited with error"
else
    echo "  OK: exited with error as expected"
fi
# Restore original DB
rm -f "$DB"
if [ -f "$DB.bak" ]; then
    mv "$DB.bak" "$DB"
fi

# ======================================================================
# TEST 13: --identify (only if ACOUSTID_API_KEY is set)
# ======================================================================
if [ -n "${ACOUSTID_API_KEY:-}" ]; then
    run_test 13 "Import with --identify"

    rm -rf "$BASE"/{photos3,videos3,musik3}
    mkdir -p "$BASE"/{photos3,videos3,musik3}

    # Back up and delete DB so dedup does not skip files
    cp "$DB" "$DB.bak" 2>/dev/null || true
    rm -f "$DB"

    cat > "$BASE/config/config.toml" <<EOF
images_target = "$BASE/photos3"
video_target = "$BASE/videos3"
audio_target = "$BASE/musik3"
acoustid_key = "$ACOUSTID_API_KEY"
EOF

    echo "  \$ $UNDISORDER import $BASE/source --identify"
    echo ""
    $UNDISORDER import "$BASE/source" --identify

    # Restore config (keep identify DB for verify)
    cat > "$BASE/config/config.toml" <<EOF
images_target = "$BASE/photos"
video_target = "$BASE/videos"
audio_target = "$BASE/musik"
EOF
else
    echo ""
    echo "================================================================"
    echo "  TEST 13: SKIPPED (set ACOUSTID_API_KEY to enable)"
    echo "================================================================"
fi

# ======================================================================
# TEST 14: --configure writes config file
# ======================================================================
run_test 14 "Interactive --configure"

# Use a separate config dir for this test
CONFIGURE_DIR="$BASE/config_test"
rm -rf "$CONFIGURE_DIR"
mkdir -p "$CONFIGURE_DIR"

# Pipe answers to --configure (all defaults except images_target and dry_run)
UNDISORDER_CONFIG_DIR="$CONFIGURE_DIR" \
    $UNDISORDER --configure <<EOF
$BASE/photos_configured


true



EOF
echo "  Config written to: $CONFIGURE_DIR/config.toml"
echo "  Contents:"
cat "$CONFIGURE_DIR/config.toml" | sed 's/^/    /'

# ======================================================================
# TEST 15: config file settings picked up by CLI
# ======================================================================
run_test 15 "CLI uses settings from config file"

# Write a config with custom targets + exclude pattern
CFG_DIR="$BASE/config_cli_test"
rm -rf "$CFG_DIR" "$BASE"/{photos_cfg,videos_cfg,musik_cfg}
mkdir -p "$CFG_DIR" "$BASE"/{photos_cfg,videos_cfg,musik_cfg}

cat > "$CFG_DIR/config.toml" <<EOF
images_target = "$BASE/photos_cfg"
video_target = "$BASE/videos_cfg"
audio_target = "$BASE/musik_cfg"
exclude = ["*.wav"]
exclude_dir = ["DAW*"]
EOF

# Back up main DB, delete it for a clean import
cp "$DB" "$DB.bak" 2>/dev/null || true
rm -f "$DB"

echo "  Config: $CFG_DIR/config.toml"
cat "$CFG_DIR/config.toml" | sed 's/^/    /'
echo ""
echo "  \$ UNDISORDER_CONFIG_DIR=$CFG_DIR $UNDISORDER import $BASE/source"
echo ""
UNDISORDER_CONFIG_DIR="$CFG_DIR" $UNDISORDER import "$BASE/source"

# Restore main DB
rm -f "$DB"
mv "$DB.bak" "$DB" 2>/dev/null || true

# ======================================================================
# TEST 16: CLI flags override config file
# ======================================================================
run_test 16 "CLI flags override config"

# Config has default targets, but CLI overrides images_target
rm -rf "$BASE/photos_override"
mkdir -p "$BASE/photos_override"

# Back up main DB, delete it
cp "$DB" "$DB.bak" 2>/dev/null || true
rm -f "$DB"

echo "  Config images_target: $BASE/photos (from main config)"
echo "  CLI --images-target:  $BASE/photos_override"
echo ""
echo "  \$ $UNDISORDER import $BASE/source --images-target $BASE/photos_override --dry-run"
echo ""
$UNDISORDER import "$BASE/source" --images-target "$BASE/photos_override" --dry-run

# Restore main DB
rm -f "$DB"
mv "$DB.bak" "$DB" 2>/dev/null || true

# ======================================================================
# Done
# ======================================================================
echo ""
echo "================================================================"
echo "  ALL TESTS COMPLETE - run testing/verify.sh to check results"
echo "================================================================"
