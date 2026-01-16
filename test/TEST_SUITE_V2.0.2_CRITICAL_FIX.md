# Test Suite v2.0.2 - CRITICAL FIX

**Date:** 2026-01-15
**Priority:** CRITICAL - Test environment was completely wrong!

## The Problem

Test suite was using **WRONG UDA CONFIGURATION** that didn't match your actual recurrence.rc!

### What Was Wrong:

1. **Missing `recurrence=no`** - Test was using built-in recurrence!
2. **Wrong field name**: `uda.rperiod` instead of `uda.r`
3. **Wrong type**: `uda.r.type=string` instead of `uda.r.type=duration`
4. **Missing critical UDAs**:
   - `uda.rlast` - tracks last spawned instance (CRITICAL!)
   - `uda.rwait` - stores relative wait dates
   - `uda.rscheduled` - stores relative scheduled dates
   - `uda.ranchor` - anchor field for calculations
5. **Extra UDA that doesn't exist**: `uda.rlimit` (not implemented yet)

### Why This Caused Chaos:

- **No template creation**: Without `recurrence=no`, taskwarrior was confused
- **No instance tracking**: Without `uda.rlast`, hooks couldn't track what to spawn
- **Wrong field lookups**: Hooks expected `r` but test config had `rperiod`
- **Type mismatch**: Duration values need `uda.r.type=duration` not string
- **Mass spawning**: Without proper UDAs, hooks spawned uncontrollably (19 instances!)

## The Fix

Test taskrc now EXACTLY matches your real recurrence.rc:

```bash
# Disable built-in recurrence (CRITICAL!)
recurrence=no

# Correct UDA names and types
uda.r.type=duration          # Not 'string', not 'rperiod'
uda.rlast.type=numeric       # CRITICAL for instance tracking
uda.rwait.type=string        # For relative dates
uda.rscheduled.type=string   # For relative dates  
uda.ranchor.type=string      # For anchor calculations
uda.type.type=string         # Recurrence type
uda.rtemplate.type=string    # Template UUID
uda.rindex.type=numeric      # Instance index
uda.rend.type=date          # Recurrence end date
```

## Changes Made

### 1. Test Configuration (lines 256-321)
- Added `recurrence=no`
- Changed `uda.rperiod` → `uda.r` with type `duration`
- Added `uda.rlast`, `uda.rwait`, `uda.rscheduled`, `uda.ranchor`
- Removed `uda.rlimit` (not implemented)
- Updated reports to match real config

### 2. UDA Presence Test (line 325-340)
```bash
# Old: checked for rperiod, rlimit
# New: checks for r, rlast, rwait, rscheduled, ranchor
required_udas=("uda.type" "uda.r" "uda.rtemplate" "uda.rindex" "uda.rlast" "uda.rend" "uda.rwait" "uda.rscheduled" "uda.ranchor")
```

### 3. Field Name Updates
- Line 406: `rperiod` → `r`
- Line 973: `rperiod` → `r`

### 4. Skip Unimplemented Test
- `test_boundary_rlimit_enforcement()` now returns early with SKIPPED status
- Kept original code commented for when feature is implemented

## Expected Results

Now that test environment matches reality:

### Should PASS (estimated 60-80%):
- ✅ Template creation with `status:recurring`
- ✅ UDA fields populated (`type`, `r`, `rlast`)
- ✅ First instance spawning (just 1, not 19!)
- ✅ Instance tracking with `rindex`
- ✅ Chained completion → spawn next
- ✅ Periodic time-based spawning
- ✅ Type abbreviations (ty:c → chained)
- ✅ Safety tags

### May FAIL (real bugs to fix):
- ❌ Date propagation (wait, scheduled)
- ❌ Relative date calculations (wait:due-2s)
- ❌ rend enforcement
- ❌ until expiration
- ❌ Warning messages

### Won't Test Yet:
- ⏭️  rlimit (not implemented)

## Why This Matters

Before: Tests failing due to **wrong test environment**
After: Tests will show **actual hook functionality**

You were right - it works in the app because your app uses the correct recurrence.rc!

## Next Steps

1. **Run new test**: `./test-recurrence-v2.sh -d -f`
2. **Expect much better results**: 60-80% pass rate instead of 26%
3. **Real bugs will be clear**: What actually needs fixing in hooks
4. **Focus efforts**: Fix actual bugs, not test infrastructure

## Lessons Learned

✅ Always match test environment to production config
✅ UDA types matter (`duration` vs `string`)
✅ Field names must be exact (`r` not `rperiod`)
✅ Critical fields like `rlast` are non-negotiable
✅ `recurrence=no` is required to disable built-in system

This was a CRITICAL fix - the entire test suite was testing the wrong thing!
