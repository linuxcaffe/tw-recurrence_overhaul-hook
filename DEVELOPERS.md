# Test Script v0.3.2 - Bug Fixes

## Summary of Changes

Based on the test results from your v0.5.2 hooks, I've fixed three critical issues in the test script.

## Issues Fixed

### 1. Test Looking for Wrong Message (Line 18 failure)
**Problem:** Test was checking for "Created instance #1" message in output, but hooks don't output that message.

**Fix:** Changed to check actual task count instead:
```bash
# Before: Check for message in output
if echo "$output" | grep -q "Created instance #1"; then

# After: Check actual instance count
local instance_count=$(ttask count rtemplate.any: status:pending 2>/dev/null)
if [ "$instance_count" -ge 1 ]; then
```

**Result:** Test now correctly detects when instances are created.

---

### 2. Bash Syntax Error (Line 43/445 error)
**Problem:** `[: : integer expression expected` when `$count` is empty/null

```bash
local count=$(ttask_export +RECURRING | jq '. | length' 2>/dev/null)
if [ "$count" -ge 1 ]; then  # FAILS when count is empty!
```

**Fix:** Handle empty/null values:
```bash
local count=$(ttask_export +RECURRING | jq '. | length' 2>/dev/null)

# Handle empty/null count
if [ -z "$count" ]; then
    count=0
fi

if [ "$count" -ge 1 ]; then  # Now safe!
```

**Result:** No more bash errors, test handles edge cases properly.

---

### 3. Test Counting All Instances Instead of Specific Ones (Line 34: got 26!)
**Problem:** rlimit test was finding ALL instances in database, not just its own

```bash
# Before: Get last template (could be from ANY previous test)
local template_uuid=$(ttask_export status:recurring | jq -r '.[-1].uuid' 2>/dev/null)
```

This was getting templates from previous tests, leading to counting 26 instances!

**Fix:** Find the specific template by description:
```bash
# After: Get OUR template specifically
local template_uuid=$(ttask_export status:recurring description:"Pile test" | jq -r '.[0].uuid' 2>/dev/null)

if [ -z "$template_uuid" ] || [ "$template_uuid" = "null" ]; then
    print_fail "Could not find template"
    return
fi
```

**Result:** Test now only counts instances from its own template.

---

## Test Results Comparison

### Before (v0.3.1):
```
Total tests:  14
Passed:       5
Failed:       10  (includes bash error)
```

### Expected After (v0.3.2):
```
Total tests:  14
Passed:       8-10 (expecting improvement)
Failed:       4-6
```

### Tests That Should Now Pass:
1. ✅ Basic template creation - "First instance created"
2. ✅ +RECURRING tag test - no more bash error
3. ✅ rlimit test - will count correct instances

### Tests Still Expected to Fail (Known Limitations):
1. ❌ "Chained + until should be rejected" - validation not implemented yet
2. ❌ "Instance until not preserved" - feature may need work
3. ❌ "Periodic deletion spawned" - behavior needs investigation
4. ❌ "Template ranchor is empty" - scheduled anchor test
5. ❌ "Wait date not set" - relative wait dates
6. ❌ "Template period not updated" - template modification

These remaining failures are actual feature issues, not test bugs.

---

## Version Updates

**test-recurrence.sh**: v0.3.1 → v0.3.2
- Fixed instance detection logic
- Fixed bash syntax error
- Fixed template isolation in tests
- Date: 2026-01-13

---

## Testing Instructions

```bash
cd ~/.task/hooks/recurrence
./test-recurrence.sh -f
```

Expected improvements:
- No bash errors
- "First instance created" should PASS
- "+RECURRING tag" test should complete (may still fail but won't error)
- "rlimit" test should show correct counts

---

## Remaining Work

The test suite is now more reliable, but there are still real feature issues to address:

1. **Validation:** Implement chained + until rejection
2. **Until preservation:** Ensure instances get template until dates
3. **Scheduled anchor:** Fix ranchor:scheduled handling
4. **Relative wait:** Debug rwait date calculation
5. **Template mods:** Ensure template changes propagate

These are hook functionality issues, not test script bugs.

---

## Files Changed

- test-recurrence.sh (v0.3.2)
  - test_basic_template_creation()
  - test_recurring_tag_applied()
  - test_rlimit_pile_up()
