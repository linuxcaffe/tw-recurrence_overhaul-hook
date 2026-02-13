- Project: https://github.com/linuxcaffe/tw-recurrence_overhaul-hook
- Issues:  https://github.com/linuxcaffe/tw-recurrence_overhaul-hook/issues

# recurrence-overhaul

An enhanced recurrence system for Taskwarrior, implemented as hooks.

---

## TL;DR

- Chained recurrence — next task due relative to when you *complete* the last one
- Periodic recurrence — fixed schedule, same as built-in but without the mask problem
- Relative dates — `wait:due-7d`, `sched:due-2h` just work
- Attribute-agnostic — all template fields (UDAs, annotations, tags, project, priority) copy to instances automatically
- Comprehensive validation — catches errors before they become data problems
- Stealthy aliases — type `last:5` instead of `rlast:5`, `ty:c` instead of `type:chain`
- Three bundled reports — `templates`, `recurring`, `instances`
- Taskwarrior 2.6.2 only — replaces built-in recurrence entirely

---

## Why this exists

Taskwarrior's built-in recurrence has real limitations: it only supports
periodic (time-based) recurrence, the mask system grows unbounded, and there's
no way to say "mow the lawn 7 days after I actually do it."

This hook system replaces built-in recurrence with a template-instance model.
Templates store the recurrence rules. Instances are the actual tasks you see
and complete. When you complete an instance, the next one spawns automatically
with the correct dates.

Based on the
[Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html).

---

## Core concepts

- **Template**
  A task with `status:recurring` that stores the recurrence rules. Templates
  don't appear in your normal task list — they're the blueprint.

- **Instance**
  A regular pending task linked to a template via `rtemplate`. This is what
  you see, work on, and complete. Completing or deleting it spawns the next.

- **Chained recurrence** (`ty:c`)
  Next instance due relative to completion time. Good for habits, chores,
  exercise — anything where "every N days" means "after I actually do it."

- **Periodic recurrence** (`ty:p`, default)
  Fixed schedule from the template. Instance #2 is always template date +
  period, regardless of when you complete #1. Good for bills, meetings,
  appointments.

- **Anchor**
  The date field that recurrence calculations are based on — either `due`
  (default) or `scheduled`. Set with `anchor:sched` on the template.

- **Relative dates**
  Wait, scheduled, and until dates expressed as offsets from the anchor:
  `wait:due-7d`, `sched:due-2h`, `until:due+30d`. These are stored on
  the template and recalculated for each instance.

---

## Installation

### Option 1) Download and run the install file
```bash
chmod +x recurrence-overhaul.install  # then run it
recurrence-overhaul.install
```
copies hooks, library file, rc config and README
to directories under ~/.task, sets chmod and simlink

### Option 2) Via awesome-taskwarrior

```bash
tw -I recurrence-overhaul
```

### Option 3) Manual

```bash
cd ~/.task/hooks

# Copy the three hook files
cp on-add_recurrence.py on-exit_recurrence.py recurrence_common_hook.py .

# Make hooks executable (not the library)
chmod +x on-add_recurrence.py on-exit_recurrence.py

# Create the on-modify symlink
ln -s on-add_recurrence.py on-modify_recurrence.py

# Install configuration
cp recurrence.rc ~/.task/config/
```

Add to `~/.taskrc`:

```ini
include ~/.task/config/recurrence.rc
```

Verify:

```bash
task show | grep uda.type
task diag # see hooks section
```

---

## Usage

### Creating recurring tasks

**Chained** — next due relative to completion:

```bash
task add "Mow lawn" ty:c r:7d due:tomorrow
task add "Gym workout" ty:c r:3d due:tomorrow +health
task add "Meditate" ty:c r:1d due:today +habits
```

**Periodic** — fixed schedule (default type, `ty:p` optional):

```bash
task add "Pay rent" r:1mo due:eom
task add "Standup" r:1w due:monday +work
task add "Quarterly report" r:3mo due:2025-03-31 +work
```

**With relative dates:**

```bash
task add "Credit card" r:1mo due:15th wait:due-7d priority:H +finance
task add "Week review" r:1w due:friday sched:due-1h +review
```

**With an end date:**

```bash
task add "Beach cleanup" r:1w due:2025-06-01 rend:2025-08-31 +volunteer
```

**Using scheduled as anchor:**

```bash
task add "Daily standup" ty:c r:1d sched:tomorrow+9hrs wait:sched-90min
```

### Completing and deleting

```bash
task 42 done       # Completes instance, spawns next automatically
task 42 delete     # Deletes instance, spawns next automatically
```

Both completion and deletion trigger the next instance. The system never
leaves you without a pending instance for an active template.

### Viewing recurrence

Three bundled reports:

```bash
task templates     # All recurrence templates
task recurring     # Templates AND their instances together
task instances     # All instances (or filter by template)
```

The `R` column in reports shows an indicator for recurring instances.

### Modifying templates

Changes to recurrence fields auto-sync to the current instance:

```bash
task 5 modify r:14d           # Change period
task 5 modify ty:c            # Switch to chained
task 5 modify anchor:sched    # Change anchor to scheduled
task 5 modify last:10         # Time machine — jump to instance #10
```

Changes to non-recurrence fields show a suggested command:

```bash
task 5 modify priority:H      # Template updated
# "To apply to current instance: task 42 mod priority:H"
```

### Modifying instances

```bash
task 42 modify index:5        # Time machine — recalculates dates
```

Changing `index` on an instance auto-syncs `last` on the template and
recalculates all dates. This has basically no effect on chain type.

---

## Aliases

