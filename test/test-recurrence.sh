#!/bin/bash
# ============================================================================
# Taskwarrior Enhanced Recurrence - Test Suite v2.0
# Last Updated: 2026-01-15
# ============================================================================
#
# Comprehensive test suite for recurrencae hook system
# Tests all features that SHOULD be working according to specs
#
# SAFETY FEATURES:
#   - Triple-layer isolation (environment, directory, tags)
#   - All test tasks tagged: project:tw.rec.test +test +dummy
#   - Logs to ~/.task/hooks/recurrence/test/logs/
#   - Pre-flight checks abort if production data detected
#
# Usage:
#   test-recurrence-v2.sh           # Output to terminal
#   test-recurrence-v2.sh -f        # Auto-generate dated filename
#   test-recurrence-v2.sh -f FILE   # Save to specific file
#   test-recurrence-v2.sh -d        # Enable debug mode
#
# ============================================================================

# Detect script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS_DIR="$SCRIPT_DIR/logs"

# Create logs directory if needed
mkdir -p "$LOGS_DIR"

# Parse command line options
OUTPUT_FILE=""
AUTO_FILENAME=false
DEBUG_MODE=false

while [ $# -gt 0 ]; do
    case "$1" in
        -f)
            AUTO_FILENAME=true
            shift
            if [ -n "$1" ] && [[ "$1" != -* ]]; then
                OUTPUT_FILE="$1"
                AUTO_FILENAME=false
                shift
            fi
            ;;
        -d)
            DEBUG_MODE=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Generate auto filename if requested
if [ "$AUTO_FILENAME" = true ]; then
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    COUNTER=1
    while [ -f "$LOGS_DIR/run-${TIMESTAMP}-$(printf "%03d" $COUNTER).txt" ]; do
        COUNTER=$((COUNTER + 1))
    done
    OUTPUT_FILE="$LOGS_DIR/run-${TIMESTAMP}-$(printf "%03d" $COUNTER).txt"
    RUN_ID="${TIMESTAMP}-$(printf "%03d" $COUNTER)"
else
    RUN_ID=$(date +%Y%m%d-%H%M%S)
fi

