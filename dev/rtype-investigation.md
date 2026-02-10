# rtype Warning Investigation

## The Warning
```
WARNING: Removed legacy recurrence field 'rtype'
  Enhanced recurrence uses different fields (r, type, rtemplate, etc.)
```

## The Mystery
- Warning appears when annotating template: `task 102 ann note one`
- BUT task 102 export shows NO rtype field
- rtype IS legitimately a legacy field (should stay in LEGACY_RECURRENCE)
- Warning appears "frequently" according to user

## What We Know

### 1. rtype is NOT in task 102
```bash
task 102 export | grep -i rtype
# Returns nothing
```

### 2. strip_legacy_recurrence() only warns if field EXISTS
```python
def strip_legacy_recurrence(task):
    warnings = []
    for field in LEGACY_RECURRENCE:
        if field in task:  # <-- Only warns if present
            del task[field]
            warnings.append(f"WARNING: Removed legacy recurrence field '{field}'...")
    return warnings
```

### 3. The hook is on-modify (triggered by annotate)
```
task 102 ann note one
    ↓
on-modify hook receives: (original, modified)
    ↓
strip_legacy_recurrence(modified)
    ↓
WARNING appears
```

## Hypothesis 1: Timing/Cache Issue
**Theory:** Python cache has old version with rtype

**Evidence:**
- User said "I see this warning frequently"
- Suggests persistent issue across multiple tasks

**Test:**
```bash
rm -rf ~/.task/hooks/__pycache__
export PYTHONDONTWRITEBYTECODE=1
task 102 ann "test note"
# Does warning still appear?
```

## Hypothesis 2: Modified Task Has rtype
**Theory:** Taskwarrior adds rtype during modify operation

**Evidence:**
- Original task doesn't have it
- Modified task might

**Test:**
```bash
export DEBUG_RECURRENCE=1
task 102 ann "test"
grep "rtype" ~/.task/recurrence_debug.log
```

Look for the JSON that on-modify receives.

## Hypothesis 3: UDA Definition Conflict
**Theory:** rtype defined as UDA somewhere, gets auto-added

**Check:**
```bash
task show | grep rtype
cat ~/.taskrc | grep rtype
cat ~/.task/hooks/recurrence/recurrence.rc | grep rtype
cat ~/.task/config/recurrence.rc | grep rtype
```

## Hypothesis 4: Annotation Triggers rtype Creation
**Theory:** When adding annotation, Taskwarrior synthesizes missing fields

**Test sequence:**
```bash
# Clean slate
task add "Clean test" r:1d due:tomorrow +clean
TASK_ID=$(task newest export | jq -r '.[0].id')

# Export before annotation
task $TASK_ID export | grep rtype
# Should be empty

# Add annotation
task $TASK_ID ann "test note"

# Export after annotation  
task $TASK_ID export | grep rtype
# Is it there now?
```

## Hypothesis 5: Template vs Instance Issue
**Theory:** Only templates get the warning, or vice versa

**Data point:** Warning on task 102 (template)

**Test:**
```bash
# Try on instance
task 103 ann "instance test"
# Does warning appear?
```

## The Debug Approach

### Step 1: Enable Full Debug
```bash
export DEBUG_RECURRENCE=1
rm -rf ~/.task/hooks/__pycache__
```

### Step 2: Add Debug to strip_legacy_recurrence
Edit recurrence_common_hook.py, add before line that deletes field:

```python
def strip_legacy_recurrence(task):
    warnings = []
    for field in LEGACY_RECURRENCE:
        if field in task:
            if DEBUG:
                debug_log(f"STRIPPING: Found '{field}' in task", "VALIDATION")
                debug_log(f"  Task UUID: {task.get('uuid')}", "VALIDATION")
                debug_log(f"  Task desc: {task.get('description')}", "VALIDATION")
                debug_log(f"  Field value: {task[field]}", "VALIDATION")
            del task[field]
            warnings.append(...)
```

### Step 3: Reproduce
```bash
task add "Debug test" r:1d due:tomorrow +debug
task <id> ann "trigger warning"
```

### Step 4: Analyze Log
```bash
tail -100 ~/.task/recurrence_debug.log | grep -A5 "STRIPPING"
```

Should show:
- Which task has rtype
- What the rtype value is
- When it appears (original or modified)

## Critical Questions

1. **Does the warning appear on EVERY annotation?**
   - If yes: Hook issue
   - If no: Specific task issue

2. **Does it appear on instances or only templates?**
   - If templates only: Template-specific field
   - If both: System-wide issue

3. **What's the actual rtype value when stripped?**
   - Empty string?
   - Some old value?
   - Generated value?

4. **Is it in the original or modified task?**
   - Original: Pre-existing field
   - Modified: Taskwarrior generating it
   - Both: Persistent field

## Possible Root Causes

### A. Old Templates from Previous Versions
If user has templates created before we changed `rtype` → `type`:
```bash
# Find old templates
task status:recurring export | jq '.[] | select(.rtype != null)'
```

**Fix:** Migrate old templates
```bash
task <uuid> modify rtype:
```

### B. Config File Has uda.rtype Definition
```bash
grep -r "uda.rtype" ~/.task/ ~/.taskrc
```

**Fix:** Remove UDA definition

### C. Hook Version Mismatch
Different hook files have different field names:
- Old on-add still uses `rtype`
- New on-modify expects `type`

**Check:**
```bash
grep "rtype" ~/.task/hooks/on-*.py
```

### D. Taskwarrior Bug/Feature
Taskwarrior auto-generates fields for status:recurring tasks

**Test:** Create task WITHOUT hooks
```bash
task rc.hooks=off add "No hooks" status:recurring
task <id> export | grep rtype
```

## Action Items

1. Add detailed debug logging to strip_legacy_recurrence
2. Reproduce with DEBUG=1
3. Check if warning appears on every annotation or just some
4. Export task before and after annotation
5. Search all config files for rtype UDA definition
6. Check if old templates exist with rtype field

## Temporary Workaround

If warning is spurious and annoying:
```python
# Comment out rtype in LEGACY_RECURRENCE
LEGACY_RECURRENCE = {
    'recur',
    'mask',
    'imask',
    'parent',
    # 'rtype'  # Temporarily disabled - investigate why it triggers
}
```

BUT this is treating symptom, not cause!

## Why This Matters

If rtype is appearing when it shouldn't:
- Indicates hook getting stale data
- Possible cache issue
- Possible Taskwarrior behavior we don't understand
- Could affect other fields too

Need to understand WHERE rtype comes from before we can properly fix.

## Next Steps for Investigation

1. **Immediate:** Add debug logging to strip function
2. **Short-term:** Reproduce and capture full task JSON
3. **Long-term:** Understand Taskwarrior's field synthesis for recurring tasks

The warning is the symptom. The question is: **Why does a task that exports 
without rtype trigger the strip function that only runs when rtype exists?**

This is a logic contradiction that needs resolution.
