## One-to-One Rule Enforcement - Complete Implementation

### Version: 0.4.0
### Date: 2026-02-02

---

## The One-to-One Rule

**Every active template MUST have exactly one pending instance at all times.**

```
Template (status:recurring) ←→ Instance (status:pending)
        1                   :                   1
```

This is the fundamental invariant of the recurrence system:
- `template.rlast` ↔ `instance.rindex` must ALWAYS match
- There can be only ONE! ⚡

---

## Implementation Architecture

### On-Add/On-Modify Hook (Validation)
**Role:** Detect violations and warn
**Actions:**
- Query instances when template/instance is modified
- Count instances: 0, 1, or >1
- Provide comprehensive error messages
- Note that on-exit will fix violations

### On-Exit Hook (Enforcement)
**Role:** Fix violations proactively
**Actions:**
- Check ALL active templates (every invocation)
- Spawn missing instances (0 found)
- Error comprehensively on multiple instances (>1 found)
- Sync rindex/rlast mismatches (1 found but desynced)

---

## Error Conditions and Responses

### Condition 1: No Instance Exists (0 instances)

**Detected in on-add/on-modify:**
```
ERROR: No pending instance exists (violates one-to-one rule)
  Expected: Exactly 1 instance with rindex=0
  Found: 0 instances
  Fix: On-exit hook will spawn instance #5 on next task command
```

**Fixed in on-exit:**
```
[ONE-TO-ONE] Created instance 5 of 'Weekly review'
```

**What happens:**
1. User modifies template rlast
2. on-add/on-modify detects no instance exists
3. Warns user that on-exit will spawn
4. Command completes
5. on-exit runs, checks all templates
6. Finds template with 0 instances
7. Spawns instance with rindex=rlast
8. User sees instance appear

---

### Condition 2: Multiple Instances Exist (>1 instances)

**Detected in on-add/on-modify:**
```
ERROR: Multiple instances exist (violates one-to-one rule - DATA CORRUPTION)
  Expected: Exactly 1 instance
  Found: 3 instances: task 42 (rindex=3), task 43 (rindex=5), task 44 (rindex=7)
  This indicates a serious bug or external data corruption.
  Manual fix required:
    1. Decide which instance to keep (usually the one with rindex=5)
    2. Delete the others: task <id> delete
    3. Ensure remaining instance has rindex matching template rlast=5
  Or delete all and let on-exit spawn fresh: task 42 43 44 delete
```

**Detected in on-exit:**
```
[ONE-TO-ONE ERROR] Template 1 -- Weekly review has 3 instances!
  Expected: Exactly 1 instance
  Found: task 42 (rindex=3), task 43 (rindex=5), task 44 (rindex=7)
  This is DATA CORRUPTION - manual fix required:
    1. Decide which instance to keep (usually the one with rindex=5)
    2. Delete others: task <id> delete
  Or delete all and let on-exit spawn fresh: task 42 43 44 delete
```

**What happens:**
1. Corruption detected (multiple instances)
2. System errors loudly - cannot auto-fix
3. User must manually decide which to keep
4. User deletes unwanted instances
5. Next command, on-exit validates and syncs remaining instance

**Why not auto-fix?**
- Can't know which instance is "correct"
- User might have work in multiple instances
- Could lose data by auto-deleting
- Better to error and let user decide

---

### Condition 3: Desync (1 instance, but rindex ≠ rlast)

**Detected in on-add/on-modify:**
```
WARNING: Detected desync - instance rindex=3 but template rlast=5
  Auto-fixing: Template rlast will be updated to 7
```

**Fixed in on-exit:**
```
[ONE-TO-ONE] Synced task 42 -- Weekly review: rindex 3 → 5
```

**What happens:**
1. on-add/on-modify detects and fixes immediately
2. on-exit double-checks and fixes if needed
3. System self-heals automatically

---

## Test Scenarios

### Test 1: Normal Operation (Should NOT trigger)

```bash
# Create template
task add "Weekly review" due:friday r:1w

# Wait for instance to spawn or trigger manually
task export >/dev/null

# Verify one-to-one
task 1 export | jq '.[] | {rlast}'    # Should show: "0"
task 2 export | jq '.[] | {rindex}'   # Should show: "0"
```

**Expected output:**
- Template exists with rlast=0
- Instance exists with rindex=0
- No error messages from on-exit

---

### Test 2: Missing Instance (Spawn)

```bash
# Create template
task add "Daily standup" due:today r:1d

# Delete the instance (simulate missing instance)
task 2 delete

# Trigger on-exit
task export >/dev/null
```

**Expected output:**
```
[ONE-TO-ONE] Created instance 0 of 'Daily standup'
```

**Verification:**
```bash
task rtemplate:<UUID> status:pending export | jq length
# Should show: 1
```

---

### Test 3: Template rlast Change (Sync)

```bash
# Create template with instance
task add "Weekly report" due:friday r:1w
task export >/dev/null  # Spawn instance

# Change template rlast
task 1 mod rlast:5
```

**Expected output:**
```
Template rlast modified: 0 → 5 (5 instances forward)
  Next instance will be #6 due 20260307T000000Z
  Instance #0 (task 2) rindex auto-synced to 5.
```

**Verification:**
```bash
task 1 export | jq '.[] | {rlast}'    # Should show: "5"
task 2 export | jq '.[] | {rindex}'   # Should show: "5"
```

---

### Test 4: Simulate Corruption (Multiple Instances)

```bash
# Create template with instance
task add "Test" due:today r:1d
task export >/dev/null

# Manually create duplicate instances (simulating corruption)
task add "Test" rtemplate:<UUID> rindex:1
task add "Test" rtemplate:<UUID> rindex:2

# Trigger one-to-one check
task export >/dev/null
```