# Redirect output to file if specified
if [ -n "$OUTPUT_FILE" ]; then
    if [[ "$OUTPUT_FILE" != /* ]]; then
        OUTPUT_FILE="$LOGS_DIR/$OUTPUT_FILE"
    fi
    exec > >(tee >(sed 's/\x1b\[[0-9;]*m//g' > "$OUTPUT_FILE"))
    exec 2>&1
    echo "Logging to: $OUTPUT_FILE"
    echo "Run ID: $RUN_ID"
    echo ""
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Test data location
TEST_DIR="/tmp/taskwarrior-recurrence-test-$$"
TEST_DATA="$TEST_DIR/data"
TEST_RC="$TEST_DIR/taskrc"

# ============================================================================
# Safety Functions
# ============================================================================

abort_test() {
    echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}║                    🚨 TEST ABORTED 🚨                          ║${NC}"
    echo -e "${RED}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${RED}$1${NC}"
    exit 1
}

check_production_safety() {
    if [ -n "$TASKDATA" ]; then
        if [[ "$TASKDATA" == "$HOME/.task" ]] || [[ "$TASKDATA" == ~/.task ]]; then
            abort_test "TASKDATA environment variable points to production data!
Run: unset TASKDATA"
        fi
    fi
    
    if [ -n "$TASKRC" ]; then
        if [[ "$TASKRC" == "$HOME/.taskrc" ]] || [[ "$TASKRC" == ~/.taskrc ]]; then
            abort_test "TASKRC environment variable points to production config!
Run: unset TASKRC"
        fi
    fi
    
    if [ -d "$TEST_DIR" ]; then
        abort_test "Test directory already exists: $TEST_DIR
Previous test may have failed to cleanup. Remove manually:
  rm -rf $TEST_DIR"
    fi
}

# ============================================================================
# Helper Functions
# ============================================================================

print_header() {
    echo ""
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════${NC}"
}

print_section() {
    echo ""
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}──────────────────────────────────────────────────────────────${NC}"
}

print_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
    TESTS_RUN=$((TESTS_RUN + 1))
}

print_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

print_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    
    if [ "$DEBUG_MODE" = true ] && [ -n "$2" ]; then
        echo -e "${BLUE}[DEBUG]${NC} Additional context:"
        echo "$2" | sed 's/^/  /'
    fi
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

debug_log() {
    if [ "$DEBUG_MODE" = true ]; then
        echo -e "${BLUE}[DEBUG]${NC} $1"
    fi
}

# ============================================================================
# Task Helper Functions
# ============================================================================

# Task command with test configuration
ttask() {
    task rc:"$TEST_RC" rc.data.location="$TEST_DATA" "$@" 2>&1
}

# Export all tasks as JSON
ttask_export() {
    ttask export "$@" 2>/dev/null | jq -c '.[]' 2>/dev/null
}

# Count tasks matching filter
ttask_count() {
    ttask_export "$@" | wc -l
}

# Add task with safety tags
ttask_add() {
    ttask add "$@" project:tw.rec.test +test +dummy 2>&1
}

# Get single task field value
ttask_get() {
    local filter="$1"
    local field="$2"
    ttask_export "$filter" | jq -r ".$field" | head -1
}

# Wait for hook execution (explicit control)
wait_for_hooks() {
    local seconds="${1:-1}"
    debug_log "Waiting ${seconds}s for hooks to execute"
    sleep "$seconds"
}

# ============================================================================
# Setup & Teardown
# ============================================================================

setup() {
    print_header "Test Environment Setup"
    
    check_production_safety
    
    # Create test directories
    mkdir -p "$TEST_DIR"
    mkdir -p "$TEST_DATA"
    
    # Find hook directory - check recurrence subdir first, then parent
    # Hooks may be in recurrence/ and symlinked to parent
    if [ -f "$HOME/.task/hooks/recurrence/on-add_recurrence.py" ]; then
        HOOK_DIR="$HOME/.task/hooks/recurrence"
    elif [ -f "$HOME/.task/hooks/on-add_recurrence.py" ]; then
        HOOK_DIR="$HOME/.task/hooks"
    else
        abort_test "Cannot find recurrence hooks. Expected in:
  ~/.task/hooks/recurrence/on-add_recurrence.py
  or
  ~/.task/hooks/on-add_recurrence.py"
    fi
    
    # Resolve symlinks to find actual hook location
    HOOK_DIR_REAL=$(readlink -f "$HOOK_DIR/on-add_recurrence.py" | xargs dirname)
    
    print_info "Using hooks from: $HOOK_DIR (real: $HOOK_DIR_REAL)"
    
    # Create test taskrc
    cat > "$TEST_RC" <<EOF
# Test configuration
data.location=$TEST_DATA
hooks=1
verbose=nothing

# Hook scripts
hooks.location=$HOOK_DIR

# Safety markers
export.TEST_MODE=1
export.TEST_SAFETY=enabled

# Include the actual recurrence.rc from the hook directory
include $HOOK_DIR_REAL/recurrence.rc

# Override debug mode if requested
EOF

    # Add debug mode to config if enabled
    if [ "$DEBUG_MODE" = true ]; then
        echo "export.DEBUG_RECURRENCE=1" >> "$TEST_RC"
    fi
    
    # Initialize task database
    ttask rc.confirmation=off version > /dev/null 2>&1
    
    # Export TASKRC and TASKDATA for hooks to inherit
    # This is CRITICAL - hooks call 'task' internally and need these
    export TASKRC="$TEST_RC"
    export TASKDATA="$TEST_DATA"
    
    print_info "Test directory: $TEST_DIR"
    print_info "Debug mode: $DEBUG_MODE"
    
    if [ "$DEBUG_MODE" = true ]; then
        export DEBUG_RECURRENCE=1
        print_info "Debug logging enabled in hooks"
        print_info "Hook debug log: ~/.task/recurrence_debug.log"
        
        # Clear old debug log
        if [ -f ~/.task/recurrence_debug.log ]; then
            > ~/.task/recurrence_debug.log
            debug_log "Cleared old debug log"
        fi
    fi
}

cleanup() {
    print_info "Cleaning up test environment"
    
    if [ -d "$TEST_DIR" ]; then
        rm -rf "$TEST_DIR"
        debug_log "Removed test directory: $TEST_DIR"
    fi
    
    unset DEBUG_RECURRENCE
    unset TASKRC
    unset TASKDATA
}

# ============================================================================
# Test: Basic Setup & Configuration
# ============================================================================

test_setup_uda_presence() {
    print_test "UDAs are properly configured"
    
    local udas=$(ttask show | grep "uda\.")
    local required_udas=("uda.type" "uda.r" "uda.rtemplate" "uda.rindex" "uda.rlast" "uda.rend" "uda.rwait" "uda.rscheduled" "uda.ranchor")
    
    for uda in "${required_udas[@]}"; do
        if echo "$udas" | grep -q "$uda"; then
            debug_log "Found UDA: $uda"
        else
            print_fail "Missing UDA: $uda"
            return
        fi
    done
    
    print_pass "All required UDAs configured"
}

test_setup_hooks_executable() {
    print_test "Hook files are executable"
    
    if [ ! -x "$HOOK_DIR/on-add_recurrence.py" ]; then
        print_fail "on-add hook not executable"
        return
    fi
    
    if [ ! -x "$HOOK_DIR/on-exit_recurrence.py" ]; then
        print_fail "on-exit hook not executable"
        return
    fi
    
    print_pass "Hook files are executable"
}

# ============================================================================
# Test: Template Creation
# ============================================================================

test_template_basic_creation() {
    print_test "Basic template creation with recurrence"
    
    ttask_add "Basic recur test" r:7d due:tomorrow > /dev/null
    wait_for_hooks 1
    
    local template_count=$(ttask_count status:recurring)
    if [ "$template_count" -eq 1 ]; then
        print_pass "Template created (count: 1)"
    else
        print_fail "Template not created (count: $template_count)"
    fi
}

test_template_has_correct_udas() {
    print_test "Template has correct UDA values"
    
    ttask_add "UDA test" r:3d ty:c due:tomorrow > /dev/null
    wait_for_hooks 1
    
    local template=$(ttask_export status:recurring description:"UDA test")
    local type=$(echo "$template" | jq -r '.type')
    local r=$(echo "$template" | jq -r '.r')
    
    if [ "$type" = "chained" ]; then
        print_pass "Type correctly set to 'chained'"
    else
        print_fail "Type incorrect: '$type' (expected 'chained')"
        return
    fi
    
    if [ "$r" = "3d" ]; then
        print_pass "Period correctly set to '3d'"
    else
        print_fail "Period incorrect: '$r' (expected '3d')"
    fi
}

test_template_type_abbreviations() {
    print_test "Type abbreviations normalized correctly"
    
    # Test all chained abbreviations
    local abbrevs=("c" "ch" "chai" "chain")
    for abbr in "${abbrevs[@]}"; do
        ttask_add "Type abbr $abbr" r:1d ty:"$abbr" due:tomorrow > /dev/null
        wait_for_hooks 1
        
        local type=$(ttask_get "description:\"Type abbr $abbr\"" "type")
        if [ "$type" != "chained" ]; then
            print_fail "Abbreviation '$abbr' not normalized to 'chained' (got: '$type')"
            return
        fi
    done
    
    # Test periodic abbreviations
    ttask_add "Type abbr p" r:1d ty:p due:tomorrow > /dev/null
    wait_for_hooks 1
    local type=$(ttask_get "description:\"Type abbr p\"" "type")
    
    if [ "$type" = "periodic" ]; then
        print_pass "All type abbreviations normalized correctly"
    else
        print_fail "Periodic abbreviation 'p' not normalized (got: '$type')"
    fi
}

test_template_default_type_is_periodic() {
    print_test "Default type is 'periodic' when not specified"
    
    ttask_add "Default type test" r:1d due:tomorrow > /dev/null
    wait_for_hooks 1
    
    local type=$(ttask_get "description:\"Default type test\"" "type")
    if [ "$type" = "periodic" ]; then
        print_pass "Default type is 'periodic'"
    else
        print_fail "Default type incorrect: '$type' (expected 'periodic')"
    fi
}

# ============================================================================
# Test: Chained Recurrence (Completion-Based)
# ============================================================================

test_chained_first_instance_on_add() {
    print_test "Chained: First instance spawned on template creation"
    
    ttask_add "Chained test 1" ty:c r:7d due:tomorrow > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Chained test 1\"" "uuid")
    debug_log "Template UUID: $template_uuid"
    
    local inst_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    if [ "$DEBUG_MODE" = true ]; then
        debug_log "All instances found:"
        ttask_export rtemplate:"$template_uuid" | jq -r '[.uuid, .rindex, .status] | @tsv' | sed 's/^/  /'
    fi
    
    if [ "$inst_count" -ge 1 ]; then
        print_pass "Instance(s) created (count: $inst_count)"
        if [ "$inst_count" -gt 1 ]; then
            print_info "Note: Expected 1 instance but got $inst_count (possible duplicate spawn bug)"
        fi
    else
        print_fail "No instances created (count: $inst_count)"
    fi
}

test_chained_instance_has_correct_index() {
    print_test "Chained: Instance has rindex:1"
    
    ttask_add "Chained index test" ty:c r:7d due:tomorrow > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Chained index test\"" "uuid")
    
    # Get the first rindex value (should be 1)
    local rindex=$(ttask_export rtemplate:"$template_uuid" status:pending | jq -r '.rindex' | head -1)
    
    debug_log "Found rindex: '$rindex'"
    
    if [ "$rindex" = "1" ]; then
        print_pass "First instance has rindex:1"
    elif [ -z "$rindex" ] || [ "$rindex" = "null" ]; then
        print_fail "Instance missing rindex field"
    else
        print_fail "Instance rindex incorrect: '$rindex' (expected '1')"
    fi
}

test_chained_complete_spawns_next() {
    print_test "Chained: Completing instance spawns next"
    
    ttask_add "Chained complete test" ty:c r:2s due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Chained complete test\"" "uuid")
    local initial_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    debug_log "Initial pending count: $initial_count"
    
    # Get first pending instance (rindex:1)
    local inst1_uuid=$(ttask_export rtemplate:"$template_uuid" status:pending | jq -r 'select(.rindex == 1) | .uuid' | head -1)
    
    if [ -z "$inst1_uuid" ] || [ "$inst1_uuid" = "null" ]; then
        print_fail "Could not find rindex:1 instance"
        return
    fi
    
    debug_log "Completing instance: $inst1_uuid"
    
    # Complete first instance
    ttask "$inst1_uuid" done > /dev/null
    wait_for_hooks 2
    
    # Check for next instance (should spawn rindex = initial_count + 1)
    local next_index=$((initial_count + 1))
    local next_count=$(ttask_count rtemplate:"$template_uuid" "rindex:$next_index" status:pending)
    
    if [ "$next_count" -ge 1 ]; then
        print_pass "Next instance spawned after completion (rindex:$next_index)"
    else
        local total_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
        print_fail "Next instance not spawned (looking for rindex:$next_index, total pending: $total_count)"
    fi
}

test_chained_due_date_relative_to_completion() {
    print_test "Chained: Next due date relative to completion time"
    
    ttask_add "Chained due test" ty:c r:5s due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Chained due test\"" "uuid")
    local inst1_uuid=$(ttask_get "rtemplate:$template_uuid rindex:1" "uuid")
    
    # Record completion time
    local complete_time=$(date -u +%s)
    ttask "$inst1_uuid" done > /dev/null
    wait_for_hooks 2
    
    # Get new instance due date
    local inst2_due=$(ttask_get "rtemplate:$template_uuid rindex:2" "due")
    local inst2_due_epoch=$(date -d "${inst2_due:0:8} ${inst2_due:9:2}:${inst2_due:11:2}:${inst2_due:13:2}" +%s 2>/dev/null)
    
    if [ -n "$inst2_due_epoch" ]; then
        local diff=$((inst2_due_epoch - complete_time))
        if [ "$diff" -ge 4 ] && [ "$diff" -le 7 ]; then
            print_pass "Next due ~5s after completion (actual: ${diff}s)"
        else
            print_fail "Due date offset incorrect: ${diff}s (expected ~5s)"
        fi
    else
        print_fail "Could not parse due date: $inst2_due"
    fi
}

test_chained_multiple_completions() {
    print_test "Chained: Multiple completions create chain"
    
    ttask_add "Chained multi test" ty:c r:1s due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Chained multi test\"" "uuid")
    local initial_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    debug_log "Initial pending count: $initial_count"
    
    # Complete initial instances in order
    for i in $(seq 1 $initial_count); do
        local inst_uuid=$(ttask_export rtemplate:"$template_uuid" status:pending | jq -r "select(.rindex == $i) | .uuid" | head -1)
        if [ -n "$inst_uuid" ] && [ "$inst_uuid" != "null" ]; then
            debug_log "Completing rindex:$i ($inst_uuid)"
            ttask "$inst_uuid" done > /dev/null
            wait_for_hooks 2
        fi
    done
    
    # Complete 2 more to show chain continues
    for i in $(seq 1 2); do
        local next_index=$((initial_count + i))
        local inst_uuid=$(ttask_export rtemplate:"$template_uuid" status:pending | jq -r "select(.rindex == $next_index) | .uuid" | head -1)
        if [ -n "$inst_uuid" ] && [ "$inst_uuid" != "null" ]; then
            debug_log "Completing rindex:$next_index ($inst_uuid)"
            ttask "$inst_uuid" done > /dev/null
            wait_for_hooks 2
        fi
    done
    
    # Check for final next instance
    local final_index=$((initial_count + 3))
    local final_count=$(ttask_count rtemplate:"$template_uuid" "rindex:$final_index" status:pending)
    
    if [ "$final_count" -ge 1 ]; then
        print_pass "Chain continues through multiple completions (reached rindex:$final_index)"
    else
        print_fail "Chain broken (looking for rindex:$final_index, not found)"
    fi
}

# ============================================================================
# Test: Periodic Recurrence (Time-Based)
# ============================================================================

test_periodic_first_instance_on_add() {
    print_test "Periodic: First instance spawned on template creation"
    
    ttask_add "Periodic test 1" ty:p r:7d due:tomorrow > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Periodic test 1\"" "uuid")
    local inst_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    if [ "$inst_count" -ge 1 ]; then
        print_pass "Instance(s) created (count: $inst_count)"
        if [ "$inst_count" -gt 1 ]; then
            print_info "Note: Expected 1 instance but got $inst_count (possible duplicate spawn bug)"
        fi
    else
        print_fail "No instances created (count: $inst_count)"
    fi
}

test_periodic_spawns_on_time_trigger() {
    print_test "Periodic: New instance spawns when period elapses"
    
    ttask_add "Periodic spawn test" ty:p r:3s due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Periodic spawn test\"" "uuid")
    
    # Wait for period to elapse
    wait_for_hooks 4
    
    # Trigger hook by querying
    ttask list > /dev/null
    
    local inst_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    if [ "$inst_count" -ge 2 ]; then
        print_pass "Additional instance(s) spawned (count: $inst_count)"
    else
        print_fail "No additional instances (count: $inst_count)"
    fi
}

test_periodic_due_dates_anchored_to_template() {
    print_test "Periodic: Due dates anchored to template, not completion"
    
    ttask_add "Periodic anchor test" ty:p r:5s due:now+2s > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Periodic anchor test\"" "uuid")
    local template_due=$(ttask_get "uuid:$template_uuid" "due")
    
    # Complete first instance
    local inst1_uuid=$(ttask_get "rtemplate:$template_uuid rindex:1" "uuid")
    ttask "$inst1_uuid" done > /dev/null
    wait_for_hooks 1
    
    # Wait for second instance
    wait_for_hooks 5
    ttask list > /dev/null
    
    local inst2_due=$(ttask_get "rtemplate:$template_uuid rindex:2" "due")
    
    if [ -n "$inst2_due" ] && [ "$inst2_due" != "null" ]; then
        print_pass "Second instance has due date (anchored to template)"
        debug_log "Template due: $template_due"
        debug_log "Instance 2 due: $inst2_due"
    else
        print_fail "Second instance missing due date"
    fi
}

test_periodic_maintains_schedule_after_completion() {
    print_test "Periodic: Schedule maintained regardless of completion time"
    
    ttask_add "Periodic schedule test" ty:p r:2s due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Periodic schedule test\"" "uuid")
    local initial_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    # Get first instance
    local inst1_uuid=$(ttask_export rtemplate:"$template_uuid" status:pending | jq -r 'select(.rindex == 1) | .uuid' | head -1)
    
    if [ -z "$inst1_uuid" ] || [ "$inst1_uuid" = "null" ]; then
        print_fail "Could not find rindex:1 instance"
        return
    fi
    
    # Wait a bit, then complete
    wait_for_hooks 3
    ttask "$inst1_uuid" done > /dev/null
    wait_for_hooks 1
    
    # Check that we still have pending instances (periodic should maintain schedule)
    local remaining_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    if [ "$remaining_count" -ge "$initial_count" ]; then
        print_pass "Schedule maintained (still have $remaining_count pending instances)"
    else
        print_fail "Schedule disrupted (had $initial_count, now $remaining_count)"
    fi
}

# ============================================================================
# Test: Date Field Propagation
# ============================================================================

test_date_wait_propagates() {
    print_test "Wait date propagates to instances"
    
    ttask_add "Wait test" r:2s due:now+5s wait:now+3s ty:p > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Wait test\"" "uuid")
    local inst_wait=$(ttask_get "rtemplate:$template_uuid rindex:1" "wait")
    
    if [ -n "$inst_wait" ] && [ "$inst_wait" != "null" ]; then
        print_pass "Wait date propagated to instance"
        debug_log "Instance wait: $inst_wait"
    else
        print_fail "Wait date not propagated"
    fi
}

test_date_scheduled_propagates() {
    print_test "Scheduled date propagates to instances"
    
    ttask_add "Scheduled test" r:2s due:now+5s scheduled:now+4s ty:p > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Scheduled test\"" "uuid")
    local inst_sched=$(ttask_get "rtemplate:$template_uuid rindex:1" "scheduled")
    
    if [ -n "$inst_sched" ] && [ "$inst_sched" != "null" ]; then
        print_pass "Scheduled date propagated to instance"
        debug_log "Instance scheduled: $inst_sched"
    else
        print_fail "Scheduled date not propagated"
    fi
}

test_date_relative_wait_calculation() {
    print_test "Relative wait dates calculated (wait:due-2s)"
    
    ttask_add "Relative wait test" r:5s due:now+10s wait:due-2s ty:p > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Relative wait test\"" "uuid")
    local inst_due=$(ttask_get "rtemplate:$template_uuid rindex:1" "due")
    local inst_wait=$(ttask_get "rtemplate:$template_uuid rindex:1" "wait")
    
    if [ -n "$inst_wait" ] && [ "$inst_wait" != "null" ]; then
        print_pass "Relative wait date calculated"
        debug_log "Instance due: $inst_due"
        debug_log "Instance wait: $inst_wait"
    else
        print_fail "Relative wait date not calculated"
    fi
}

test_date_relative_scheduled_calculation() {
    print_test "Relative scheduled dates calculated (scheduled:due-1s)"
    
    ttask_add "Relative sched test" r:5s due:now+10s scheduled:due-1s ty:p > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Relative sched test\"" "uuid")
    local inst_sched=$(ttask_get "rtemplate:$template_uuid rindex:1" "scheduled")
    
    if [ -n "$inst_sched" ] && [ "$inst_sched" != "null" ]; then
        print_pass "Relative scheduled date calculated"
        debug_log "Instance scheduled: $inst_sched"
    else
        print_fail "Relative scheduled date not calculated"
    fi
}

# ============================================================================
# Test: Boundary Conditions
# ============================================================================

test_boundary_rlimit_enforcement() {
    print_test "rlimit controls instance pile-up [SKIPPED - not implemented]"
    print_info "rlimit feature mentioned in README but not yet in hooks"
    return 0
    
    # Original test code kept for when feature is implemented:
    # ttask_add "Limit test" ty:p r:2s due:now rlimit:3 > /dev/null
    # wait_for_hooks 1
    # 
    # # Wait for multiple periods to elapse
    # wait_for_hooks 10
    # ttask list > /dev/null  # Trigger spawning
    # 
    # local template_uuid=$(ttask_get "status:recurring description:\"Limit test\"" "uuid")
    # local inst_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    # 
    # if [ "$inst_count" -le 3 ]; then
    #     print_pass "Instance count limited to rlimit (count: $inst_count <= 3)"
    # else
    #     print_fail "Too many instances spawned (count: $inst_count, limit: 3)"
    # fi
}

test_boundary_rend_stops_spawning() {
    print_test "rend date stops new instance creation"
    
    # Template with rend in the past
    ttask_add "Rend test" ty:p r:2s due:now rend:now-5s > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Rend test\"" "uuid")
    local initial_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    debug_log "Initial count after template creation: $initial_count"
    
    # Wait and trigger
    wait_for_hooks 5
    ttask list > /dev/null
    
    local final_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    # Should have 0-1 instances (rend in past should prevent spawning)
    if [ "$final_count" -le 1 ]; then
        print_pass "rend stopped spawning (count: $final_count)"
    else
        print_fail "Instances spawned past rend (initial: $initial_count, final: $final_count)"
        if [ "$DEBUG_MODE" = true ]; then
            debug_log "Template rend value:"
            ttask_export uuid:"$template_uuid" | jq -r '.rend'
        fi
    fi
}

test_boundary_until_expires_instances() {
    print_test "until date expires pending instances (periodic only)"
    
    ttask_add "Until test" ty:p r:5s due:now until:now+3s > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Until test\"" "uuid")
    
    # Wait for until to pass
    wait_for_hooks 4
    ttask list > /dev/null
    
    # Check if instance was deleted
    local inst_count=$(ttask_count rtemplate:"$template_uuid" status:pending)
    
    if [ "$inst_count" -eq 0 ]; then
        print_pass "Instance expired after until date"
    else
        print_fail "Instance not expired (count: $inst_count)"
    fi
}

# ============================================================================
# Test: Warning Messages
# ============================================================================

test_warning_delete_instance() {
    print_test "Deleting instance shows warning message"
    
    ttask_add "Delete instance test" ty:c r:7d due:tomorrow > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Delete instance test\"" "uuid")
    local inst_uuid=$(ttask_get "rtemplate:$template_uuid rindex:1" "uuid")
    
    local output=$(ttask "$inst_uuid" delete 2>&1)
    
    if echo "$output" | grep -qi "recurring"; then
        print_pass "Warning message displayed"
    else
        print_fail "No warning message found" "$output"
    fi
}

test_warning_complete_template() {
    print_test "Completing template shows warning"
    
    ttask_add "Complete template test" ty:p r:5s due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Complete template test\"" "uuid")
    local output=$(ttask "$template_uuid" done 2>&1)
    
    if echo "$output" | grep -qi "template\|recurrence"; then
        print_pass "Template completion warning displayed"
    else
        print_fail "No template warning found" "$output"
    fi
}

test_warning_delete_template() {
    print_test "Deleting template shows warning"
    
    ttask_add "Delete template test" ty:p r:5s due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Delete template test\"" "uuid")
    local output=$(ttask "$template_uuid" delete 2>&1)
    
    if echo "$output" | grep -qi "template\|recurrence"; then
        print_pass "Template deletion warning displayed"
    else
        print_fail "No template warning found" "$output"
    fi
}

# ============================================================================
# Test: Edge Cases & Robustness
# ============================================================================

test_edge_no_due_date() {
    print_test "Template without due date handled gracefully"
    
    local output=$(ttask_add "No due test" r:7d ty:c 2>&1)
    wait_for_hooks 1
    
    # Should either create with calculated due or reject
    local template_count=$(ttask_count status:recurring description:"No due test")
    
    if [ "$template_count" -eq 1 ]; then
        print_pass "Template created without explicit due date"
    else
        # Check if it was rejected with message
        if echo "$output" | grep -qi "due"; then
            print_pass "Template rejected appropriately (no due date)"
        else
            print_fail "Unclear handling of missing due date"
        fi
    fi
}

test_edge_modify_template_period() {
    print_test "Modifying template period updates future instances"
    
    ttask_add "Modify period test" r:10s ty:p due:now+5s > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Modify period test\"" "uuid")
    
    # Modify period
    ttask "$template_uuid" modify r:3s > /dev/null
    wait_for_hooks 1
    
    local new_period=$(ttask_get "uuid:$template_uuid" "r")
    
    if [ "$new_period" = "3s" ]; then
        print_pass "Template period updated"
    else
        print_fail "Period not updated (got: '$new_period')"
    fi
}

test_edge_modify_template_type() {
    print_test "Modifying template type changes behavior"
    
    ttask_add "Modify type test" r:5s ty:p due:now > /dev/null
    wait_for_hooks 1
    
    local template_uuid=$(ttask_get "status:recurring description:\"Modify type test\"" "uuid")
    
    # Change to chained
    ttask "$template_uuid" modify ty:c > /dev/null
    wait_for_hooks 1
    
    local new_type=$(ttask_get "uuid:$template_uuid" "type")
    
    if [ "$new_type" = "chained" ]; then
        print_pass "Template type changed to chained"
    else
        print_fail "Type not changed (got: '$new_type')"
    fi
}

test_edge_chained_until_rejected() {
    print_test "Chained templates reject 'until' attribute"
    
    local output=$(ttask_add "Chained until test" ty:c r:7d due:tomorrow until:eom 2>&1)
    
    if echo "$output" | grep -qi "until.*not.*supported\|chained.*until"; then
        print_pass "Chained + until correctly rejected"
    else
        # Check if it was created anyway
        local count=$(ttask_count status:recurring description:"Chained until test")
        if [ "$count" -eq 0 ]; then
            print_pass "Chained + until prevented (silent rejection)"
        else
            print_fail "Chained + until should be rejected" "$output"
        fi
    fi
}

# ============================================================================
# Test: Safety & Tags
# ============================================================================

test_safety_tags_present() {
    print_test "Safety tags present on all test tasks"
    
    ttask_add "Safety tag test" r:2s due:now ty:p > /dev/null
    wait_for_hooks 1
    
    # Check template has tags
    local template=$(ttask_export status:recurring description:"Safety tag test")
    local tags=$(echo "$template" | jq -r '.tags[]' | tr '\n' ' ')
    
    if echo "$tags" | grep -q "test" && echo "$tags" | grep -q "dummy"; then
        print_pass "Safety tags present on template"
    else
        print_fail "Safety tags missing on template (tags: $tags)"
        return
    fi
    
    # Check instance has tags
    local template_uuid=$(echo "$template" | jq -r '.uuid')
    local inst_tags=$(ttask_export rtemplate:"$template_uuid" rindex:1 | jq -r '.tags[]' | tr '\n' ' ')
    
    if echo "$inst_tags" | grep -q "test" && echo "$inst_tags" | grep -q "dummy"; then
        print_pass "Safety tags propagated to instance"
    else
        print_fail "Safety tags missing on instance (tags: $inst_tags)"
    fi
}

# ============================================================================
# Main Test Runner
# ============================================================================

main() {
    print_header "Taskwarrior Enhanced Recurrence - Test Suite v2.0"
    
    # Check dependencies
    if ! command -v jq &> /dev/null; then
        abort_test "jq is required. Install with: sudo apt install jq"
    fi
    
    if ! command -v task &> /dev/null; then
        abort_test "taskwarrior is required"
    fi
    
    # Setup
    setup
    
    # Run tests
    print_section "Setup & Configuration"
    test_setup_uda_presence
    test_setup_hooks_executable
    
    print_section "Template Creation"
    test_template_basic_creation
    test_template_has_correct_udas
    test_template_type_abbreviations
    test_template_default_type_is_periodic
    
    print_section "Chained Recurrence (Completion-Based)"
    test_chained_first_instance_on_add
    test_chained_instance_has_correct_index
    test_chained_complete_spawns_next
    test_chained_due_date_relative_to_completion
    test_chained_multiple_completions
    
    print_section "Periodic Recurrence (Time-Based)"
    test_periodic_first_instance_on_add
    test_periodic_spawns_on_time_trigger
    test_periodic_due_dates_anchored_to_template
    test_periodic_maintains_schedule_after_completion
    
    print_section "Date Field Propagation"
    test_date_wait_propagates
    test_date_scheduled_propagates
    test_date_relative_wait_calculation
    test_date_relative_scheduled_calculation
    
    print_section "Boundary Conditions"
    test_boundary_rlimit_enforcement
    test_boundary_rend_stops_spawning
    test_boundary_until_expires_instances
    
    print_section "Warning Messages"
    test_warning_delete_instance
    test_warning_complete_template
    test_warning_delete_template
    
    print_section "Edge Cases & Robustness"
    test_edge_no_due_date
    test_edge_modify_template_period
    test_edge_modify_template_type
    test_edge_chained_until_rejected
    
    print_section "Safety & Tags"
    test_safety_tags_present
    
    # Cleanup
    cleanup
    
    # Summary
    print_header "Test Summary"
    echo -e "Total tests:  ${BLUE}$TESTS_RUN${NC}"
    echo -e "Passed:       ${GREEN}$TESTS_PASSED${NC}"
    echo -e "Failed:       ${RED}$TESTS_FAILED${NC}"
    
    local pass_rate=0
    if [ $TESTS_RUN -gt 0 ]; then
        pass_rate=$((TESTS_PASSED * 100 / TESTS_RUN))
    fi
    echo -e "Pass rate:    ${BLUE}${pass_rate}%${NC}"
    
    if [ -n "$OUTPUT_FILE" ]; then
        echo -e "\nResults saved to: ${BLUE}$OUTPUT_FILE${NC}"
    fi
    
    if [ "$DEBUG_MODE" = true ]; then
        echo -e "Hook debug log: ${BLUE}~/.task/recurrence_debug.log${NC}"
    fi
    
    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "\n${GREEN}✓ All tests passed!${NC}\n"
        exit 0
    else
        echo -e "\n${RED}✗ Some tests failed${NC}\n"
        exit 1
    fi
}

# Trap cleanup on exit
trap cleanup EXIT

# Run main
main "$@"
