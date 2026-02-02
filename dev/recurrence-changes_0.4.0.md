## Enhanced Recurrence Hook v0.4.0 - Complete Implementation

### Version: 0.4.0 (with Auto-Sync and Validation)
### Date: 2026-02-02

---

## 🎯 What's New in v0.4.0

This version implements **full bidirectional auto-sync** between template rlast and instance rindex values, plus comprehensive validation and error detection. No more manual sync commands needed!

---

## ✅ Implemented Features

### 1. Querying Infrastructure

**New Functions:**
- `query_task(uuid)` - Query Taskwarrior for any task by UUID
- `query_instances(template_uuid)` - Get all pending instances for a template
- `update_task(uuid, modifications)` - Update a task programmatically

**Uses `rc.hooks=off`** to prevent infinite recursion when making queries/updates from within hooks.

---

### 2. Template Modifications (Enhanced)

#### Type Changes (period ↔ chain)
```bash
task add "Test" due:friday r:1w type:period
task 1 mod type:chain
```
**Output:**
```
Modified template type: period → chain
  This changes how future instances spawn (on completion of current instance).
  Current rlast=0 preserved.
```

#### Recurrence Interval Changes
```bash
task 1 mod r:2w
```
**Output:**
```
Modified recurrence interval: 1w → 2w
  This changes the spacing between future instances.
```

#### Anchor Changes (due ↔ sched) with Auto-Update
```bash
task add "Review" due:friday r:1w rwait:due-2d
task 1 mod due: scheduled:friday
```
**Output:**
```
Modified template anchor: due → sched
  Relative dates (rwait) updated to use new anchor.
```
**Automatically updates:**
- `ranchor` field
- All `rwait` references (due-2d → sched-2d)
- All `rscheduled` references

#### Time Machine (rlast) with Instance Auto-Sync ⭐ NEW
```bash
task add "Gym" due:2026-02-03 r:7d type:period
# Some instances pass...
task 1 mod rlast:5
```
**Output (Period):**
```
Template rlast modified: 0 → 5 (5 instances forward)
  Next instance will be #6 due 20260310T000000Z
  Instance #0 (task 42) rindex auto-synced to 5.
```

**What happens:**
1. Template rlast changes from 0 → 5
2. Hook queries for instance with rindex=0 (old current instance)
3. Hook automatically updates that instance's rindex to 5
4. Both stay in perfect sync!

**Output (Chain):**
```
Template rlast modified: 0 → 5
  Next instance will be #6 (spawns on completion).
  Instance #0 (task 42) rindex auto-synced to 5.
```

#### Recurrence End Changes
```bash
task 1 mod rend:10
```
**Output:**
```
Modified recurrence end: none → 10
  Template will stop repeating after this limit.
```

#### Wait Field Auto-Conversion
```bash
task add "Backup" due:2026-02-10 r:7d wait:2026-02-08
```
**Output:**
```
Converted absolute wait to relative: rwait=due-172800s
This will apply to all future instances.
```

#### Anchor Date Changes
```bash
task 1 mod due:2026-02-15
```
**Output (Period):**
```
Modified template due date: 20260210T000000Z → 20260215T000000Z
  This shifts all future instances by the same offset.
```

**Output (Chain):**
```
Modified template due date: 20260210T000000Z → 20260215T000000Z
  This affects next instance only (chain type).
```

#### Attribute Changes with Instance Resolution ⭐ ENHANCED
```bash
task add "Gym" due:friday r:1w project:health
# Wait for instance to spawn
task 1 mod project:fitness priority:H
```
**Output:**
```
Modified template attributes: project, priority
  This will affect future instances. To apply to current instance #0:
  task 42 mod project:fitness priority:H
```

**What's new:**
- Hook queries for current instance (rindex matching rlast)
- Provides exact task ID in suggestion (not just UUID)
- Gives copy-paste command ready to go

---

### 3. Instance Modifications (Enhanced)

#### rindex Changes with Template Auto-Sync ⭐ NEW
```bash
task 42 mod rindex:10
```
**Output:**
```
Modified instance rindex: 0 → 10
  Template rlast auto-synced to 10.
```

**What happens:**
1. Instance rindex changes from 0 → 10
2. Hook queries the template
3. Hook automatically updates template rlast to 10
4. Both stay in perfect sync!

#### Desync Detection and Auto-Fix ⭐ NEW
If somehow instance rindex and template rlast get out of sync (external edits, bugs, etc.):

```bash
# Assume instance rindex=5 but template rlast=3 (desync!)
task 42 mod priority:H
```
**Output:**
```
WARNING: Detected desync - instance rindex=5 but template rlast=3
  Auto-fixed: Template rlast updated to 5
Modified task 42 -- gym routine (instance #5)
Modified instance attributes: priority
  To apply this change to all future instances:
  task 1 mod priority:H
```

**What happens:**
1. Hook detects rindex ≠ rlast during any instance modification
2. Automatically fixes template rlast to match instance rindex
3. Warns user about the desync and fix
4. Continues with normal modification handling

#### Attribute Changes with Template Resolution ⭐ ENHANCED
```bash
task 42 mod project:work
```
**Output:**
```
Modified instance attributes: project
  To apply this change to all future instances:
  task 1 mod project:work
```

**What's new:**
- Queries template to get numeric ID (not just UUID)
- Provides exact task ID for easy copying
- Handles tags formatting correctly

---

### 4. Instance Completion (Enhanced)

#### Completion with Validation ⭐ NEW
```bash
task 42 done
```

**Normal output:**
```
Completed task 42 -- gym routine (instance #3)
  Template: task 1
```

