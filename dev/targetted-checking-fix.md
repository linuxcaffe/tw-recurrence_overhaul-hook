## Targeted One-to-One Checking - Fixed Implementation

### Version: 0.4.0 (Corrected)
### Date: 2026-02-02

---

## What Was Wrong with Option C

**The Fatal Flaw:**
```python
# BAD: on-exit checked ALL templates on EVERY invocation
for all_templates in get_all_templates():
    check_instances(template)  # AFFECTS UNRELATED TASKS!
```

**What happened:**
- User deletes instance for template A
- on-exit runs and checks templates A, B, C, D, E, F...
- Finds that template B has a waiting instance (status:waiting not status:pending)
- SPAWNS A NEW INSTANCE for template B
- Now template B has 2 instances (corruption!)
- **Massive violation of isolation principle**

---

## The New Approach: Targeted Checking Only

### Core Principle
**ONLY check the specific template/instance being modified. NEVER touch other templates.**

### Implementation

#### recurrence_common_hook.py - Shared Functions
```python
def query_instances(template_uuid):
    """Query instances for ONE specific template
    
    CRITICAL: Queries for 'status:pending or status:waiting'
    because waiting tasks are still active instances!
    """
    task rc.hooks=off rtemplate:{uuid} '(status:pending or status:waiting)' export

def check_instance_count(template_uuid):
    """Targeted check for ONE template only
    
    Returns:
        ('missing', None) - 0 instances
        ('ok', instance) - 1 instance  
        ('multiple', instances) - 2+ instances
    """
```

#### on-add/on-modify - When to Check
```python
# Template rlast modified
if 'rlast' in modified:
    status, data = check_instance_count(THIS_template_uuid)
    # Only affects THIS template

# Instance rindex modified  
if 'rindex' in modified:
    status, data = check_instance_count(THIS_template_uuid)
    # Only affects THIS template
```

#### on-exit - Reactive Only
```python
# Only process tasks in the input stream
for task in input_tasks:
    if task_completed and is_instance:
        spawn_next_for_THIS_template()  # Only THIS one!
```

---

## Key Fixes

### 1. Query Fixed - Include Waiting Tasks
**Before:**
```python
task rtemplate:{uuid} status:pending export
```
- Missed waiting tasks
- Caused false "no instance" errors
- Triggered spurious spawning

**After:**
```python
task rtemplate:{uuid} '(status:pending or status:waiting)' export
```
- Finds both pending and waiting instances
- Correctly counts instances
- No spurious spawning

### 2. Isolation Enforced
**Before:**
```python
# Check all templates (WRONG!)
for all_templates:
    check_and_fix()
```

**After:**
```python
# Only check the template being modified (RIGHT!)
if modifying_template:
    check_instance_count(this_template_uuid_only)
```

### 3. No Global Sweeps
- ❌ Removed: `enforce_one_to_one_rule()` from on-exit
- ❌ Removed: Looping through all templates
- ✅ Added: `check_instance_count()` for targeted checking
- ✅ Added: Call only when modifying specific template/instance

---

## When Checking Happens

### Template Modified
```bash
task 1 mod rlast:5
  ↓
on-modify:
  check_instance_count(template_1_uuid)  # ONLY template 1
  - Found 1 instance → sync rindex
  - Missing → warn (on-exit will spawn when completing)
  - Multiple → error (manual fix)
```

### Instance Modified
```bash
task 42 mod rindex:10
  ↓
on-modify:
  check_instance_count(template_from_rtemplate_field)  # ONLY that template
  - Sync template rlast
  - Check for multiple instances
```

### Instance Completed
```bash
task 42 done
  ↓
on-exit:
  spawn_next_instance(template_from_rtemplate_field)  # ONLY that template
```

---

## What Won't Happen Anymore

❌ Deleting one task doesn't spawn instances for other templates
❌ Modifying template A doesn't check templates B, C, D...
❌ Waiting tasks aren't miscounted as "missing"
❌ Global "cleanup" operations affecting unrelated tasks