The hook accepts short, friendly names and translates them internally.
You never need to type the `r`-prefixed field names directly.

| You type | Hook stores | Notes |
|----------|-------------|-------|
| `ty:c` | `type:chain` | Also: `ty:ch`, `ty:chai`, `ty:chain` |
| `ty:p` | `type:period` | Also: `ty:pe`, `ty:per`. Default if omitted |
| `last:5` | `rlast:5` | Template modification only |
| `index:3` | `rindex:3` | Instance modification (time machine) |
| `anchor:sched` | `ranchor:sched` | Template modification only |
| `wait:due-2d` | `rwait:due-2d` | Relative dates stay relative |
| `wait:2026-03-15` | `rwait:due+Xs` | Absolute dates auto-convert to relative |
| `sched:due-1h` | `rscheduled:due-1h` | Same conversion rules |
| `until:due+7d` | `runtil:due+7d` | Same conversion rules |

Absolute dates on templates are automatically converted to relative offsets
from the anchor. This ensures instances always get correctly calculated dates.

---

## Recurrence fields

| Field | Where | Purpose |
|-------|-------|---------|
| `r` | Template | Recurrence period: `1d`, `7d`, `1w`, `1mo`, `3mo`, `1y` |
| `type` | Template | `chain` or `period` (default: period) |
| `ranchor` | Template | Anchor field: `due` or `sched` (default: due) |
| `rlast` | Template | Index of last spawned instance |
| `rend` | Template | Stop creating instances after this date |
| `rwait` | Template | Relative wait offset: `due-7d` |
| `rscheduled` | Template | Relative scheduled offset: `due-2h` |
| `runtil` | Template | Relative until offset: `due+30d` |
| `rtemplate` | Instance | UUID of parent template |
| `rindex` | Instance | This instance's sequence number |

---

## Validation

The hook validates input and blocks errors before they corrupt data.

**Blocked with error:**
- Template without anchor date (due or scheduled)
- Template with wait date after anchor
- Template with until date before anchor
- Invalid period format
- `rend` date in the past
- Adding `r` to an existing instance
- Changing `rtemplate` on an instance

**Warned and cleaned up:**
- Legacy fields (`recur`, `mask`, `imask`, `parent`) — stripped automatically
- Instance-only fields on templates — removed
- Template-only fields on instances — removed

---

## How it works

### Architecture

Three files, one symlink:

| File | Hook type | Purpose |
|------|-----------|---------|
| `on-add_recurrence.py` | on-add | Template creation, validation |
| `on-modify_recurrence.py` | on-modify | Symlink → on-add. Template/instance modification |
| `on-exit_recurrence.py` | on-exit | Instance spawning, spool processing |
| `recurrence_common_hook.py` | library | Shared utilities, date parsing, spawn logic |

### Template-instance lifecycle

```
1. User: task add "Mow lawn" ty:c r:7d due:tomorrow
2. on-add: Creates template (status:recurring, rlast:1)
3. on-exit: Sees new template, spawns instance #1
4. User: task 42 done
5. on-exit: Sees completed instance, spawns instance #2
   - Chain: due = completion_time + 7d
   - Period: due = template_due + 7d
6. Repeat from step 4
```

### Spool file pattern

Template modifications can't directly update instances during on-modify
(Taskwarrior holds a file lock). Instead, on-modify writes a JSON spool
file (`~/.task/recurrence_propagate.json`) and on-exit processes it after
the lock is released.

### Attribute-agnostic copying

When spawning instances, everything copies from the template except:
system fields (`uuid`, `id`, `entry`, `modified`, `status`), legacy fields
(`recur`, `mask`), template-only fields (`r`, `type`, `rlast`), and
instance-only fields (`rtemplate`, `rindex`). All UDAs, annotations,
dependencies, tags, project, and priority carry over automatically.

---

## Debug mode

```bash
export DEBUG_RECURRENCE=1
task add "Test" ty:c r:1d due:tomorrow
tail -f ~/.task/recurrence_debug.log
```

Debug output shows template creation, alias expansion, validation,
instance spawning, date calculations, and field copying. Useful for
understanding exactly what happened and why.

---

## Troubleshooting

**Hooks not running?**

```bash
task show | grep hooks     # Should show hooks=1
ls -la ~/.task/hooks/on-*  # Should be executable (except _hook.py library)
```

**No instances created?**

```bash
task templates              # Verify template exists
export DEBUG_RECURRENCE=1
task list                   # Trigger on-exit hook
cat ~/.task/recurrence_debug.log
```

**Wrong due dates?**

For chained: check completion time in debug log — next due = completion + period.
For periodic: verify template's anchor date — instance N due = template + (N-1) × period.

**Legacy field warnings?**

Taskwarrior 2.6.2 synthesizes legacy fields (`rtype`) into JSON passed to
hooks for `status:recurring` tasks. These are silently stripped. You'll only
see a warning if you explicitly add a legacy field like `recur:weekly`.

---

## Project status

Active development. Core functionality — template creation, instance spawning,
chained and periodic recurrence, validation, attribute-agnostic copying,
and bidirectional sync — is working and in daily use.

---

## Further reading

- [DEVELOPERS.md](DEVELOPERS.md) — architecture, internals, hook API details
- [Taskwarrior Recurrence RFC](https://djmitche.github.io/taskwarrior/rfcs/recurrence.html) — the design this implements

---

## Metadata

- License: MIT
- Language: Python
- Requires: Taskwarrior 2.6.2, Python 3
- Files: 3 Python files + 1 symlink + 1 config
- Version: 2.6.3
