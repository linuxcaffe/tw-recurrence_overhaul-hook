# Taskwarrior Enhanced Recurrence - Developer Documentation

**Version:** 0.4.0  
**Status:** Core Working, Time Machine Needs Debug  
**Last Updated:** 2026-02-06

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [File Structure](#file-structure)
3. [Data Model](#data-model)
4. [Hook Behavior](#hook-behavior)
5. [Critical Rules](#critical-rules)
6. [Installation](#installation)
7. [Debugging](#debugging)
8. [Known Issues](#known-issues)
9. [Development Workflow](#development-workflow)

---

## Architecture Overview

### Three-File System

```
~/.task/hooks/
├── on-add_recurrence.py           (executable) - Creates templates, handles modifications
├── on-exit_recurrence.py          (executable) - Spawns instances only
├── recurrence_common_hook.py      (library)    - Shared utilities (NOT executable)
└── on-modify_recurrence.py        (symlink)    - → on-add_recurrence.py
```

### Core Principles

1. **on-add** = Template creation and modification ONLY
2. **on-exit** = Instance spawning ONLY
3. **Users** = Deletion ONLY
4. **Never**: on-add/on-modify should NEVER spawn or delete tasks

### Data Flow

```
User: task add "Gym" r:7d due:tomorrow
  ↓
on-add: Creates template (status:recurring, rlast:1)
  ↓
on-exit: Spawns instance #1 (status:pending, rindex:1)
  ↓
User: task <id> done
  ↓
on-exit: Spawns instance #2
```

---

## File Structure

### on-add_recurrence.py (1096 lines)

**Purpose:** Template creation and modification handler

**Key Functions:**
- `RecurrenceHandler.create_template()` - Convert new task with `r` into template
- `RecurrenceHandler.handle_template_modification()` - Track and explain template changes
- `RecurrenceHandler.handle_instance_modification()` - Track and explain instance changes
- `update_instance_for_rlast_change()` - Time machine: modify instance when rlast changes
- `query_task()` - Query Taskwarrior for task by UUID
- `query_instances()` - Query instances for a template
- `update_task()` - Modify task via Taskwarrior command

**What it does:**
- Normalizes recurrence types (c→chain, p→period)
- Converts absolute dates to relative (wait→rwait)
- Detects anchor changes (due↔sched)
- Tracks template modifications with user feedback
- Implements "time machine" (rlast modification)
- Validates template/instance attribute separation

**What it does NOT do:**
- ❌ Does NOT spawn instances
- ❌ Does NOT delete instances
- ❌ Does NOT call spawn_instance() or delete_instance()

### on-exit_recurrence.py (503 lines)

**Purpose:** Instance spawning only

**Key Functions:**
- `RecurrenceSpawner.process_tasks()` - Main loop for processing completed/deleted tasks
- `RecurrenceSpawner.create_instance()` - Spawn new instance with correct dates
- `RecurrenceSpawner.get_template()` - Fetch template by UUID
- `RecurrenceSpawner.check_rend()` - Check if recurrence has ended

**Spawning Logic:**
```python
# For periodic type:
anchor_date = template_anchor + (recur_delta × (index - 1))

# For chained type:
anchor_date = completion_time + recur_delta
```

**What it does:**
- Spawns instance #1 when template is created (rlast=0 or 1)
- Spawns next instance when current one completes/deletes
- Only spawns for the LATEST instance (rindex ≥ rlast)
- Checks rend date before spawning

**What it does NOT do:**
- ❌ Does NOT modify templates or instances
- ❌ Only spawns, never modifies existing tasks

### recurrence_common_hook.py (501 lines)

**Purpose:** Shared utility library

**Key Functions:**
- `normalize_type()` - Convert type abbreviations to full names
- `parse_duration()` - Parse '7d', '1w', 'P1D' to timedelta
- `parse_date()` - Parse ISO 8601 dates (20260206T120000Z)
- `format_date()` - Format datetime to ISO 8601
- `parse_relative_date()` - Parse 'due-2d', 'sched+1w'
- `is_template()` - Check if task is template
- `is_instance()` - Check if task is instance
- `get_anchor_field_name()` - Map 'sched'→'scheduled', 'due'→'due'
- `debug_log()` - Conditional logging to file
- `check_instance_count()` - Targeted instance checking (NOT global)
- `query_instances()` - Query instances for specific template

**Constants:**
```python
DAYS_PER_MONTH = 30
DAYS_PER_YEAR = 365
DEBUG = os.environ.get('DEBUG_RECURRENCE', '0') == '1'
LOG_FILE = os.path.expanduser("~/.task/recurrence_debug.log")
```

---

## Data Model

### Template (status:recurring)

**Required Fields:**
```json
{
  "status": "recurring",
  "r": "P7D",              // Recurrence period (ISO 8601 or simple: 7d, 1w, 1mo)
  "type": "chain|period",  // How instances spawn
  "rlast": "1",            // Last spawned instance index
  "ranchor": "due|sched",  // Which field is the anchor
  "due": "20260210T000000Z" // OR scheduled (one required)
}
```

**Optional Fields:**
```json
{
  "rwait": "due-172800s",      // Relative wait (seconds from anchor)
  "rscheduled": "due-86400s",  // Relative scheduled
  "rend": "20261231T235959Z",  // Stop spawning after this date
  "rlimit": "3",               // Max pending instances (default: 1)
  "project": "work",
  "priority": "H",
  "tags": ["important"]
}
```

**Forbidden Fields:**
- ❌ `rtemplate` - Only instances have this
- ❌ `rindex` - Only instances have this

### Instance (status:pending/completed/etc)

**Required Fields:**
```json
{
  "status": "pending",
  "rtemplate": "UUID",     // Parent template UUID
  "rindex": "1",           // Instance sequence number
  "due": "20260210T000000Z", // OR scheduled
  "tags": ["RECURRING"]    // Auto-added by system
}
```

**Inherited from Template:**
- `project`, `priority`, `tags` (non-recurrence)
- `wait`, `scheduled` (calculated from rwait/rscheduled)
- `until` (copied directly)

**Forbidden Fields:**
- ❌ `r` - Only templates have this
- ❌ `type` - Only templates have this
- ❌ `rlast` - Only templates have this
- ❌ `ranchor` - Only templates have this
- ❌ `rwait` - Only templates have this
- ❌ `rscheduled` - Only templates have this
- ❌ `rend` - Only templates have this

---

## Hook Behavior

### on-add Behavior

#### New Task with `r` Field
```bash
task add "Gym" r:7d due:tomorrow ty:c
```

**Actions:**
1. Set `status:recurring`
2. Normalize `type` (c→chain)
3. Set `rlast:1`
4. Detect anchor (`ranchor:due`)
5. Convert `wait` to `rwait` if present
6. Output: "Created recurrence template. First instance will be generated on exit."

#### Template Modification (Time Machine)
```bash
task 1 mod rlast:5
```

**Actions:**
1. Detect rlast change (0→5)
2. Query for current instance
3. **Call update_instance_for_rlast_change()** to modify instance
4. Update instance's rindex to 5
5. Recalculate instance's due date
6. Output: "Instance #1 updated to #5"

**What it does NOT do:**
- ❌ Does NOT delete instance
- ❌ Does NOT spawn new instance
- ❌ Modifies existing instance in place

#### Instance Modification
```bash
task 42 mod rindex:10
```

**Actions:**
1. Detect rindex change
2. Query template
3. Update template's rlast to 10
4. Output: "Template rlast auto-synced to 10"

### on-exit Behavior

#### New Template Created
```bash
# After: task add "Gym" r:7d due:tomorrow
```

**Actions:**
1. Detect template with rlast in ['0', '1', '']
2. Spawn instance #1
3. Update template rlast to 1

#### Instance Completed
```bash
task 42 done
```

**Actions:**
1. Detect completed instance
2. Query template
3. Check if rindex ≥ rlast (is this the latest?)
4. If yes, spawn next instance (rindex + 1)
5. Update template rlast

#### Instance Deleted
```bash
task 42 delete
```

**For chain type:**
- Spawn next instance (same as completion)

**For period type:**
- Do NOT spawn (deletion means "skip this one")

---

## Critical Rules

### The Invariant

**rlast MUST equal highest active rindex**

```
Template rlast:5
Instance rindex:5 (pending)
✓ CORRECT

Template rlast:3
Instance rindex:5 (pending)
✗ DESYNC - FIX IT
```

### One-to-One Rule

**Every active template MUST have exactly ONE pending instance**

```
Template UUID-123
  ├─ Instance #5 (pending)  ✓ CORRECT
  
Template UUID-456
  ├─ Instance #3 (pending)
  └─ Instance #4 (pending)  ✗ CORRUPTION - Multiple instances!

Template UUID-789
  (no instances)            ✗ MISSING - Need to spawn!
```

### Attribute Separation

**Templates and instances have separate attribute sets:**

```python
TEMPLATE_ONLY = {'r', 'type', 'ranchor', 'rlast', 'rend', 'rwait', 'rscheduled'}
INSTANCE_ONLY = {'rtemplate', 'rindex'}
```

If attributes cross over, hooks auto-remove them with warnings.

### Spawning Responsibility

**ONLY on-exit spawns instances**

- on-add: Creates templates ✓, Modifies tasks ✓, Spawns instances ✗
- on-exit: Spawns instances ✓, Modifies tasks ✗

### Deletion Responsibility

**ONLY users delete tasks**

- Hooks NEVER delete tasks
- Exception: None (even time machine doesn't delete)

---

## Installation

### Quick Install

```bash
# 1. Copy files
cp on-add_recurrence.py ~/.task/hooks/
cp on-exit_recurrence.py ~/.task/hooks/
cp recurrence_common_hook.py ~/.task/hooks/

# 2. Set permissions
chmod +x ~/.task/hooks/on-add_recurrence.py
chmod +x ~/.task/hooks/on-exit_recurrence.py
chmod -x ~/.task/hooks/recurrence_common_hook.py  # Library, not executable!

# 3. Create symlink
cd ~/.task/hooks
ln -sf on-add_recurrence.py on-modify_recurrence.py

# 4. Verify
ls -la ~/.task/hooks/on-*.py
# Should see:
# -rwxr-xr-x on-add_recurrence.py
# -rwxr-xr-x on-exit_recurrence.py
# lrwxrwxrwx on-modify_recurrence.py -> on-add_recurrence.py

# 5. Verify library NOT executable
ls -la ~/.task/hooks/recurrence_common_hook.py
# Should see:
# -rw-r--r-- recurrence_common_hook.py
```

---

## Debugging

### Enable Debug Logging

```bash
export DEBUG_RECURRENCE=1
```

This creates `~/.task/recurrence_debug.log` with detailed execution traces.

### Debug Log Format

```
[2026-02-06 12:34:56] PREFIX: message
```

**Prefixes:**
- `ADD/MOD` - on-add/on-modify hook
- `EXIT` - on-exit hook
- `COMMON` - recurrence_common_hook library

### Python Bytecode Cache Issues

**Symptom:** Changes to .py files don't take effect

**Fix:**
```bash
# Obliterate all caches
find ~/.task -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find ~/.task -type f -name "*.pyc" -delete 2>/dev/null

# Disable permanently
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=/dev/null
```

---

## Known Issues

### 1. Time Machine Not Working (as of 2026-02-06)

**Status:** INVESTIGATING

**Symptom:**
```bash
task 79 mod rlast:5
# Instance rindex stays 1, doesn't update to 5
```

**Expected:**
- Instance #1 should update to #5
- Due date should recalculate

**Actual:**
- Instance stays at #1
- Template rlast updates to 5 (correct)
- Instance not modified

**Next Steps:**
- Check if `update_instance_for_rlast_change()` is being called
- Check if `update_task()` succeeds
- Check debug log for "Updating instance" messages

---

## Development Workflow

### Testing Changes

```bash
# 1. Clean environment
rm -rf ~/.task/hooks/__pycache__
rm -f ~/.task/hooks/.goutputstream-*

# 2. Copy new files
cp /path/to/on-add_recurrence.py ~/.task/hooks/
chmod +x ~/.task/hooks/on-add_recurrence.py

# 3. Enable debug
export DEBUG_RECURRENCE=1

# 4. Test
task add "Test" r:1d due:tomorrow ty:p +test

# 5. Check results
task recurring
tail -50 ~/.task/recurrence_debug.log
```

### Code Modification Guidelines

1. **Always ask before generating new file versions**
2. **Check current files first** - Use `view` tool on /mnt/project/
3. **Test syntax before installing** - Use `python3 -m py_compile`
4. **Version all changes** - Update version numbers and dates
5. **Document in CHANGES.txt** - Track what changed and why
6. **Test incrementally** - One change at a time

---

**Remember:** Smart coding over quick fixes. Aim for reliable product!
