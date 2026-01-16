# Test Suite v2.0 - Summary

**Created:** 2026-01-15
**Purpose:** Comprehensive testing of recurrencae features that SHOULD be working

## What's New

### Complete Rewrite
- Clean, organized structure with logical test categories
- Self-contained tests (each sets up its own data)
- Explicit wait controls instead of universal sleeps
- Better failure diagnostics with debug mode
- Pass rate calculation in summary

### Test Coverage (36 tests total)

#### 1. Setup & Configuration (2 tests)
- UDA presence validation
- Hook executability check

#### 2. Template Creation (4 tests)
- Basic template creation with recurrence
- UDA values set correctly
- Type abbreviation normalization (c, ch, chai, p, pe, etc.)
- Default type is periodic

#### 3. Chained Recurrence (5 tests)
- First instance spawns on template creation
- Instance has correct rindex
- Completing instance spawns next
- Due date relative to completion time
- Multiple completions create proper chain

#### 4. Periodic Recurrence (4 tests)
- First instance spawns on template creation
- New instances spawn when period elapses
- Due dates anchored to template (not completion)
- Schedule maintained regardless of completion time

#### 5. Date Field Propagation (4 tests)
- Wait date propagates to instances
- Scheduled date propagates to instances
- Relative wait calculation (wait:due-2s)
- Relative scheduled calculation (scheduled:due-1s)

#### 6. Boundary Conditions (3 tests)
- rlimit enforcement (pile-up control)
- rend stops spawning new instances
- until expires pending instances (periodic only)

#### 7. Warning Messages (3 tests)
- Delete instance warning
- Complete template warning
- Delete template warning

#### 8. Edge Cases & Robustness (4 tests)
- Template without due date
- Modify template period
- Modify template type
- Chained + until rejection

#### 9. Safety & Tags (1 test)
- Safety tags present on templates and instances

## Key Improvements

### Better Organization
```
Old: Mixed feature tests that tried to do too much
New: One test = one assertion, clear naming
```

### Explicit Timing
```
Old: sleep everywhere, unpredictable
New: wait_for_hooks() with explicit durations only where needed
```

### Debug Support
```bash
./test-recurrence-v2.sh -d     # Enable debug mode
# Shows hook execution details, timing info, JSON data
```

### Better Output
```
Old: Hard to read with mixed pass/fail
New: Organized sections with colors:
  - Section headers in CYAN
  - Test names in YELLOW
  - Pass/Fail clearly marked
  - Pass rate calculated
```

### Self-Contained Tests
```
Old: Tests depended on previous state
New: Each test creates its own template/instances
```

## Usage

```bash
# Run to terminal
./test-recurrence-v2.sh

# Save to auto-dated file
./test-recurrence-v2.sh -f

# Save to specific file
./test-recurrence-v2.sh -f mytest.txt

# Debug mode
./test-recurrence-v2.sh -d

# Debug + save
./test-recurrence-v2.sh -d -f
```

## What's Tested

Based on the README and feature spec, testing:
- ✅ Template creation with all UDAs
- ✅ Type abbreviations (c/ch/chai/chain/chained, p/pe/per/periodic)
- ✅ Chained recurrence (completion-based)
- ✅ Periodic recurrence (time-based)
- ✅ Date field propagation (wait, scheduled)
- ✅ Relative date calculations (wait:due-7d, scheduled:due-2s)
- ✅ Boundary enforcement (rlimit, rend, until)
- ✅ Warning messages for template/instance operations
- ✅ Template modification (period, type)
- ✅ Edge cases (no due date, chained+until rejection)
- ✅ Safety tag propagation

## Expected Results

Some features may not be fully implemented yet:
- Relative date calculations might fail (wait:due-7d parsing)
- Until expiration might not be implemented
- Some warning messages might be missing
- Template modification might need work

The test suite will show exactly which features work and which need attention.

## Next Steps

1. Run the test suite: `./test-recurrence-v2.sh -f`
2. Review failures to identify what needs fixing
3. Focus on high-priority failures first:
   - Template creation (critical)
   - Basic chained/periodic spawning (critical)
   - Date propagation (important)
   - Relative dates (nice to have)

## Notes

- All tests use 2-5 second periods for speed
- Safety tags required on all test tasks
- Triple-layer isolation (env, dir, tags)
- Tests clean up automatically on exit
- Debug mode logs to hook debug files
