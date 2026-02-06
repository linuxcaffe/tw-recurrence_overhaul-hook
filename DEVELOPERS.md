# Taskwarrior Enhanced Recurrence - Developer Documentation

**Version:** 0.4.1  
**Status:** Core Working ✓
**Last Updated:** 2026-02-06

## Version 0.4.1 Changes

**Refactoring:**
- Eliminated 106 lines of duplicate code from on-exit (-21%)
- Removed local `create_instance()` method
- Always use `spawn_instance()` from common module (single source of truth)

**New Features:**
- Added `runtil` field support (like `rwait`/`rscheduled`)
- Hour support in relative dates: `sched+4hr`, `wait-2h`
- Cleaner messaging: "Created task N - 'description' (recurrence instance #1)"

**Improvements:**
- Suppressed Taskwarrior's verbose messages from internal operations
- Removed noisy wait conversion messages
- `until` field now recalculates for each instance

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
â”œâ”€â”€ on-add_recurrence.py           (executable) - Creates templates, handles modifications
â”œâ”€â”€ on-exit_recurrence.py          (executable) - Spawns instances only
â”œâ”€â”€ recurrence_common_hook.py      (library)    - Shared utilities (NOT executable)
â””â”€â”€ on-modify_recurrence.py        (symlink)    - â†’ on-add_recurrence.py
```

### Core Principles

1. **on-add** = Template creation and modification
2. **on-exit** = Instance spawning
3. **Users** = Deletion (ONLY, this app doesn't delete tasks)

### Data Flow

```
User: task add "Gym" r:7d due:tomorrow
  â†“
on-add: Creates template (status:recurring, rlast:1)
  â†“
on-exit: Spawns instance #1 (status:pending, rindex:1)
  â†“
User: task <id> done
  â†“
on-exit: Spawns instance #2
```

---

## File Structure

### on-add_recurrence.py (1135 lines)

**Purpose:** Template creation and modification handler

**Key Functions:**
- `RecurrenceHandler.create_template()` - Convert new task with `r` and `ranchor` into template
- `RecurrenceHandler.handle_template_modification()` - Track and explain template changes
- `RecurrenceHandler.handle_instance_modification()` - Track and explain instance changes
- `query_task()` - Query Taskwarrior for task by UUID
- `query_instances()` - Query instances for a template
- `update_task()` - Modify task via Taskwarrior command

**What it does:**
- Normalizes recurrence types (câ†’chain, pâ†’period)
- Converts absolute dates to relative (waitâ†’rwait)
- Detects anchor changes (dueâ†”sched)
- Validates template/instance attribute separation

**What on-add does NOT do:**
- â�Œ Does NOT spawn instances
- â�Œ Does NOT delete instances

### on-exit_recurrence.py (397 lines)
**Purpose:** Instance spawning

**Note:** v0.4.1 removed 106 lines of duplicate code by eliminating local `create_instance()` 
method and always using `spawn_instance()` from common module.


**Key Functions:**
- `RecurrenceSpawner.process_tasks()` - Main loop for processing completed/deleted tasks

- `RecurrenceSpawner.get_template()` - Fetch template by UUID
- `RecurrenceSpawner.check_rend()` - Check if recurrence has ended

**Spawning Logic:**
```python
# For periodic type:
anchor_date = template_anchor + (recur_delta Ã— (index - 1))

# For chained type:
anchor_date = completion_time + recur_delta
```

**What on-exit does:**
- Spawns instance #1 when template is created (rlast=0 or 1)
- Spawns next instance when current one completes/deletes
- Only spawns for the LATEST instance (rindex â‰¥ rlast)
- Checks rend date before spawning

**What on-exit does NOT do:**
- â�Œ Does NOT modify templates or instances
- â�Œ Only spawns, never modifies existing tasks

### recurrence_common_hook.py (528 lines)

**Purpose:** Shared utility library

**Key Functions:**
- `normalize_type()` - Convert type abbreviations to full names
- `parse_duration()` - Parse '7d', '1w', 'P1D' to timedelta
- `parse_date()` - Parse ISO 8601 dates (20260206T120000Z)
- `format_date()` - Format datetime to ISO 8601
- `parse_relative_date()` - Parse 'due-2d', 'sched+1w', 'wait-4hr' (supports hours in v0.4.1)
- `is_template()` - Check if task is template
- `is_instance()` - Check if task is instance
- `get_anchor_field_name()` - Map 'sched'â†’'scheduled', 'due'â†’'due'
- `debug_log()` - Conditional logging to file
- `check_instance_count()` - Targeted instance checking (NOT global)
- `query_instances()` - Query instances for specific template
- `spawn_instance()` - Create new instance with proper verbosity control

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
  "runtil": "sched+14400s",    // Relative until (seconds from anchor)
  "rend": "20261231T235959Z",  // Stop spawning after this date
  "rlimit": "3",               // Max pending instances (default: 1)
  "project": "work",
  "priority": "H",
  "tags": ["important"]
}
```

