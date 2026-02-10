# Annotation Handling Fix

## Problem

Annotations were being copied incorrectly using:
```python
cmd.append(f'annotate:{annotation["description"]}')
```

This treats `annotate` as a field in the `task add` command, but **annotate is a command**, not a field.

## Taskwarrior Annotation API

**CORRECT (two-step process):**
```bash
task add "description"        # Step 1: Create task
task <ID> annotate "text"     # Step 2: Add annotation
```

**WRONG (what we were doing):**
```bash
task add "description" annotate:"text"  # Invalid syntax
```

## JSON Structure

In Taskwarrior's JSON export:
```json
{
  "annotations": [
    {
      "entry": "20260210T120000Z",
      "description": "First annotation"
    },
    {
      "entry": "20260210T130000Z", 
      "description": "Second annotation"
    }
  ]
}
```

Each annotation has:
- `description`: The annotation text
- `entry`: Timestamp when annotation was added

## Solution

**Two-phase approach:**

### Phase 1: Skip during attribute-agnostic copying
```python
elif field == 'annotations' and isinstance(value, list):
    # Annotations cannot be added via 'task add' - need separate commands
    if DEBUG:
        debug_log(f"Skipping {len(value)} annotation(s) - will add after task creation", "COMMON")
```

### Phase 2: Add after task creation
```python
# After task is created and we have task_id:
if task_id and 'annotations' in template:
    for annotation in template['annotations']:
        subprocess.run(
            ['task', 'rc.hooks=off', 'rc.confirmation=off', 'rc.verbose=nothing',
             task_id, 'annotate', annotation['description']],
            ...
        )
```

## Behavior

### Template with annotations:
```bash
task add "Weekly review" r:1w due:friday
task <id> annotate "Check metrics"
task <id> annotate "Update roadmap"
```

Template JSON:
```json
{
  "description": "Weekly review",
  "annotations": [
    {"entry": "20260210T120000Z", "description": "Check metrics"},
    {"entry": "20260210T130000Z", "description": "Update roadmap"}
  ]
}
```

### Spawned instance:
```bash
task 123 export
```

Instance JSON:
```json
{
  "description": "Weekly review",
  "rtemplate": "...",
  "rindex": 2,
  "annotations": [
    {"entry": "20260210T150000Z", "description": "Check metrics"},
    {"entry": "20260210T150000Z", "description": "Update roadmap"}
  ]
}
```

**Note:** All annotations get the same timestamp (spawn time), not original template timestamps. This is acceptable because:
1. Template annotations are guidance for instances
2. Instance gets its own annotation timeline
3. Original timestamps aren't meaningful for instances

## Testing

```bash
# Create template with annotations
task add "Test" r:1d due:tomorrow
task <id> annotate "Note 1"
task <id> annotate "Note 2"

# Trigger spawn
task <instance> done

# Check new instance
task <new_instance> info
# Should show both annotations
```

## Files Changed

**recurrence_common_hook.py:**
- Lines 863-867: Skip annotations during attribute copying
- Lines 915-933: Add annotations post-creation using `task annotate`

## Why This Matters

Annotations are often used for:
- Checklists (subtasks within a task)
- Notes and reminders
- Progress tracking
- Context that should carry forward

Without this fix, annotations would either:
- Be ignored entirely
- Create invalid UDAs named "annotate"
- Cause task creation to fail

## Alternative Approaches Considered

### Approach 1: Don't copy annotations at all
**Pro:** Simple, avoids complexity  
**Con:** Users lose valuable context

### Approach 2: Store in custom UDA
**Pro:** No post-creation subprocess  
**Con:** Breaks Taskwarrior's annotation system, loses timestamps

### Approach 3: Use hooks to add annotations ✓ (chosen)
**Pro:** Proper Taskwarrior API, preserves structure  
**Con:** Requires post-creation step

## Limitations

**Timestamp loss:** Original annotation timestamps are not preserved. All instance annotations get spawn timestamp.

**Workaround (if timestamps matter):**
Store timestamp in annotation text:
```bash
task <id> annotate "2026-02-10: Original note"
```

## See Also

- Taskwarrior DOM: `annotations.<N>.description`
- Command: `task <id> annotate "text"`
- Command: `task <id> denotate "text"`
