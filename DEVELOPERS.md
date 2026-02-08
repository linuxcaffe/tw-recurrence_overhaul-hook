# Taskwarrior Enhanced Recurrence - Developer Documentation

**Version:** 0.5.0  
**Status:** Core Working ✔ | Template↔Instance Propagation Working ✔  
**Last Updated:** 2026-02-07

## Version 0.5.0 Changes

**Major: Template↔Instance Propagation via Spool File**

The defining challenge of this project: when the user modifies a recurrence attribute on a
template (e.g., `task <tmpl> mod rlast:3`), the corresponding instance must be updated in
the same command. One user action → two tasks modified.

After extensive testing of multiple approaches (see [Lessons Learned](#lessons-learned)),
we discovered that Taskwarrior 2.6.2 holds a **file lock on `pending.data` during on-modify
hook execution**. Any subprocess `task modify` called from within on-modify reports success
(exit code 0) but the write is silently lost. The solution is the **spool file pattern**:

- `on-modify` calculates instance updates → writes `~/.task/recurrence_propagate.json`
- `on-exit` (runs after lock release) → reads spool → executes modification → deletes spool

This works bidirectionally:
- Template `rlast` change → propagates `rindex` + recalculated dates to instance
- Instance `rindex` change → propagates `rlast` back to template
- Template `r` (period) change → recalculates instance `due` date
- Template `rwait`/`rscheduled`/`runtil` change → recalculates instance `wait`/`scheduled`/`until`

**Bug Fixes:**
- Added minute support to `parse_relative_date`: `m`, `min`, `minutes` (was only `mo` for months)
- Added hour support to on-exit's local `parse_relative_date` (was missing `h`/`hours`)

**Anti-`__pycache__` Hardening:**
- All three files now set `sys.dont_write_bytecode = True` at the very top, before any imports
- No more stale bytecode, ever

**Re-entrancy Safety Net:**
- `RECURRENCE_PROPAGATING` environment variable guard in `main()` — if a subprocess somehow
  triggers on-modify with hooks enabled, it passes through without cascading

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [The Spool File Pattern](#the-spool-file-pattern)
3. [File Structure](#file-structure)
4. [Data Model](#data-model)
5. [Hook Behavior](#hook-behavior)
6. [Critical Rules](#critical-rules)
7. [Installation](#installation)
8. [Debugging](#debugging)
9. [Known Issues](#known-issues)
10. [Lessons Learned](#lessons-learned)
11. [Development Workflow](#development-workflow)

---

## Architecture Overview

### Three-File System

```
~/.task/hooks/
├── on-add_recurrence.py           (executable) - Creates templates, handles modifications
├── on-exit_recurrence.py          (executable) - Spawns instances + processes spool
├── recurrence_common_hook.py      (library)    - Shared utilities (NOT executable)
└── on-modify_recurrence.py        (symlink)    → on-add_recurrence.py
```

### Transient File

```
~/.task/recurrence_propagate.json  (spool)      - Exists for milliseconds during propagation
```

### Core Principles

1. **on-add/on-modify** = Template creation, modification detection, spool writing
2. **on-exit** = Instance spawning + spool processing (the ONLY place that modifies other tasks)
3. **Users** = Deletion (ONLY — hooks never delete tasks)
4. **No subprocess `task modify` from within on-modify** — file lock prevents it

### Data Flow

```
User: task add "Gym" r:7d due:tomorrow
  │
on-add: Creates template (status:recurring, rlast:1)
  │
on-exit: Spawns instance #1 (status:pending, rindex:1)
  │
User: task <id> done
  │
on-modify: Detects instance completion
  │
on-exit: Spawns instance #2 (rindex:2), updates template rlast:2
```

### Propagation Flow (Template → Instance)

```
User: task <template> modify r:14d
  │
on-modify: Detects recurrence field change on template
  │         Calculates new instance dates
  │         Writes ~/.task/recurrence_propagate.json
  │         (CANNOT subprocess here — file lock!)
  │
on-exit: Reads spool file
  │       Executes: task rc.hooks=off <instance> modify due:<new> ...
  │       Deletes spool file
  │       Outputs: "Instance #N synced (r)."
```

### Propagation Flow (Instance → Template)

```
User: task <instance> modify rindex:5
  │
on-modify: Detects rindex change (TIME MACHINE)
  │         Writes spool: {updates: {rlast: "5"}, target: template_uuid}
  │
on-exit: Reads spool
  │       Executes: task rc.hooks=off <template> modify rlast:5
  │       Deletes spool file
```

---

## The Spool File Pattern

### Why It Exists

Taskwarrior 2.6.2 holds a file lock on `pending.data` for the entire duration of hook
execution. This means:

- `on-add` hooks: lock held while hook runs
- `on-modify` hooks: lock held while hook runs
- `on-exit` hooks: lock **released** before hook runs

Any `subprocess.run(['task', ..., 'modify', ...])` called from within on-add or on-modify
will appear to succeed (exit code 0) but the changes will not persist to disk.

### Spool File Format

```json
{
  "instance_uuid": "bfbf7c0c-69fc-4422-a839-dd71de38a94a",
  "instance_rindex": "3",
  "updates": {
    "rindex": "5",
    "due": "20260208T010414Z",
    "wait": "20260208T004414Z"
  },
  "template_id": "72",
  "changes": ["rlast"]
}
```

### Lifecycle

1. **on-modify** writes the file (atomic JSON dump)
2. **on-exit** checks for the file at the start of `process_tasks()`
3. **on-exit** reads it, executes the modification with `rc.hooks=off`, deletes it
4. File exists for typically < 100ms

### Error Handling

- If the spool file is malformed → on-exit logs the error, deletes the file
- If the modification fails → on-exit reports a warning to the user
- If on-exit doesn't run (crash) → stale spool file will be processed on next task command

---

## File Structure

### on-add_recurrence.py (~1080 lines)

**Purpose:** Template creation and modification handler, spool file writer

**Key Functions:**
- `RecurrenceHandler.create_template()` — Convert new task with `r` into template
- `RecurrenceHandler.handle_template_modification()` — Detect recurrence field changes,
  calculate instance updates, write spool file
- `RecurrenceHandler.handle_instance_modification()` — Detect rindex changes (TIME MACHINE),
  write spool file for template sync
- `RecurrenceHandler.handle_instance_completion()` — Track completion/deletion
- `RecurrenceHandler.calculate_instance_updates()` — Core logic for determining what fields
  on an instance need to change when template recurrence attributes change
- `query_task()` — Query Taskwarrior for task by UUID
- `query_instances()` — Query instances for a template
- `update_task()` — Modify task via Taskwarrior command (used for non-propagation updates)

**What on-add/on-modify does:**
- Normalizes recurrence types (c→chain, p→period)
- Converts absolute dates to relative (wait→rwait, scheduled→rscheduled, until→runtil)
- Detects anchor changes (due↔sched)
- Validates template/instance attribute separation
- Writes propagation spool for on-exit

**What on-add/on-modify does NOT do:**
- ✗ Does NOT spawn instances
- ✗ Does NOT delete instances
- ✗ Does NOT subprocess `task modify` for propagation (file lock prevents it)

### on-exit_recurrence.py (~460 lines)

**Purpose:** Instance spawning + spool file processing

**Key Functions:**
- `RecurrenceSpawner.process_tasks()` — Main loop: process spool first, then handle
  completed/deleted instances
- `RecurrenceSpawner.get_template()` — Fetch template by UUID (dual-method with fallback)
- `RecurrenceSpawner.check_rend()` — Check if recurrence has ended

**Spawning Logic:**
```python
# For periodic type:
anchor_date = template_anchor + (recur_delta × (index - 1))

# For chained type:
anchor_date = completion_time + recur_delta
```

**What on-exit does:**
- Processes propagation spool file (template↔instance sync)
- Spawns instance #1 when template is created (rlast in [0, 1, ''])
- Spawns next instance when current one completes/deletes
- Only spawns for the LATEST instance (rindex ≥ rlast)
- Checks rend date before spawning

**What on-exit does NOT do:**
- ✗ Does NOT modify templates (except via spool file instructions)
- ✗ Does NOT create templates

### recurrence_common_hook.py (~535 lines)

**Purpose:** Shared utility library

**Key Functions:**
- `normalize_type()` — Convert type abbreviations to full names
- `parse_duration()` — Parse '7d', '1w', '30m', 'P1D' to timedelta
- `parse_date()` — Parse ISO 8601 dates (20260206T120000Z)
- `format_date()` — Format datetime to ISO 8601
- `parse_relative_date()` — Parse 'due-2d', 'sched+1w', 'wait-30m', 'due-4h'
- `is_template()` — Check if task is template
- `is_instance()` — Check if task is instance
- `get_anchor_field_name()` — Map 'sched'→'scheduled', 'due'→'due'
- `debug_log()` — Conditional logging to file
- `check_instance_count()` — Targeted instance checking (NOT global)
- `query_instances()` — Query instances for specific template
- `spawn_instance()` — Create new instance with proper verbosity control
- `delete_instance()` — Delete an instance task

**Supported Duration Units (in parse_relative_date):**
```
s, seconds    — seconds
m, min, minutes — minutes
h, hours      — hours
d, days       — days
w, weeks      — weeks
mo, months    — months (30 days)
y, years      — years (365 days)
```

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
  "rlast": "1",            // Last spawned instance index (string type UDA)
  "ranchor": "due|sched",  // Which field is the anchor
  "due": "20260210T000000Z" // OR scheduled (one required)
}
```

**Optional Fields:**
```json
{
  "rwait": "due-172800s",      // Relative wait (offset from anchor)
  "rscheduled": "due-86400s",  // Relative scheduled
  "runtil": "sched+14400s",    // Relative until (offset from anchor)
  "rend": "20261231T235959Z",  // Stop spawning after this date
  "project": "work",
  "priority": "H",
  "tags": ["important"]
}
```

**Templates should NOT have:**
- ✗ `rtemplate` — Only instances have this
- ✗ `rindex` — Only instances have this

### Instance (status:pending/completed/etc)

**Required Fields:**
```json
{
  "status": "pending",
  "rtemplate": "UUID",     // Parent template UUID
  "rindex": "1",           // Instance sequence number (string type UDA)
  "due": "20260210T000000Z" // OR scheduled
}
```

**Inherited from Template:**
- `project`, `priority`, `tags` (non-recurrence)
- `wait`, `scheduled`, `until` (calculated from rwait/rscheduled/runtil)

**Instances do NOT have:**
- ✗ `r`, `type`, `rlast`, `ranchor`, `rwait`, `rscheduled`, `runtil`, `rend`

### UDA Types

Both `rlast` and `rindex` are **string** type UDAs. This avoids numeric coercion
issues in Taskwarrior 2.6.2. The hook code handles `int()` conversion where needed
for arithmetic.

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
6. Convert `scheduled` to `rscheduled` if present (when anchor is due)
7. Convert `until` to `runtil` if present

### on-modify Behavior

#### Template Recurrence Attribute Change
```bash
task <template> mod rlast:3     # Time machine
task <template> mod r:14d       # Change period
task <template> mod rwait:due-30m   # Add/change relative wait
```

**Actions:**
1. Detect recurrence field changes (r, type, ranchor, rlast, rend, rwait, rscheduled, runtil)
2. Query for current instance
3. Calculate instance updates via `calculate_instance_updates()`
4. Write `~/.task/recurrence_propagate.json` for on-exit
5. Output: "Template N modified: rlast. Instance #1 will be synced."

#### Instance rindex Change (TIME MACHINE from instance side)
```bash
task <instance> mod rindex:5
```

**Actions:**
1. Detect rindex change
2. Query template
3. Write spool file with `{rlast: "5"}` targeting template
4. Output: "Instance N rindex changed: 1 → 5. Template rlast will be synced."

#### Template Non-Recurrence Field Change
```bash
task <template> mod project:home
```

**Actions:**
1. Detect non-recurrence field change
2. Inform user with suggested command to apply to instance
3. Output: "Non-recurrence fields changed: project. To apply to current instance: task N mod project:home"

### on-exit Behavior

#### Spool File Processing (FIRST, before anything else)
1. Check for `~/.task/recurrence_propagate.json`
2. If present: read, execute `task rc.hooks=off <uuid> modify ...`, delete file
3. Report result to user

#### New Template Created
1. Detect template with rlast in ['0', '1', '']
2. Check no instance already exists (prevent duplicate spawning)
3. Spawn instance #1
4. Update template rlast to 1

#### Instance Completed/Deleted
1. Detect completed or deleted instance
2. Query template
3. Check if rindex ≥ rlast (is this the latest?)
4. If yes, spawn next instance (rindex + 1)
5. Update template rlast

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

### Attribute Separation

```python
TEMPLATE_ONLY = {'r', 'type', 'ranchor', 'rlast', 'rend', 'rwait', 'rscheduled', 'runtil'}
INSTANCE_ONLY = {'rtemplate', 'rindex'}
```

If attributes cross over, hooks auto-remove them with warnings.

### No Subprocess from on-modify

**NEVER call `subprocess.run(['task', ..., 'modify', ...])` from within on-add or on-modify hooks.**

Taskwarrior holds a file lock on `pending.data` during these hooks. The subprocess will
report success but changes will not persist. Use the spool file pattern instead.

### Spawning Responsibility

- on-add/on-modify: Creates templates ✓, Detects changes ✓, Writes spool ✓, Spawns ✗
- on-exit: Processes spool ✓, Spawns instances ✓, Modifies via spool ✓

### Deletion Responsibility

**ONLY users delete tasks** — hooks NEVER delete tasks.

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

# 4. Nuke any pycache
find ~/.task/hooks -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null
find ~/.task/hooks -name '*.pyc' -delete 2>/dev/null

# 5. Verify
ls -la ~/.task/hooks/on-*.py ~/.task/hooks/recurrence_common_hook.py
```

---

## Debugging

### Enable Debug Logging

```bash
DEBUG_RECURRENCE=1 task add "Test" r:1d due:tomorrow
cat ~/.task/recurrence_debug.log
```

Or export for a whole session:
```bash
export DEBUG_RECURRENCE=1
```

### Debug Log Format

```
[2026-02-07 14:10:34] PREFIX: message
```

**Prefixes:**
- `ADD/MOD` — on-add/on-modify hook
- `EXIT` — on-exit hook
- `COMMON` — recurrence_common_hook library

### Python Bytecode Cache

All three files set `sys.dont_write_bytecode = True` at the top, so `__pycache__` should
never be created. If you still encounter stale behavior:

```bash
find ~/.task -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find ~/.task -type f -name "*.pyc" -delete 2>/dev/null
```

### Verifying Propagation

```bash
# Check if spool file was written (should be gone by the time you look):
ls -la ~/.task/recurrence_propagate.json

# If it persists, on-exit didn't process it. Check:
cat ~/.task/recurrence_propagate.json
task diagnostics | grep -A10 Hooks
```

---

## Known Issues

### 1. Instance dates not recalculated on TIME MACHINE (instance→template direction)

When changing `rindex` on an instance, the template's `rlast` is synced but the instance's
`due` date is not recalculated. The user needs to then modify the template's `rlast` to
trigger a full recalculation. This is because the spool file currently only carries `rlast`
for the template update, not recalculated dates for the instance.

### 2. On-exit has duplicate utility methods

`RecurrenceSpawner` in on-exit still has local copies of `parse_duration()`,
`parse_date()`, `format_date()`, and `parse_relative_date()` that duplicate the common
module. These should eventually be removed in favor of the common module imports.

---

## Lessons Learned

### The File Lock Discovery

The single most important discovery in this project: **Taskwarrior 2.6.2 holds a file lock
on `pending.data` during on-add and on-modify hook execution.** This is undocumented and
manifests as silent data loss — subprocess calls to `task modify` return exit code 0 but
changes are not persisted.

**Approaches tried and failed:**

1. **Direct subprocess from on-modify** (hooks enabled) — Changes lost due to file lock.
   The subprocess `task modify` succeeded but wrote to a locked file.

2. **Direct subprocess from on-modify** (rc.hooks=off) — Same result. `rc.hooks=off`
   prevents hook re-entrancy but doesn't release the parent's file lock.

3. **Environment variable re-entrancy guard** (RECURRENCE_PROPAGATING) — The guard worked
   perfectly for preventing cascading hook calls, but the underlying file lock problem
   remained. The re-entrant on-modify correctly passed through, on-exit even confirmed
   the new field values — but nothing persisted.

**What works:** The spool file pattern. `on-modify` writes instructions to a JSON file.
`on-exit` runs after Taskwarrior releases the lock, reads the instructions, executes the
modification, and deletes the file.

### `__pycache__` Pain

Python's bytecode cache (`__pycache__/`) caused persistent debugging confusion. Edits to
hook scripts would not take effect because Python loaded cached `.pyc` files. The fix:
`sys.dont_write_bytecode = True` as the very first statement after `import sys` in every
file. This must come before any other imports, including the common module.

### Minutes vs Months in Regex

The relative date parser regex originally had `mo` for months but no `m` for minutes.
This meant `rwait:due-30m` silently failed to parse (returned None), causing
`calculate_instance_updates` to report "No instance updates calculated." The fix was adding
`m|min|minutes?` to the regex, with careful ordering so `min` matches before `mo`.

### UDA Type: String over Numeric

`rlast` and `rindex` are defined as `type=string` UDAs. Numeric UDAs in Taskwarrior 2.6.2
can cause coercion issues. String type ensures what you put in is exactly what you get back.
The hook code handles `int()` conversion internally where arithmetic is needed.

---

## Development Workflow

### Testing Changes

```bash
# 1. Nuke caches
find ~/.task/hooks -name '__pycache__' -exec rm -rf {} + 2>/dev/null

# 2. Copy new files
cp on-add_recurrence.py ~/.task/hooks/
cp on-exit_recurrence.py ~/.task/hooks/
cp recurrence_common_hook.py ~/.task/hooks/

# 3. Enable debug
export DEBUG_RECURRENCE=1

# 4. Create test task
task add "Test" r:1h due:now+2h ty:p +test pro:tw.rec

# 5. Test propagation (note template and instance IDs)
task <template> mod rlast:3
task <instance> export | python3 -m json.tool | grep -E 'rindex|due'

# 6. Test rwait propagation
task <template> mod rwait:due-30m
task <instance> export | python3 -m json.tool | grep wait

# 7. Test reverse sync
task <instance> mod rindex:1
task <template> export | python3 -m json.tool | grep rlast

# 8. Check debug log
tail -30 ~/.task/recurrence_debug.log
```

### Code Modification Guidelines

1. **Always set `sys.dont_write_bytecode = True`** at the top of every file
2. **Never subprocess `task modify` from on-add/on-modify** — use spool file
3. **Check current files first** — Use `view` tool on Project files
4. **Test syntax before installing** — `python3 -m py_compile <file>`
5. **Version all changes** — Update version numbers and dates
6. **Test incrementally** — One change at a time
7. **Use `DEBUG_RECURRENCE=1`** to trace execution flow

---

**Remember:** Taskwarrior hooks can't modify other tasks during on-modify. Use the spool. Trust the spool.