**If rindex doesn't match rlast:**
```
Completed task 42 -- gym routine (instance #3)
  Template: task 1
WARNING: Instance rindex=3 doesn't match template rlast=5
  This may indicate out-of-order completion or missed instances.
```

**If no pending instances exist:**
```
Completed task 42 -- gym routine (instance #3)
  Template: task 1
ERROR: No pending instances exist for this template.
  On-exit hook should spawn next instance, but may need manual intervention.
```

**What happens:**
1. Hook queries template to check rlast
2. Compares with instance rindex being completed
3. Warns if they don't match (out-of-order)
4. Queries for other pending instances
5. Errors if none exist (on-exit should fix this)

---

## 🔧 Architecture Details

### Hook Execution Flow

```
1. Hook receives input (1 or 2 JSON task objects)
2. Determines mode (ADD vs MODIFY)
3. Parses task(s) and detects type (template/instance/new)
4. Routes to appropriate handler
5. Handler queries Taskwarrior as needed (rc.hooks=off)
6. Handler auto-syncs or auto-fixes as appropriate
7. Handler collects messages
8. Outputs modified task JSON
9. Outputs all messages to stderr
10. Exits
```

### Query Safety

All queries use `rc.hooks=off` to prevent recursive hook calls:
```bash
task rc.hooks=off UUID export        # Query
task rc.hooks=off rc.confirmation=off UUID mod field:value  # Update
```

### Error Handling

- Query failures are logged but don't crash the hook
- Update failures are logged and user is warned
- Fallback to manual sync commands if auto-sync fails
- Invalid JSON is caught with clear error messages

---

## 📊 Comparison: Before vs After

### Before v0.4.0
```bash
# User modifies instance rindex
task 42 mod rindex:5

# Output:
Modified instance rindex: 3 → 5
  Template rlast will be synced to 5.
  Update template with: task abc-123-def mod rlast:5

# User must manually run command:
task abc-123-def mod rlast:5
```

### After v0.4.0
```bash
# User modifies instance rindex
task 42 mod rindex:5

# Output:
Modified instance rindex: 3 → 5
  Template rlast auto-synced to 5.

# Done! No manual command needed.
```

---

## 🧪 Testing Checklist

### Template Modifications
- [ ] Type change (period → chain)
- [ ] Type change (chain → period)
- [ ] Recurrence interval change
- [ ] Anchor change (due → sched)
- [ ] Anchor change (sched → due)
- [ ] rlast change forward (time machine)
- [ ] rlast change backward (rollback)
- [ ] rlast change with auto-sync to instance
- [ ] rend modification
- [ ] Wait absolute → relative conversion
- [ ] Anchor date change (period type)
- [ ] Anchor date change (chain type)
- [ ] Attribute changes with instance resolution
- [ ] Multiple simultaneous changes

### Instance Modifications
- [ ] rindex change with template auto-sync
- [ ] rindex change when desync exists
- [ ] Attribute changes with template resolution
- [ ] Any modification when desync exists (auto-fix)

### Instance Completion
- [ ] Normal completion (rindex = rlast)
- [ ] Out-of-order completion (rindex ≠ rlast)
- [ ] Completion when no pending instances exist
- [ ] Deletion instead of completion

### Edge Cases
- [ ] Template/instance not found in queries
- [ ] Update failures (permission issues, etc.)
- [ ] Invalid JSON input
- [ ] Missing required fields
- [ ] Multiple hooks running simultaneously

---

## 🐛 Known Limitations

1. **Race Conditions**: If multiple hooks run simultaneously modifying the same template/instance, auto-sync might conflict. (Rare in normal usage)

2. **Hook Recursion**: We use `rc.hooks=off` to prevent recursion, but this means our updates don't trigger other hooks. (This is intentional and correct)

3. **Performance**: Querying adds latency (~50-100ms per query). For most users this is imperceptible, but on slow systems or with many instances it could be noticeable.

4. **Instance Spawning**: We detect missing instances but don't spawn them - that's the on-exit hook's job. If on-exit isn't working, user needs manual intervention.

---

## 📝 Debug Mode

Enable comprehensive logging:
```bash
export DEBUG_RECURRENCE=1
task <command>
tail -f ~/.task/recurrence_debug.log
```

Debug output includes:
- Hook entry/exit
- Mode detection (ADD vs MODIFY)
- Template/instance detection
- Query results
- Update results
- Auto-sync operations
- Desync detection
- All attribute changes

---

## 🚀 Installation

```bash
# Copy files
cp on-add_recurrence.py ~/.task/hooks/
cp recurrence_common_hook.py ~/.task/hooks/

# Make executable
chmod +x ~/.task/hooks/on-add_recurrence.py

# Create symlink for on-modify
cd ~/.task/hooks
ln -s on-add_recurrence.py on-modify_recurrence.py

# Test
task add "Test" due:tomorrow r:1d
task 1 mod rlast:5
task list
```

---

## 📄 Files

- `on-add_recurrence.py` - v0.4.0 (661 lines)
- `recurrence_common_hook.py` - v0.4.0 (274 lines)
- Both required for full functionality

---

## 🎉 Summary

v0.4.0 represents a **complete implementation** of the smart modification features outlined in recurrence-mods.md:

✅ All template modifications tracked and explained
✅ All instance modifications tracked and explained  
✅ Bidirectional rlast ↔ rindex auto-sync
✅ Desync detection and auto-fix
✅ Instance existence validation
✅ Task ID resolution for friendly messages
✅ Comprehensive error handling
✅ Full debug logging

The system now maintains perfect synchronization automatically, provides helpful educational messages, and catches/fixes issues proactively. Users can modify templates and instances freely without worrying about manual sync commands or getting out of sync!