**Expected output:**
```
[ONE-TO-ONE ERROR] Template 1 -- Test has 3 instances!
  Expected: Exactly 1 instance
  Found: task 2 (rindex=0), task 3 (rindex=1), task 4 (rindex=2)
  This is DATA CORRUPTION - manual fix required:
    1. Decide which instance to keep (usually the one with rindex=0)
    2. Delete others: task <id> delete
  Or delete all and let on-exit spawn fresh: task 2 3 4 delete
```

**Manual fix:**
```bash
# Keep instance with correct rindex, delete others
task 3 4 delete

# Verify
task export >/dev/null  # Should show no errors now
```

---

### Test 5: Instance rindex Change (Reverse Sync)

```bash
# Create template with instance
task add "Gym" due:today r:1d
task export >/dev/null

# Change instance rindex
task 2 mod rindex:10
```

**Expected output:**
```
Modified instance rindex: 0 → 10
  Template rlast auto-synced to 10.
```

**Verification:**
```bash
task 1 export | jq '.[] | {rlast}'    # Should show: "10"
task 2 export | jq '.[] | {rindex}'   # Should show: "10"
```

---

## Performance Considerations

### Cost of Option C (Check Everything)

On-exit hook checks ALL templates on EVERY invocation:
- Query all templates: `task status:recurring export`
- For each template, query instances: `task rtemplate:<UUID> status:pending export`

**Typical performance:**
- 1-10 templates: ~50-100ms overhead
- 11-50 templates: ~100-300ms overhead
- 51+ templates: ~300ms+ overhead

**Is this acceptable?**
- Most users have <10 recurring tasks
- Overhead is negligible on modern systems
- Self-healing benefits outweigh cost
- Ensures system integrity at all times

**If performance becomes an issue:**
- Could add flag file optimization later
- Could check only modified templates
- Current implementation prioritizes correctness

---

## Debug Mode

Enable comprehensive logging:
```bash
export DEBUG_RECURRENCE=1
task <any command>
tail -f ~/.task/recurrence_debug.log
```

**Look for:**
```
[timestamp] EXIT: Starting one-to-one rule enforcement
[timestamp] EXIT: Found 5 active templates to check
[timestamp] EXIT: Checking template 1: Weekly review, rlast=0
[timestamp] EXIT:   Found 1 pending instance(s)
[timestamp] EXIT:   OK: instance #0 in sync
[timestamp] EXIT: Checking template 2: Daily standup, rlast=3
[timestamp] EXIT:   ERROR: No instance found, spawning instance #3
[timestamp] EXIT:   Spawned: Created instance 3 of 'Daily standup'
[timestamp] EXIT: One-to-one enforcement complete, 1 issues found/fixed
```

---

## Integration Points

### Files Modified

**on-add_recurrence.py** (v0.4.0):
- Added one-to-one validation in `handle_template_modification()`
- Added multiple instance detection in `handle_instance_modification()`
- Comprehensive error messages for all violation conditions

**on-exit_recurrence.py** (v0.4.0):
- Added `enforce_one_to_one_rule()` function
- Checks all templates every invocation
- Spawns missing instances
- Syncs desynced instances
- Errors on multiple instances

**Both hooks:**
- Use `query_instances()` helper
- Follow same error message format
- Share debug logging via recurrence_common_hook

---

## Expected Behavior Summary

| Condition | On-Add/On-Modify | On-Exit |
|-----------|------------------|---------|
| 0 instances | Warn + note fix pending | **Spawn instance** |
| 1 instance, synced | ✓ Normal | ✓ Normal |
| 1 instance, desynced | **Auto-sync** | **Auto-sync** |
| 2+ instances | **Error comprehensively** | **Error comprehensively** |

**Key principle:** 
- on-add/on-modify validates and warns
- on-exit enforces and fixes

---

## Installation

```bash
# Copy updated hooks
cp on-add_recurrence.py ~/.task/hooks/
cp on-exit_recurrence.py ~/.task/hooks/
cp recurrence_common_hook.py ~/.task/hooks/

# Ensure executable
chmod +x ~/.task/hooks/on-add_recurrence.py
chmod +x ~/.task/hooks/on-exit_recurrence.py

# Create on-modify symlink
cd ~/.task/hooks
ln -sf on-add_recurrence.py on-modify_recurrence.py

# Test
export DEBUG_RECURRENCE=1
task add "Test" due:tomorrow r:1d
tail -f ~/.task/recurrence_debug.log
```

---

## Common Issues

### Issue: "on-exit spawning instances every time"

**Cause:** Template exists but instance keeps getting deleted/completed
**Debug:** Check if on-modify is properly handling instance completion
**Fix:** Verify on-exit spawning logic

### Issue: "Multiple instances appearing"

**Cause:** Bug in on-exit spawning, or external tool creating instances
**Debug:** Check debug log for spawning calls
**Fix:** Delete extras manually, system will stabilize

### Issue: "Template and instance constantly desyncing"

**Cause:** External modifications bypassing hooks
**Debug:** Check who/what is modifying tasks
**Fix:** Ensure all modifications go through hooks (don't use rc.hooks=off in user commands)

---

## Future Enhancements

Potential improvements:
1. Flag file optimization (only check on errors)
2. Batch spawning (spawn multiple instances at once)
3. Corruption repair suggestions (which instance to keep)
4. Performance metrics (track enforcement time)
5. Configurable enforcement (opt-in/opt-out)

Current implementation prioritizes correctness and simplicity over optimization.
