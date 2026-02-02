## Re-Spawn Implementation - Delete + Create with Correct Dates

### Version: 0.4.0 (Re-Spawn Fix)
### Date: 2026-02-02

---

## The Problem We Fixed

### What Was Wrong:
When modifying template `rlast`, we were just updating the instance's `rindex` field:
```python
# WRONG - just renamed the instance
instance.rindex = 1 → 3  # Changed number but dates stay wrong!
```

**Why this was broken:**
- Instance #1 dates: calculated from `anchor + (r × 0)`
- Instance #3 dates: should be `anchor + (r × 3)`
- Just changing rindex doesn't recalculate dates!

### What We Do Now:
```python
# RIGHT - delete old, spawn new with correct dates
delete_instance(old_instance)
spawn_instance(template, new_rlast)  # Recalculates all dates!
```

---

## Architecture: Shared Spawning Logic

### recurrence_common_hook.py - Central Functions

```python
def spawn_instance(template, rindex, completion_time=None):
    """Spawn instance with correctly calculated dates
    
    Can be called from:
    - on-exit: Normal spawning when instances complete
    - on-modify: Re-spawning when rlast changes
    """
    # Calculate dates based on rindex and type
    if rindex == 0:
        anchor_date = template_anchor
    else:
        if type == 'chain':
            anchor_date = completion_time + recur_delta
        else:  # period
            anchor_date = template_anchor + (recur_delta × rindex)
    
    # Create task with calculated dates
    # Update template rlast to match

def delete_instance(instance_uuid, instance_id=None):
    """Delete an instance"""
    task rc.hooks=off delete {uuid}
```

---

## The Re-Spawn Flow

### User Action:
```bash
task 71 mod rlast:3
```

### Template Modification (on-modify):
```
1. Template rlast: 1 → 3
2. Check instances: Found 1 instance (#1)
3. DELETE instance #1
4. SPAWN instance #3 with recalculated dates:
   - due: anchor + (r × 3)
   - wait: due + rwait offset
   - scheduled: due + rscheduled offset
5. Template rlast set to 3
```

### Result:
```
Modified task 71 -- test recurrence period (recurrence template)
Template rlast modified: 1 → 3 (2 instances forward)
  Next instance will be #4 due 20260204T102044Z
  Instance #1 (task 72) deleted and re-spawned as #3
  Created instance 3 of 'test recurrence period'
```

---

## Instance Completion Flow

### User Action:
```bash
task 72 done  # Completes instance #3
```

### Instance Completion (on-exit):
```
1. Instance #3 completed
2. Template rlast = 3
3. current_idx (3) >= last_idx (3) ✓
4. SPAWN instance #4:
   - Calculate: anchor + (r × 4)
   - Create task
   - Update template rlast to 4
```

### Result:
```
Completed task 72 -- test recurrence period (instance #3)
  Template: task 71
Created instance 4 of 'test recurrence period'
```

---

## Date Calculation Examples

### Template:
```
due: 2026-02-01T10:20:00Z
r: 1d
type: period
```

### Instances:
```
Instance #0: 2026-02-01T10:20:00Z (anchor + 0)
Instance #1: 2026-02-02T10:20:00Z (anchor + 1d)
Instance #2: 2026-02-03T10:20:00Z (anchor + 2d)
Instance #3: 2026-02-04T10:20:00Z (anchor + 3d)
```

### Time Machine (rlast: 0 → 3):
```
OLD instance #0: due 2026-02-01 (WRONG for #3!)
  ↓ DELETE + RE-SPAWN
NEW instance #3: due 2026-02-04 (CORRECT!)
```

---

## Key Files Changed

### recurrence_common_hook.py
**Added:**
- `spawn_instance(template, rindex, completion_time)` - Universal spawning
- `delete_instance(instance_uuid, instance_id)` - Instance deletion

**Features:**
- Handles both period and chain types
- Calculates dates based on rindex
- Processes relative wait/scheduled
- Copies template attributes
- Updates template rlast
- Full debug logging

### on-add_recurrence.py
**Changed:**
- Import `spawn_instance` and `delete_instance`
- On rlast change:
  - Delete old instance
  - Re-spawn with new rindex
  - Recalculate all dates

### on-exit_recurrence.py
**Changed:**
- Import `spawn_instance`
- Use common `spawn_instance` instead of local `create_instance`
- Maintains backward compatibility with fallback

---

## Test Scenarios

### Test 1: Time Machine Forward
```bash
# Create template
task add "Daily standup" due:today r:1d
# Instance #0 created with due:today

# Jump forward
task 1 mod rlast:5
# Instance #0 deleted
# Instance #5 created with due:today+5d
```

**Verification:**
```bash
task 1 export | jq '.[] | {rlast}'  # Should be "5"
task 2 export | jq '.[] | {rindex, due}'
# Should be: rindex:"5", due:"2026-02-07..."
```

### Test 2: Time Machine with Wait
```bash
# Create with wait
task add "Bill" due:2026-03-01 r:1mo rwait:due-7d
# Instance #0: due:2026-03-01, wait:2026-02-23

# Jump to instance #3
task 1 mod rlast:3
# Instance #3: due:2026-06-01, wait:2026-05-25
```

**Verification:**
```bash
task 2 export | jq '.[] | {rindex, due, wait}'
# due should be 3 months later
# wait should be due-7d
```

### Test 3: Complete and Spawn Next
```bash
# With rlast:3, instance #3 exists
task 2 done

# Should spawn instance #4
```

**Expected:**
```
Completed task 2 -- Daily standup (instance #3)
  Template: task 1
Created instance 4 of 'Daily standup'
```

### Test 4: Chain Type
```bash
# Create chain
task add "Workout" due:today r:1d type:chain

# Complete instance
task 2 done
# Next instance spawns from completion_time + 1d
```

---

## Debug Output

Enable debugging:
```bash
export DEBUG_RECURRENCE=1
task 1 mod rlast:5
tail -f ~/.task/recurrence_debug.log
```

**Look for:**
```
[timestamp] ADD/MOD: Deleting old instance #0 and re-spawning as #5
[timestamp] COMMON: Deleting instance 2
[timestamp] COMMON: Instance 2 deleted successfully
[timestamp] COMMON: Spawning instance 5 from template {uuid}
[timestamp] COMMON: Instance 5 spawned successfully
```

---

## Benefits of Shared Spawning

✅ **Single source of truth** - One function handles all spawning
✅ **Consistent date calculation** - Same logic everywhere
✅ **No duplication** - on-exit and on-modify use same code
✅ **Easier maintenance** - Fix bugs in one place
✅ **Correct re-spawning** - Dates recalculated properly

---

## Installation

```bash
# Copy all three files
cp recurrence_common_hook.py ~/.task/hooks/
cp on-add_recurrence.py ~/.task/hooks/
cp on-exit_recurrence.py ~/.task/hooks/

# Ensure executable
chmod +x ~/.task/hooks/on-add_recurrence.py
chmod +x ~/.task/hooks/on-exit_recurrence.py

# Verify symlink
cd ~/.task/hooks
ln -sf on-add_recurrence.py on-modify_recurrence.py

# Test re-spawning
task add "Test" due:today r:1d
task 1 mod rlast:5
task list  # Should show instance #5 with correct date
```

---

## Summary

The system now properly handles rlast modifications by:
1. ✅ Deleting the old instance
2. ✅ Re-spawning with correct rindex
3. ✅ Recalculating all dates based on new rindex
4. ✅ Using shared spawn_instance function
5. ✅ Maintaining one-to-one invariant

**No more wrong dates when time-machining!** ⚡
