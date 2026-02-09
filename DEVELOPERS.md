# Taskwarrior Enhanced Recurrence - Developer Documentation

**Version:** 2.6.2  
**Status:** Production Ready ✓  
**Last Updated:** 2026-02-08

---

## Quick Links

- **[Spool File Pattern](SPOOL_PATTERN.md)** - Deep dive on template↔instance propagation
- **[Installation](#installation)** - Get started quickly
- **[Debugging](#debugging)** - Troubleshooting guide

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
├── on-exit_recurrence.py          (executable) - Spawns instances, processes spool
├── recurrence_common_hook.py      (library)    - Shared utilities (NOT executable)
└── on-modify_recurrence.py        (symlink)    → on-add_recurrence.py
```

### Core Principles

1. **on-add/on-modify** - Template creation, modification detection, spool writing
2. **on-exit** - Instance spawning, spool processing (ONLY place that modifies other tasks)
3. **Users** - Task deletion (hooks never delete tasks)
4. **Spool file** - Deferred execution for template↔instance synchronization

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
on-exit: Spawns instance #2 (rindex:2), updates template rlast:2
```

See **[SPOOL_PATTERN.md](SPOOL_PATTERN.md)** for complete propagation flow details.

---

## File Structure

### on-add_recurrence.py (1041 lines)

**Purpose:** Template creation and modification handler, spool writer

**Key Features:**
- Template creation with type normalization (c→chain, p→period)
- User-friendly aliases (wait→rwait, ty→type, last→rlast)
- Modification tracking with detailed user feedback
- Spool file writing for template↔instance propagation
- Attribute validation and cleanup

**What it does NOT do:**
- ❌ No instance spawning (on-exit does that)
- ❌ No task deletion
- ❌ No direct modification of other tasks (uses spool instead)

### on-exit_recurrence.py (361 lines)

**Purpose:** Instance spawning and spool processing

**What it does:**
- **FIRST:** Processes spool file (template↔instance sync)
- Spawns instances when templates created or instances complete
- Updates template rlast after spawning
- Checks rend dates before spawning

### recurrence_common_hook.py (535 lines)

**Purpose:** Shared utility library

**Key Functions:**
- Date/duration parsing (7d, 1w, due-2d, etc.)
- Type normalization
- Task querying
- Debug logging

---

## Data Model

### Template (status:recurring)

**Required:**
- `status:recurring`, `r` (period), `type` (chain|period)
- `rlast` (last spawned index), `ranchor` (due|sched)
- `due` OR `scheduled` (one required)

**Optional:**
- `rwait`, `rscheduled`, `runtil` (relative dates)
- `rend` (stop spawning after)
- `project`, `priority`, `tags`

**Forbidden:**
- ❌ `rtemplate`, `rindex` (instance-only)

### Instance (status:pending/etc)

**Required:**
- `rtemplate` (parent UUID), `rindex` (sequence)
- `due` OR `scheduled`
- `+RECURRING` tag (auto-added)

**Inherited:**
- `project`, `priority`, `tags`
- `wait`, `scheduled`, `until` (calculated from template)

**Forbidden:**
- ❌ `r`, `type`, `rlast`, `ranchor`, etc. (template-only)

---

## Hook Behavior

### on-add: New Task with r Field

```bash
task add "Gym" r:7d due:tomorrow ty:c
```

Creates template with `status:recurring`, `rlast:1`, normalized type.  
Output: "Created recurrence template. First instance will be generated on exit."

### on-modify: Time Machine

```bash
task 72 mod rlast:5
```

Writes spool file with instance updates.  
Output: "Instance #1 will be synced."

### on-exit: Spool Processing + Spawning

1. Reads spool file (if exists)
2. Executes modifications
3. Spawns new instances as needed

Output: "Instance #1 synced (rlast)."

---

## Critical Rules

### The Invariant
**rlast MUST equal highest active rindex**

### One-to-One Rule
**Every active template has exactly ONE pending instance**

### Attribute Separation
Templates and instances have separate attribute sets. Hooks auto-remove misplaced attributes.

### Responsibility Boundaries
- **Spawning:** ONLY on-exit
- **Modification:** ONLY on-exit (via spool)
- **Deletion:** ONLY users

---

## Installation

```bash
# 1. Copy files
cp on-add_recurrence.py ~/.task/hooks/
cp on-exit_recurrence.py ~/.task/hooks/
cp recurrence_common_hook.py ~/.task/hooks/

# 2. Set permissions
chmod +x ~/.task/hooks/on-add_recurrence.py
chmod +x ~/.task/hooks/on-exit_recurrence.py
chmod -x ~/.task/hooks/recurrence_common_hook.py

# 3. Create symlink
cd ~/.task/hooks
ln -sf on-add_recurrence.py on-modify_recurrence.py

# 4. Verify
ls -la ~/.task/hooks/on-*.py
```

Add UDAs to `~/.taskrc` (see recurrence.rc).

Test:
```bash
export DEBUG_RECURRENCE=1
task add "Test" r:1d due:tomorrow
```

---

## Debugging

### Enable Debug Logging

```bash
export DEBUG_RECURRENCE=1
```

Creates `~/.task/recurrence_debug.log`.

### Common Patterns

**Template creation:**
```
ADD/MOD: Creating template
EXIT: spawning first instance
```

**Time machine:**
```
ADD/MOD: Wrote propagation spool
EXIT: Processing propagation spool
EXIT: Propagation successful
```

### Troubleshooting

**Hook not running?**
- Check executable: `ls -la ~/.task/hooks/on-*.py`
- Check enabled: `task show | grep hooks`

**Time machine not working?**
- Check debug log: `grep spool ~/.task/recurrence_debug.log`
- Verify no stale spool: `ls ~/.task/recurrence_propagate.json`

### Python Bytecode Prevention

```bash
# Add to ~/.bashrc
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX=/dev/null
```

---

## Known Issues

### rwait Propagation
Modifying template `rwait` doesn't calculate instance updates.  
**Workaround:** Manually update instance.

---

## Development Workflow

```bash
# Test changes
rm -rf ~/.task/hooks/__pycache__
cp on-add_recurrence.py ~/.task/hooks/
chmod +x ~/.task/hooks/on-add_recurrence.py
export DEBUG_RECURRENCE=1
task add "Test" r:1d due:tomorrow

# Check results
tail -50 ~/.task/recurrence_debug.log
```

---

## What v2.6.2 Has

✅ Template creation  
✅ Instance spawning  
✅ Periodic and chained recurrence  
✅ **Spool file pattern** (template↔instance sync)  
✅ **Time machine** (rlast modification)  
✅ **Bidirectional sync** (rindex ↔ rlast)  
✅ User-friendly aliases  
✅ Comprehensive feedback  
✅ Debug logging  
✅ Attribute validation  
✅ Python bytecode prevention  

---

## References

- **[SPOOL_PATTERN.md](SPOOL_PATTERN.md)** - Technical deep dive
- **[README.md](README.md)** - User documentation
- `~/.task/recurrence_debug.log` - Runtime log

---

**Remember:** Smart coding over quick fixes!