---

## Test Scenarios

### Test 1: Delete Instance (Should Only Affect That Template)
```bash
# Setup: 3 templates with instances
task add "Daily" due:today r:1d
task add "Weekly" due:friday r:1w  
task add "Monthly" due:eom r:1mo

# Delete Daily's instance
task 2 delete
```

**Expected:**
```
Deleted task 2 -- Daily (instance #0)
  Template: task 1
Created instance 1 of 'Daily'
```

**Should NOT see:**
```
[ONE-TO-ONE] Created instance X of 'Weekly'   ← WRONG!
[ONE-TO-ONE] Created instance Y of 'Monthly'  ← WRONG!
```

### Test 2: Modify Template rlast (Targeted Check)
```bash
# Create template with waiting instance
task add "Bill" due:next-month r:1mo wait:due-7d

# Modify template rlast
task 1 mod rlast:5
```

**Expected:**
```
Template rlast modified: 0 → 5
  Instance #0 (task 2) rindex auto-synced to 5.
```

**Verification:**
```bash
# Should find the waiting instance
task 2 export | jq '.[] | {status, rindex}'
# Should show: status:"waiting", rindex:"5"
```

### Test 3: Multiple Instances (Corruption Detection)
```bash
# Manually create corruption
task add "Test" due:today r:1d
task add "Test" rtemplate:<UUID> rindex:0
task add "Test" rtemplate:<UUID> rindex:0

# Modify template
task 1 mod priority:H
```

**Expected:**
```
ERROR: Multiple instances exist (violates one-to-one rule - DATA CORRUPTION)
  Expected: Exactly 1 instance
  Found: 3 instances: task 2 (rindex=0), task 3 (rindex=0), task 4 (rindex=0)
  Manual fix required:
    1. Decide which instance to keep
    2. Delete the others: task <id> delete
```

---

## Files Changed

### recurrence_common_hook.py
**Added:**
- `query_instances(template_uuid)` - Query with pending OR waiting
- `check_instance_count(template_uuid)` - Targeted checking function

### on-add_recurrence.py
**Changed:**
- Import `query_instances` and `check_instance_count`
- Use `check_instance_count()` in template rlast handler
- Use `check_instance_count()` in instance modification handler
- Removed manual instance counting logic

### on-exit_recurrence.py  
**Removed:**
- `enforce_one_to_one_rule()` function (entire global sweep)
- Call to `enforce_one_to_one_rule()` in main()
**Kept:**
- Reactive spawning when instances complete
- Only processes tasks in input stream

---

## Critical Lessons Learned

1. **Isolation is Sacred** - Never let one task affect another
2. **Targeted Over Global** - Check only what changed
3. **Waiting = Active** - status:waiting is still an active instance
4. **Reactive > Proactive** - Fix problems when they occur, not preemptively

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

# Ensure symlink
cd ~/.task/hooks
ln -sf on-add_recurrence.py on-modify_recurrence.py

# Test isolation
task add "Test1" due:today r:1d
task add "Test2" due:friday r:1w
task 2 delete  # Should ONLY affect Test1
```

---

## Debugging

```bash
export DEBUG_RECURRENCE=1
task 1 mod rlast:5
tail -f ~/.task/recurrence_debug.log
```

**Look for:**
```
[timestamp] ADD/MOD: Instance check for {uuid}: OK (1 found)
[timestamp] ADD/MOD: Auto-synced instance 42 rindex: 0 -> 5
```

**Should NOT see:**
```
[timestamp] EXIT: Checking template X...  ← Global checking removed!
[timestamp] EXIT: Spawned instance for unrelated template  ← WRONG!
```

---

## Summary

✅ Targeted checking - only the template being modified
✅ Waiting tasks included in instance queries
✅ No global sweeps affecting unrelated tasks
✅ Isolation principle preserved
✅ One-to-one rule enforced surgically

The system now respects the fundamental principle: **Modifying task A never affects tasks B, C, D, E...**