**Templates should NOT have:**
- â�Œ `rtemplate` - Only instances have this
- â�Œ `rindex` - Only instances have this

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
- `wait`, `scheduled`, `until` (calculated from rwait/rscheduled/runtil)

**Instances do NOT have:**
- â�Œ `r` - Only templates have this
- â�Œ `type` - Only templates have this
- â�Œ `rlast` - Only templates have this
- â�Œ `ranchor` - Only templates have this
- â�Œ `rwait` - Only templates have this
- â�Œ `rscheduled` - Only templates have this
- â�Œ `rend` - Only templates have this

---

## Hook Behavior

### on-add Behavior

#### New Task with `r` and `ranchor` Fields
```bash
task add "Gym" r:7d due:tomorrow ty:c
```

**Actions:**
1. Set `status:recurring`
2. Normalize `type` (câ†’chain)
3. Set `rlast:1`
4. Detect anchor (`ranchor:due`)
5. Convert `sched` to `rscheduled` if present
6. Convert `wait` to `rwait` if present
7. Output: "Created recurrence template. First instance will be generated on exit."

#### Template Modification (Time Machine) NOTE; in development!
```bash
task 1 mod rlast:5
```

**Actions:**
1. Detect rlast change (0â†’5)
2. Query for current instance
3. **Call update_instance_for_rlast_change()** to modify instance
4. Update instance's rindex to 5
5. Recalculate instance's due date
6. Output: "Instance #1 updated to #5"

**What it does NOT do:**
- â�Œ Does NOT delete instance
- â�Œ Does NOT spawn new instance
- â�Œ Modifies existing instance in place

#### Instance Modification - NOTE; in development!
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
1. Detect completed or deleted instance
2. Query template
3. Check if rindex â‰¥ rlast (is this the latest?)
4. If yes, spawn next instance (rindex + 1)
5. Update template rlast

---

## Critical Rules

### The Invariant

**rlast MUST equal highest active rindex**

```
Template rlast:5
Instance rindex:5 (pending)
âœ“ CORRECT

Template rlast:3
Instance rindex:5 (pending)
âœ— DESYNC - FIX IT
```

### One-to-One Rule

**Every active template MUST have exactly ONE pending instance**

```
Template UUID-123
  â”œâ”€ Instance #5 (pending)  âœ“ CORRECT
  
Template UUID-456
  â”œâ”€ Instance #3 (pending)
  â””â”€ Instance #4 (pending)  âœ— CORRUPTION - Multiple instances!

Template UUID-789
  (no instances)            âœ— MISSING - Need to spawn!
```

### Attribute Separation

**Templates and instances have separate attribute sets:**

```python
TEMPLATE_ONLY = {'r', 'type', 'ranchor', 'rlast', 'rend', 'rwait', 'rscheduled', 'runtil'}
INSTANCE_ONLY = {'rtemplate', 'rindex'}
```

If attributes cross over, hooks auto-remove them with warnings.

### Spawning Responsibility

**ONLY on-exit spawns instances**

- on-add: Creates templates âœ“, Modifies tasks âœ“, Spawns instances âœ—
- on-exit: Spawns instances âœ“, Modifies tasks âœ—

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

### 1. Time Machine (rlast modifications) - In Development

**Status:** CODE IMPLEMENTED, NOT FULLY TESTED

The time machine feature (modifying template `rlast` to jump forward/backward in the sequence) 
has been implemented but requires comprehensive testing. Core recurrence functionality works correctly.

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
2. **Check current files first** - Use `view` tool in Priject files
3. **Test syntax before installing** - Use `python3 -m py_compile`
4. **Version all changes** - Update version numbers and dates
5. **Document in CHANGES.txt** - Track what changed and why
6. **Test incrementally** - One change at a time

---

**Remember:** Smart coding over quick fixes. Aim for reliable product!
