#!/usr/bin/env bash
set -euo pipefail

# Test Core Recurrence Functionality
# Tests the spawn/respawn separation fix

echo "========================================"
echo "Core Recurrence Functionality Test"
echo "========================================"
echo ""

# Enable debug
export DEBUG_RECURRENCE=1
export TASKDATA=/tmp/task_test_$$
export TASKRC=/tmp/taskrc_test_$$

# Setup
mkdir -p "$TASKDATA"
cat > "$TASKRC" << EOF
data.location=$TASKDATA
recurrence=no
confirmation=no
hooks=on
verbose=nothing
EOF

# Copy hooks
mkdir -p "$TASKDATA/hooks"
cp /home/claude/recurrence_common_hook.py "$TASKDATA/hooks/"
cp /home/claude/on-add_recurrence.py "$TASKDATA/hooks/"
cp /home/claude/on-exit_recurrence.py "$TASKDATA/hooks/"
chmod +x "$TASKDATA/hooks/on-add_recurrence.py"
chmod +x "$TASKDATA/hooks/on-exit_recurrence.py"

# Create symlink for on-modify
cd "$TASKDATA/hooks"
ln -sf on-add_recurrence.py on-modify_recurrence.py

echo "Test environment ready: $TASKDATA"
echo ""

# Test 1: Create recurring task and verify instance #1 spawns
echo "TEST 1: Create recurring task"
echo "========================================"
task rc:"$TASKRC" add "Daily standup" due:today r:1d type:period

echo ""
echo "Checking template..."
task rc:"$TASKRC" status:recurring export | jq '.[] | {id, description, status, rlast, type, r}'

echo ""
echo "Checking instances..."
task rc:"$TASKRC" rtemplate.any: export | jq '.[] | {id, description, rtemplate, rindex, due}'

echo ""
echo "Expected: Template with rlast:1, Instance with rindex:1"
echo ""

# Test 2: Complete instance #1, verify instance #2 spawns
echo "TEST 2: Complete instance #1"
echo "========================================"
task rc:"$TASKRC" 2 done

echo ""
echo "Checking template..."
task rc:"$TASKRC" status:recurring export | jq '.[] | {id, description, rlast}'

echo ""
echo "Checking instances..."
task rc:"$TASKRC" rtemplate.any: export | jq '.[] | {id, description, rindex, status, due}'

echo ""
echo "Expected: Template with rlast:2, Instance with rindex:2 (pending)"
echo ""

# Test 3: Modify template rlast (time machine) - respawn
echo "TEST 3: Time machine (rlast: 2 -> 5)"
echo "========================================"
task rc:"$TASKRC" 1 mod rlast:5

echo ""
echo "Checking template..."
task rc:"$TASKRC" status:recurring export | jq '.[] | {id, description, rlast}'

echo ""
echo "Checking instances..."
task rc:"$TASKRC" rtemplate.any: export | jq '.[] | {id, description, rindex, due}'

echo ""
echo "Expected: Template rlast:5 (unchanged by spawn_instance), Instance rindex:5"
echo ""

# Test 4: Complete instance #5, verify instance #6 spawns
echo "TEST 4: Complete instance #5"
echo "========================================"
# Find instance ID (might be 3 or 4 depending on respawn)
INST_ID=$(task rc:"$TASKRC" rtemplate.any: status:pending export | jq -r '.[0].id')
task rc:"$TASKRC" "$INST_ID" done

echo ""
echo "Checking template..."
task rc:"$TASKRC" status:recurring export | jq '.[] | {id, description, rlast}'

echo ""
echo "Checking instances..."
task rc:"$TASKRC" rtemplate.any: export | jq '.[] | {id, description, rindex, status, due}' | head -20

echo ""
echo "Expected: Template with rlast:6, Instance with rindex:6 (pending)"
echo ""

# Test 5: Modify non-recurrence attribute (should NOT respawn)
echo "TEST 5: Modify template priority (no respawn)"
echo "========================================"
BEFORE_COUNT=$(task rc:"$TASKRC" rtemplate.any: export | jq '. | length')
task rc:"$TASKRC" 1 mod priority:H

echo ""
echo "Checking instances..."
AFTER_COUNT=$(task rc:"$TASKRC" rtemplate.any: export | jq '. | length')

echo ""
echo "Before: $BEFORE_COUNT instances"
echo "After: $AFTER_COUNT instances"
echo "Expected: Same count (no respawn for non-recurrence field)"
echo ""

# Check debug log
echo "========================================"
echo "Debug Log (last 30 lines):"
echo "========================================"
tail -30 ~/.task/recurrence_debug.log 2>/dev/null || echo "No debug log found"

# Cleanup
echo ""
echo "Cleanup..."
rm -rf "$TASKDATA" "$TASKRC"

echo ""
echo "========================================"
echo "Test complete!"
echo "========================================"
